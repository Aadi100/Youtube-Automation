"""The video editor: sources (an upload, a part of a link, one of the member's videos), background tasks, and the finished render.

Nothing here costs tokens: cutting, layout, silence and face detection and captions all run on this server. The finished video goes
into the member's Videos list, held for their review (it is never uploaded by itself).
"""
import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from app.config import BASE_DIR, OUTPUT_DIR, TEMP_DIR
from app.engine import discovery, editor
from app.models import EditSource, Video, now, oid

UPLOAD_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
MAX_UPLOAD = 2 * 1024 ** 3
MAX_SOURCE_SECONDS = 3 * 3600
MAX_LINK_SECONDS = 20 * 60
KEEP_SOURCES = 8
LINK_RE = re.compile(r"^https://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|live/)[\w\-]{6,15}|youtu\.be/[\w\-]{6,15}|twitch\.tv/videos/\d{5,12}"
                     r"|twitch\.tv/[\w]{3,25}/(?:clip|video)/[\w\-]+|clips\.twitch\.tv/[\w\-]+|kick\.com/video/[0-9a-fA-F\-]{8,40}"
                     r"|kick\.com/[\w\-]{2,40}/(?:videos|clips)/[\w\-]+)[\w\-&=%.?/]*$")

TASKS: Dict[str, Dict] = {}
_LOCK = threading.Lock()
_RENDER = threading.Semaphore(1)         # one render at a time: the server is shared with the video runs
_DOWNLOAD = threading.Semaphore(2)


# ---------------------------------------------------------------- sources
def _unlink(p: Path) -> None:
    """Delete a file; on Windows a video that the browser is still playing cannot be deleted yet: it is left for the next clean-up."""
    try:
        Path(p).unlink(missing_ok=True)
    except OSError:
        pass


def src_dir(uid) -> Path:
    d = BASE_DIR / "inputs" / str(uid) / "editor"
    d.mkdir(parents=True, exist_ok=True)
    return d


def view(doc: Dict) -> Dict:
    return {"id": str(doc["_id"]), "title": doc.get("title") or "Video", "origin": doc.get("origin"), "duration": doc.get("duration"),
            "width": doc.get("width"), "height": doc.get("height"), "has_audio": doc.get("has_audio", True), "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
            "credit": doc.get("credit"), "face": doc.get("face")}


def get_source(uid, sid: str, is_owner: bool = False) -> Optional[Dict]:
    try:
        doc = EditSource.find_one(id=oid(sid))
    except Exception:
        return None
    if doc and (doc.get("user_id") == str(uid) or is_owner) and doc.get("path") and Path(doc["path"]).is_file():
        return doc
    return None


def list_sources(uid) -> List[Dict]:
    return [view(d) for d in EditSource.find_all(user_id=str(uid), order=("-created_at",), limit=KEEP_SOURCES) if d.get("path") and Path(d["path"]).is_file()]


def _prune(uid) -> None:
    """Keep the newest few sources; older downloads and uploads are deleted from the disk (finished videos are never touched)."""
    docs = EditSource.find_all(user_id=str(uid), order=("-created_at",))
    for d in docs[KEEP_SOURCES:]:
        if d.get("origin") != "video" and d.get("path"):
            _unlink(d["path"])
            _unlink(strip_path(d))
        EditSource.objects(id=d["_id"]).delete()


def _add(uid, title: str, path: Path, origin: str, info: Dict, **extra) -> Dict:
    doc = EditSource(user_id=str(uid), title=title[:120], origin=origin, path=str(path), created_at=now(), duration=info["duration"], width=info["width"],
                     height=info["height"], has_audio=info["has_audio"], **extra).save()
    _prune(uid)
    return view(EditSource.find_one(id=doc.id))


