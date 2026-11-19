"""Controller (the C of MVC): video endpoints."""
import json
import os
import re
import subprocess
import threading
from pathlib import Path

from flask import Blueprint
from mongoengine import Q

from app.http import register
from app.models import Clip, Video, now, oid
from app.runtime import STATUSES, TWITCH_STATUSES
from app.services.upload_service import _notify_uploaded, approve_video, decline_video, push_thumbnail
from app.utils.paths import inside_outputs
from app.views.serializers import _vid


def _video_for(h, vid: str):
    """A video the signed-in member may touch: their own (the owner may open any member's video)."""
    doc = Video.find_one(id=oid(vid))
    if doc and (doc.get("user_id") == h.uid or h.is_owner()):
        return doc
    return None


def h_videos(h):
    flt = {k: h.q[k] for k in ("kind", "status", "game_id") if h.q.get(k)}
    flt["user_id"] = h.uid
    tw, cond = h.q.get("twitch"), Q()
    if tw == "pending":  # older records have no twitch field: they count as pending
        cond = Q(__raw__={"twitch.status": "pending"}) | Q(__raw__={"twitch": {"$exists": False}})
    elif tw in TWITCH_STATUSES:
        cond = Q(__raw__={"twitch.status": tw})
    docs = Video.find_all(cond, order=("-created_at",), limit=200, **flt)
    h.send_json(200, [_vid(x) for x in docs])


def h_video(h, vid):
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    h.send_json(200, _vid(doc))


def h_video_twitch(h, vid):
    """Record the manual Twitch upload: {status: pending|uploaded|skipped, url?}."""
    data = h.body_json()
    status = data.get("status")
    if status not in TWITCH_STATUSES:
        raise ValueError(f"status must be one of {sorted(TWITCH_STATUSES)}")
    url = str(data.get("url", "")).strip()
    if url and not (url.startswith("https://") and "twitch.tv" in url.split("/")[2]):
        raise ValueError("url must be a https://…twitch.tv link")
    upd = {"twitch.status": status, "twitch.url": url or None,
           "twitch.updated_at": now()}
    if not _video_for(h, vid):
        return h.send_json(404, {"error": "not found"})
    if not Video.update_where(id=oid(vid), fields=upd):
        return h.send_json(404, {"error": "not found"})
    h_video(h, vid)


def h_video_reveal(h, vid):
    """Open the folder with the video selected in Windows Explorer (handy for the manual upload; local owner only)."""
    if not (h.is_owner() and h.is_local() and os.name == "nt"):
        return h.send_json(403, {"error": "Use the Download button: opening folders only works on the owner's own computer."})
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    try:
        p = inside_outputs(doc.get("video_path", ""))
    except ValueError:
        return h.send_json(403, {"error": "path outside outputs/"})
    if not p.is_file():
        return h.send_json(404, {"error": "file missing on disk"})
    subprocess.Popen(["explorer", "/select,", str(p)])
    h.send_json(200, {"ok": True})


def h_video_patch(h, vid):
    if not _video_for(h, vid):
        return h.send_json(404, {"error": "not found"})
    data, upd = h.body_json(), {}
    for k in ("title", "description", "notes", "privacy_status", "youtube_id"):
        if k in data:
            upd[k] = str(data[k])[:5000]
    if "tags" in data:
        tags = data["tags"] if isinstance(data["tags"], list) else str(data["tags"]).split(",")
        upd["tags"] = [str(t).strip() for t in tags if str(t).strip()][:40]
    if "status" in data:
        if data["status"] not in STATUSES:
            raise ValueError(f"status must be one of {sorted(STATUSES)}")
        upd["status"] = data["status"]
    if upd.get("youtube_id"):
        upd["youtube_url"] = f"https://youtu.be/{upd['youtube_id']}"
    if not upd:
        raise ValueError("nothing to update")
    if not Video.update_where(id=oid(vid), fields=upd):
        return h.send_json(404, {"error": "not found"})
    h_video(h, vid)


def h_video_uploaded(h, vid):
    """Called by n8n after the YouTube upload."""
    data = h.body_json()
    yt = str(data.get("youtube_id", "")).strip()
    if not yt:
        raise ValueError("youtube_id required")
    privacy = data.get("privacy_status", "unlisted")
    n = Video.update_where(id=oid(vid), fields={
        "status": "public" if privacy == "public" else "uploaded", "youtube_id": yt,
        "youtube_url": f"https://youtu.be/{yt}", "privacy_status": privacy, "uploaded_at": now()})
    if n:
        threading.Thread(target=lambda: push_thumbnail(Video.find_one(id=oid(vid))), daemon=True).start()
    if n and privacy != "public":
        threading.Thread(target=_notify_uploaded, args=(vid,), daemon=True).start()
    h.send_json(200 if n else 404, {"ok": bool(n)})


def h_video_publish(h, vid):
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    ok, msg = approve_video(doc)
    h.send_json(200 if ok else 502, {"ok": ok, "message": msg} if ok else {"error": msg})