def save_upload(uid, name: str, stream, length: int) -> Dict:
    ext = Path(name or "").suffix.lower()
    if ext not in UPLOAD_EXT:
        raise ValueError("Upload an .mp4, .mov, .mkv, .webm or .m4v video.")
    if not 0 < length <= MAX_UPLOAD:
        raise ValueError("That file is too big (up to 2 GB).")
    out = src_dir(uid) / f"up_{secrets.token_hex(6)}{ext}"
    left = length
    try:
        with open(out, "wb") as f:
            while left > 0 and (chunk := stream.read(min(1 << 20, left))):
                f.write(chunk)
                left -= len(chunk)
        if left > 0:
            raise ValueError("The upload was cut off. Try again.")
        info = editor.probe(out)
        if info["duration"] > MAX_SOURCE_SECONDS:
            raise ValueError("That video is longer than 3 hours. Cut it first.")
    except Exception:
        out.unlink(missing_ok=True)
        raise
    return _add(uid, Path(name).stem or "My video", out, "upload", info)


def from_video(uid, vdoc: Dict) -> Dict:
    """Open one of the member's finished videos in the editor (the original file is never changed)."""
    p = Path(vdoc.get("video_path") or "")
    if not p.is_file():
        raise ValueError("That video's file is missing on the disk.")
    for d in EditSource.find_all(user_id=str(uid), origin="video"):
        if d.get("path") == str(p):
            return view(d)
    return _add(uid, vdoc.get("title") or "Video", p, "video", editor.probe(p), credit=(vdoc.get("credits") or [None])[0])


def strip_path(doc: Dict) -> Path:
    d = BASE_DIR / "state" / "filmstrips"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{doc['_id']}.jpg"


def filmstrip_for(doc: Dict) -> Path:
    p = strip_path(doc)
    if not p.is_file():
        editor.filmstrip(Path(doc["path"]), p, float(doc.get("duration") or 1))
    return p


def delete_source(uid, sid: str) -> bool:
    doc = get_source(uid, sid)
    if not doc:
        return False
    if doc.get("origin") != "video":
        _unlink(doc["path"])
    _unlink(strip_path(doc))
    EditSource.objects(id=doc["_id"]).delete()
    return True


# ---------------------------------------------------------------- background tasks
def start_task(uid, kind: str, fn: Callable[[Callable[[float, str], None]], Dict], gate: Optional[threading.Semaphore] = None) -> str:
    tid = secrets.token_hex(8)
    with _LOCK:
        for k in [k for k, v in TASKS.items() if time.time() - v["t"] > 7200]:
            TASKS.pop(k, None)
        TASKS[tid] = {"id": tid, "user": str(uid), "kind": kind, "status": "running", "pct": 0, "message": "Starting…", "result": None, "t": time.time()}

    def report(pct: float, msg: str = "") -> None:
        TASKS[tid]["pct"] = int(max(0, min(100, pct)))
        if msg:
            TASKS[tid]["message"] = msg

    def run() -> None:
        try:
            if gate:
                TASKS[tid]["message"] = "Waiting for the server…"
                gate.acquire()
            try:
                TASKS[tid]["result"] = fn(report)
                TASKS[tid].update(status="done", pct=100, message="Done")
            finally:
                if gate:
                    gate.release()
        except Exception as e:
            TASKS[tid].update(status="error", message=str(e)[:300] if isinstance(e, (ValueError, RuntimeError)) else f"{type(e).__name__}: {str(e)[:200]}")
        TASKS[tid]["t"] = time.time()
    threading.Thread(target=run, daemon=True).start()
    return tid


def task_view(uid, tid: str, is_owner: bool = False) -> Optional[Dict]:
    t = TASKS.get(tid)
    if not t or (t["user"] != str(uid) and not is_owner):
        return None
    return {k: t[k] for k in ("id", "kind", "status", "pct", "message", "result")}


def _active(uid, kind: str) -> bool:
    return any(t["user"] == str(uid) and t["kind"] == kind and t["status"] == "running" for t in TASKS.values())


# ---------------------------------------------------------------- opening a link
def _parse_time(v) -> float:
    return editor._secs(str(v)) if str(v or "").strip() else 0.0


def start_link(uid, url: str, start, end, safety_on: bool = True) -> str:
    url = (url or "").strip()
    if len(url) > 300 or not LINK_RE.match(url):
        raise ValueError("Paste a YouTube, Twitch or Kick video link (a stream replay, a video or a clip).")
    a, b = _parse_time(start), _parse_time(end)
    if (a or b) and (b - a < 5 or b - a > MAX_LINK_SECONDS):
        raise ValueError(f"Choose a part between 5 seconds and {MAX_LINK_SECONDS // 60} minutes long.")
    if _active(uid, "download"):
        raise ValueError("A download is already running. Wait for it to finish.")

    def work(report):
        report(5, "Reading the link…")
        info = json.loads(discovery._ytdlp("-J", "--no-playlist", url, capture=True, timeout=120))
        dur = float(info.get("duration") or 0)
        if safety_on and int(info.get("age_limit") or 0) >= 18:
            raise ValueError("That video is age-restricted, so it cannot be used.")
        win = None
        if a or b:
            if dur and a >= dur:
                raise ValueError(f"That video is only {int(dur)} seconds long.")
            win = (a, min(b, dur) if dur else b)
        elif dur > MAX_LINK_SECONDS:
            raise ValueError(f"That video is {int(dur // 60)} minutes long. Enter the start and end of the part you want (up to {MAX_LINK_SECONDS // 60} minutes).")
        who = info.get("channel") or info.get("uploader") or "Creator"
        title = info.get("title") or "Video"
        out = src_dir(uid) / f"link_{secrets.token_hex(6)}.mp4"
        report(25, "Downloading…")
        discovery._fetch(url, "editor", win, dur, out)
        report(90, "Preparing…")
        pr = editor.probe(out)
        credit = {"creator": who, "title": title, "platform": "twitch" if "twitch" in url else "kick" if "kick.com" in url else "youtube",
                  "video_url": info.get("webpage_url") or url, "channel_url": info.get("channel_url") or info.get("uploader_url")}
        return {"source": _add(uid, title, out, "link", pr, credit=credit)}
    return start_task(uid, "download", work, _DOWNLOAD)


# ---------------------------------------------------------------- Twitch past streams
def _dur_seconds(s: str) -> int:
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s or "")
    return int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0) if m else 0


def twitch_search(q: str) -> List[Dict]:
    q = (q or "").strip()
    if not 2 <= len(q) <= 40:
        raise ValueError("Type at least two letters of the streamer's name.")
    hdr = discovery._twitch_headers()
    r = requests.get(f"{discovery.HELIX}/search/channels", headers=hdr, params={"query": q, "first": 8}, timeout=30)
    r.raise_for_status()
    return [{"login": c["broadcaster_login"], "name": c["display_name"], "live": bool(c.get("is_live")), "avatar": c.get("thumbnail_url"), "game": c.get("game_name")}
            for c in r.json().get("data", [])]


def twitch_videos(login: str) -> Dict:
    hdr = discovery._twitch_headers()
    u = discovery._twitch_user(discovery.parse_creator("twitch", login)[1], hdr)
    r = requests.get(f"{discovery.HELIX}/videos", headers=hdr, params={"user_id": u["id"], "type": "archive", "first": 20}, timeout=30)
    r.raise_for_status()
    return {"name": u["display_name"], "login": u["login"], "videos": [
        {"id": v["id"], "title": v["title"], "seconds": _dur_seconds(v.get("duration")), "created_at": v.get("created_at"), "views": v.get("view_count"),
         "thumb": (v.get("thumbnail_url") or "").replace("%{width}", "320").replace("%{height}", "180"), "url": v["url"]} for v in r.json().get("data", [])]}