def h_video_thumbnail(h, vid):
    """Make the thumbnail again (new AI artwork) - for a video that is already rendered."""
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    vp = inside_outputs(doc.get("video_path", ""))
    if not vp or not Path(vp).is_file():
        return h.send_json(404, {"error": "The video file is missing."})
    meta = {}
    try:
        meta = json.loads(Path(vp).with_suffix(".json").read_text(encoding="utf-8"))
    except Exception:
        pass
    from app.engine import thumbnail_generator
    mode = "16:9" if doc.get("kind") == "compilation" else "9:16"
    out = inside_outputs(doc.get("thumbnail_path", "")) if doc.get("thumbnail_path") else None
    try:
        src = Path(vp)
        try:
            for cid in (doc.get("clip_ids") or [])[:1]:
                cdoc = Clip.find_one(id=cid)
                if cdoc and cdoc.get("path") and Path(cdoc["path"]).is_file() and mode == "9:16":
                    src = Path(cdoc["path"])   # the original clip has no blurred bars
        except Exception:
            pass
        p = thumbnail_generator.generate_thumbnail(
            video_path=src, headline=meta.get("thumb_headline") or doc.get("title", "")[:40],
            subtext=meta.get("thumb_subtext") or (doc.get("game_name") or ""), mode=mode,
            output_path=Path(out) if out else None, game_name=doc.get("game_name"))
    except Exception as e:
        return h.send_json(500, {"error": f"Could not make the thumbnail: {e}"})
    Video.update_where(id=doc["_id"], fields={"thumbnail_path": str(p)})
    doc = Video.find_one(id=doc["_id"])
    msg = "New thumbnail ready."
    if doc.get("youtube_id"):
        ok, why = push_thumbnail(doc)
        msg += " " + ("It is now on YouTube too." if ok else f"(Not updated on YouTube: {why})")
    h.send_json(200, {"ok": True, "message": msg})


def h_video_yt_thumbnail(h, vid):
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    ok, msg = push_thumbnail(doc)
    h.send_json(200 if ok else 502, {"ok": ok, "message": msg} if ok else {"error": msg})


def h_video_decline(h, vid):
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    ok, msg = decline_video(doc)
    h.send_json(200 if ok else 409, {"ok": ok, "message": msg} if ok else {"error": msg})


def h_video_delete(h, vid):
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    removed = []
    if h.q.get("files") == "1":
        for k in ("video_path", "thumbnail_path"):
            try:
                p = inside_outputs(doc.get(k, ""))
                if p.is_file():
                    p.unlink()
                    removed.append(p.name)
            except ValueError:
                pass
    Video.remove_where(id=doc["_id"])
    h.send_json(200, {"ok": True, "files_removed": removed})


def h_media(h, vid, which):
    doc = _video_for(h, vid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    try:
        p = inside_outputs(doc["video_path" if which == "video" else "thumbnail_path"])
    except (ValueError, KeyError):
        return h.send_json(403, {"error": "path outside outputs/"})
    if not p.is_file():
        return h.send_json(404, {"error": "file missing on disk"})
    dl = None
    if h.q.get("download") == "1":
        dl = (re.sub(r'[<>:"/\\|?*\x00-\x1f#]', "", doc.get("title") or "video").strip()[:80] or "video") + p.suffix
    h.send_file(p, filename=dl)


def h_file(h):  # used by n8n
    try:
        p = inside_outputs(h.q.get("path", ""))
    except (ValueError, OSError):
        return h.send_json(403, {"error": "path must be inside outputs/"})
    if not p.is_file():
        return h.send_json(404, {"error": "not found"})
    h.send_file(p)


ROUTES = [
    (r"/api/videos", "GET", h_videos),
    (r"/api/videos/([0-9a-f]{24})", "GET", h_video),
    (r"/api/videos/([0-9a-f]{24})", "PATCH", h_video_patch),
    (r"/api/videos/([0-9a-f]{24})", "DELETE", h_video_delete),
    (r"/api/videos/([0-9a-f]{24})/uploaded", "POST", h_video_uploaded),
    (r"/api/videos/([0-9a-f]{24})/publish", "POST", h_video_publish),
    (r"/api/videos/([0-9a-f]{24})/decline", "POST", h_video_decline),
    (r"/api/videos/([0-9a-f]{24})/thumbnail", "POST", h_video_thumbnail),
    (r"/api/videos/([0-9a-f]{24})/yt-thumbnail", "POST", h_video_yt_thumbnail),
    (r"/api/videos/([0-9a-f]{24})/twitch", "POST", h_video_twitch),
    (r"/api/videos/([0-9a-f]{24})/reveal", "POST", h_video_reveal),
    (r"/media/([0-9a-f]{24})/(video|thumb)", "GET", h_media),
    (r"/file", "GET", h_file),
]
bp = Blueprint("video", __name__)
register(bp, ROUTES)