# ---------------------------------------------------------------- looking at a source
def auto_edit(uid, doc: Dict, remove_ums: bool) -> str:
    src, dur = Path(doc["path"]), float(doc["duration"])

    def work(report):
        report(10, "Listening for dead air…")
        segs = editor.auto_segments(dur, editor.silences(src, duration=dur))
        ums = 0
        if remove_ums and doc.get("has_audio", True):
            report(45, "Finding the ums (this takes a while)…")
            from app.engine.subtitles import transcribe_audio_to_words
            words = transcribe_audio_to_words(src, TEMP_DIR)
            cuts = editor.filler_cuts(words)
            ums = len(cuts)
            segs = editor.normalize(editor.subtract(segs, cuts), dur)
        if not segs:
            raise ValueError("Nothing is left after cutting. The video may be all quiet.")
        kept = sum(b - a for a, b in segs)
        return {"segments": segs, "removed": round(dur - kept, 1), "ums": ums}
    return start_task(uid, "analyze", work)


def find_face(uid, doc: Dict) -> str:
    src, dur = Path(doc["path"]), float(doc["duration"])

    def work(report):
        report(20, "Looking for the face…")
        face = editor.find_face(src, dur)
        if face:
            EditSource.objects(id=doc["_id"]).update_one(set__face=face)
        return {"face": face}
    return start_task(uid, "analyze", work)


# ---------------------------------------------------------------- render
def start_render(uid, doc: Dict, spec: Dict, title: str, description: str = "") -> str:
    info = {"duration": float(doc["duration"]), "width": int(doc["width"]), "height": int(doc["height"]), "has_audio": bool(doc.get("has_audio", True))}
    spec = editor.clean_spec(spec, info)
    title = " ".join((title or "").split())[:100] or (doc.get("title") or "My edit")
    if _active(uid, "render"):
        raise ValueError("You already have a video rendering. Wait for it to finish.")
    from app.services import token_service as tokens
    why = tokens.small_shortfall(uid, "editor_render")
    if why:
        raise ValueError(why)
    total = sum(b - a for a, b in spec["segments"])

    def work(report):
        from app.engine import safety
        kind = "short" if spec["aspect"] == "9:16" and total <= 180 else "compilation"
        folder = OUTPUT_DIR / ("shorts" if kind == "short" else "compilations") / str(uid)
        out = folder / f"edit_{int(time.time())}_{secrets.token_hex(3)}.mp4"
        report(2, "Rendering…")
        editor.render(Path(doc["path"]), out, spec, info, lambda f: report(5 + f * 85, "Rendering…"))
        report(92, "Checking the video is safe…")
        ok, why = safety.check_final_video(out, title, description)
        if not ok:
            out.unlink(missing_ok=True)
            raise ValueError(f"The finished video did not pass the safety check, so it was not saved ({why}).")
        report(96, "Saving…")
        thumb = out.with_suffix(".jpg")
        import subprocess
        from app.config import FFMPEG_BIN
        subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{total * 0.35:.2f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "3", str(thumb)],
                       check=False, timeout=120)
        credit = doc.get("credit")
        desc = description.strip()
        if not desc and credit:
            desc = f"Original: {credit.get('title') or ''} by {credit.get('creator') or ''}\n{credit.get('video_url') or ''}".strip()
        vid = Video(user_id=str(uid), kind=kind, status="rendered", title=title, description=desc, tags=[], video_path=str(out),
                    thumbnail_path=str(thumb) if thumb.is_file() else "", audio_mode="original", clip_ids=[], game_name="Edited video",
                    credits=[credit] if credit else [], privacy_status="unlisted", upload_status="hold", edited=True, created_at=now()).save()
        tokens.charge_action(uid, "editor_render", ref=str(vid.id))       # only a finished, saved video is charged
        from app.services import notification_service as notes
        notes.notify(uid, "editor", "Your edited video is ready", f"{title} was saved to your Videos and is waiting for your check.", "#/videos", "success")
        return {"video_id": str(vid.id), "kind": kind, "seconds": round(total, 1)}
    return start_task(uid, "render", work, _RENDER)
