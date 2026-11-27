"""Editor projects: save them, and render them through a queue that every member shares.

Built for many members at the same time:
  * every project and every render belongs to ONE member; nobody can read, change, delete or render another member's project (the owner included);
  * saving uses a version number, so two open tabs never overwrite each other unnoticed (the second save is refused with the newest version);
  * a render is a row in the database (not memory in one web process), so any web worker can show its progress and a restart does not lose the queue;
  * renders run in the WORKER service, oldest first, a limited number at a time; one member may have only one waiting or running render; the queue has a size limit;
  * every temporary file is named after its own render, so two members rendering at once never touch each other's files;
  * the sources a project uses are never cleaned away while the project exists, and a member's editor storage has a limit.
"""
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.config import FFMPEG_BIN, OUTPUT_DIR, TEMP_DIR
from app.engine import edit_project as ep
from app.engine import risk
from app.models import EditProject, EditRender, EditSource, Video, now, oid
from app.runtime import WORKER_ID

MAX_PROJECTS = 25               # per member
MAX_QUEUE = 40                  # renders waiting in the whole studio; beyond this a member is asked to try again soon
STALE_SECONDS = 600             # a running render that has not reported for this long is given up on (its worker stopped)
ACTIVE = ("queued", "running")


class Conflict(Exception):
    """The project was saved somewhere else since this copy was opened."""
    def __init__(self, current: Dict):
        super().__init__("conflict")
        self.current = current


class Cancelled(Exception):
    pass


def _threads() -> int:
    try:
        return max(1, int(os.environ.get("EDITOR_THREADS") or 2))
    except ValueError:
        return 2


def _renderers() -> int:
    try:
        return max(1, int(os.environ.get("EDITOR_RENDERERS") or 1))
    except ValueError:
        return 1


# ---------------------------------------------------------------- sources of a member
def _source_infos(uid, ids) -> Dict[str, Dict]:
    """The member's own sources among `ids`. A source that belongs to somebody else is simply not found."""
    out = {}
    for sid in {str(i) for i in ids}:
        try:
            d = EditSource.find_one(id=oid(sid))
        except Exception:
            continue
        if d and d.get("user_id") == str(uid) and d.get("origin") not in ("audio", "image"):     # only videos can be clips
            out[sid] = {"duration": float(d.get("duration") or 0), "width": int(d.get("width") or 0), "height": int(d.get("height") or 0),
                        "has_audio": bool(d.get("has_audio", True)), "path": d.get("path") or "", "title": d.get("title") or "Video", "credit": d.get("credit")}
    return out


def _source_ids(clips) -> list:
    """Every video of the member that these clips need: the clips' own and their reaction (picture-in-picture) videos."""
    out = []
    for c in clips or []:
        if not isinstance(c, dict):
            continue
        out.append(c.get("source"))
        if isinstance(c.get("pip"), dict):
            out.append(c["pip"].get("source"))
    return [x for x in out if x]


def in_use(uid) -> set:
    """Ids of the sources any of this member's projects use: they are not cleaned away or deleted while a project needs them."""
    used = set()
    for p in EditProject.find_all(user_id=str(uid)):
        for c in ((p.get("data") or {}).get("clips") or []):
            used.add(str(c.get("source")))
            if isinstance(c.get("pip"), dict):
                used.add(str(c["pip"].get("source")))
        ref = (((p.get("data") or {}).get("audio") or {}).get("music") or {}).get("ref") or ""
        if ref.startswith("src:"):
            used.add(ref[4:])                    # an audio file that a project uses is kept too
        for c in ((p.get("data") or {}).get("clips") or []):
            for o in c.get("overlays") or []:
                if str(o.get("ref") or "").startswith("img:"):
                    used.add(str(o["ref"])[4:])  # and so is every sticker picture
    return used


# ---------------------------------------------------------------- projects
def _own(uid, pid: str) -> Optional[Dict]:
    try:
        d = EditProject.find_one(id=oid(pid))
    except Exception:
        return None
    return d if d and d.get("user_id") == str(uid) else None


def _latest_render(uid, pid: str) -> Optional[Dict]:
    r = EditRender.find_all(user_id=str(uid), project_id=str(pid), order=("-created_at",), limit=1)
    return render_view(r[0]) if r else None


def view(doc: Dict, full: bool = True) -> Dict:
    data = doc.get("data") or ep.empty()
    out = {"id": str(doc["_id"]), "title": doc.get("title") or "My project", "version": int(doc.get("version") or 1), "clips": len(data.get("clips") or []),
           "seconds": ep.total_seconds(data), "aspect": data.get("aspect", "9:16"), "updated_at": doc["updated_at"].isoformat() if doc.get("updated_at") else None}
    if full:
        out["data"] = data
        out["render"] = _latest_render(doc["user_id"], str(doc["_id"]))
    return out


def list_projects(uid) -> Dict:
    docs = EditProject.find_all(user_id=str(uid), order=("-updated_at",), limit=MAX_PROJECTS + 5)
    return {"projects": [view(d, full=False) for d in docs], "max": MAX_PROJECTS}


def create(uid, title: str, source_id: str = "") -> Dict:
    if EditProject.total(user_id=str(uid)) >= MAX_PROJECTS:
        raise ValueError(f"You can have up to {MAX_PROJECTS} projects. Delete an old one first.")
    data = ep.empty()
    if source_id:
        info = _source_infos(uid, [source_id]).get(str(source_id))
        if not info:
            raise ValueError("That video is not in your editor any more.")
        data = ep.clean({"aspect": "9:16", "clips": [{"source": str(source_id), "start": 0, "end": info["duration"]}]}, {str(source_id): info})
    t = " ".join((title or "").split())[:100] or "My project"
    doc = EditProject(user_id=str(uid), title=t, version=1, created_at=now(), updated_at=now(), data=data).save()
    return view(EditProject.find_one(id=doc.id))


def get(uid, pid: str) -> Optional[Dict]:
    d = _own(uid, pid)
    return view(d) if d else None


def save(uid, pid: str, version: int, title, data) -> Dict:
    d = _own(uid, pid)
    if not d:
        raise LookupError("project not found")
    if len(json.dumps(data, default=str)) > ep.MAX_DATA_BYTES:
        raise ValueError("This project is too big to save. Remove some clips or text.")
    infos = _source_infos(uid, _source_ids(data.get("clips")) if isinstance(data, dict) else [])
    from app.services import editor_service as editor_sources
    clean = ep.clean(data, infos, lambda ref: editor_sources.resolve_music(uid, ref) is not None, lambda ref: editor_sources.resolve_image(uid, ref) is not None)
    t = " ".join(str(title if title is not None else d.get("title") or "").split())[:100] or "My project"
    n = EditProject.objects(id=d["_id"], user_id=str(uid), version=int(version)).update_one(set__title=t, set__data=clean, set__updated_at=now(), inc__version=1)
    if not n:
        raise Conflict(view(_own(uid, pid), full=False))
    return view(_own(uid, pid))


def rename_only(uid, pid: str, title: str) -> Dict:
    d = _own(uid, pid)
    if not d:
        raise LookupError("project not found")
    EditProject.objects(id=d["_id"]).update_one(set__title=" ".join(title.split())[:100] or "My project", set__updated_at=now())
    return view(_own(uid, pid))


def duplicate(uid, pid: str) -> Dict:
    d = _own(uid, pid)
    if not d:
        raise LookupError("project not found")
    if EditProject.total(user_id=str(uid)) >= MAX_PROJECTS:
        raise ValueError(f"You can have up to {MAX_PROJECTS} projects. Delete an old one first.")
    doc = EditProject(user_id=str(uid), title=((d.get("title") or "Project") + " copy")[:100], version=1, created_at=now(), updated_at=now(), data=d.get("data") or ep.empty()).save()
    return view(EditProject.find_one(id=doc.id))


def delete(uid, pid: str) -> bool:
    d = _own(uid, pid)
    if not d:
        return False
    if EditRender.total(user_id=str(uid), project_id=str(pid), status__in=list(ACTIVE)):
        raise ValueError("This project is being rendered. Cancel the render first.")
    EditRender.objects(user_id=str(uid), project_id=str(pid)).delete()
    EditProject.objects(id=d["_id"]).delete()
    return True


# ---------------------------------------------------------------- the render queue
def render_view(doc: Dict) -> Dict:
    ahead = 0
    if doc.get("status") == "queued":
        ahead = EditRender.total(status="queued", created_at__lt=doc["created_at"]) + EditRender.total(status="running")
    return {"id": str(doc["_id"]), "project_id": doc.get("project_id"), "status": doc.get("status"), "pct": int(doc.get("pct") or 0), "message": doc.get("message") or "",
            "ahead": ahead, "result": doc.get("result"), "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None}


def enqueue(uid, pid: str, title: str = "", description: str = "") -> Dict:
    d = _own(uid, pid)
    if not d:
        raise LookupError("project not found")
    data = d.get("data") or ep.empty()
    if not data.get("clips"):
        raise ValueError("Add at least one clip to the timeline first.")
    ep.check_export(data)
    if EditRender.total(user_id=str(uid), status__in=list(ACTIVE)):
        raise ValueError("You already have a video waiting or rendering. Wait for it to finish, or cancel it.")
    if EditRender.total(status="queued") >= MAX_QUEUE:
        raise ValueError("The editor is very busy right now. Try again in a few minutes.")
    infos = _source_infos(uid, _source_ids(data["clips"]))
    for c in data["clips"]:
        s = infos.get(c["source"])
        if (c.get("pip") and (infos.get(c["pip"]["source"]) is None or not Path(infos[c["pip"]["source"]]["path"]).is_file())):
            raise ValueError("A reaction video used in this project is missing on the server. Remove the picture-in-picture or add the video again.")
        if not s or not Path(s["path"]).is_file():
            raise ValueError("A video used in this project is missing on the server. Remove that clip or add the video again.")
    music = (data.get("audio") or {}).get("music")
    from app.services import editor_service as editor_sources
    if music and not editor_sources.resolve_music(uid, music["ref"]):
        raise ValueError("The music track of this project is not available any more. Choose another one or remove the music.")
    for c in data["clips"]:
        for o in c.get("overlays") or []:
            if not editor_sources.resolve_image(uid, o["ref"]):
                raise ValueError("A sticker or logo picture used in this project is not available any more. Remove it from the clip or upload it again.")
    from app.services import token_service as tokens
    why = tokens.small_shortfall(uid, "editor_render")
    if why:
        raise ValueError(why)
    t = " ".join((title or d.get("title") or "My edit").split())[:100]
    r = EditRender(user_id=str(uid), project_id=str(pid), status="queued", pct=0, message="Waiting in line…", created_at=now(), title=t,
                   description=str(description or "")[:4000], data=data, heartbeat=time.time()).save()
    return render_view(EditRender.find_one(id=r.id))


def get_render(uid, rid: str) -> Optional[Dict]:
    try:
        d = EditRender.find_one(id=oid(rid))
    except Exception:
        return None
    return render_view(d) if d and d.get("user_id") == str(uid) else None


def cancel(uid, rid: str) -> Optional[Dict]:
    try:
        d = EditRender.find_one(id=oid(rid))
    except Exception:
        return None
    if not d or d.get("user_id") != str(uid):
        return None
    if EditRender.objects(id=d["_id"], status="queued").update_one(set__status="cancelled", set__message="Cancelled"):
        return render_view(EditRender.find_one(id=d["_id"]))
    EditRender.objects(id=d["_id"], status="running").update_one(set__cancel=True, set__message="Stopping…")
    return render_view(EditRender.find_one(id=d["_id"]))


# ---------------------------------------------------------------- the worker
def claim() -> Optional[Dict]:
    """Take the oldest waiting render (one worker only: the change is atomic)."""
    for cand in EditRender.objects(status="queued").order_by("created_at").limit(5):
        got = EditRender.objects(id=cand.id, status="queued").modify(new=True, set__status="running", set__worker=WORKER_ID, set__started_at=now(), set__heartbeat=time.time(), set__message="Starting…")
        if got:
            return EditRender.find_one(id=cand.id)
    return None


def recover_stale(mine_only: bool = False) -> int:
    """Renders left 'running' by a worker that stopped are marked failed (nothing was charged), so the member can press Make video again."""
    q = {"status": "running"}
    if mine_only:
        q["worker"] = WORKER_ID
    else:
        q["heartbeat__lt"] = time.time() - STALE_SECONDS
    return EditRender.objects(**q).update(set__status="error", set__message="The server was restarted while this was rendering. Nothing was charged. Press Make video again.")


def run_render(doc: Dict) -> None:
    rid, uid, pid = str(doc["_id"]), str(doc["user_id"]), str(doc["project_id"])
    last = {"t": 0.0, "m": ""}

    def report(pct: float, msg: str = "") -> None:
        """Save the progress (at most once a second, sooner when the message changes) and stop if the member cancelled."""
        if time.time() - last["t"] < 1.0 and (not msg or msg == last["m"]):
            return
        last["t"], last["m"] = time.time(), msg or last["m"]
        cur = EditRender.objects(id=doc["_id"]).modify(new=True, set__pct=int(max(0, min(99, pct))), set__heartbeat=time.time(), **({"set__message": msg} if msg else {}))
        if cur is None or cur.status != "running" or getattr(cur, "cancel", False):
            raise Cancelled()

    work = TEMP_DIR / "editor" / rid
    out = None
    try:
        data = doc.get("data") or ep.empty()
        infos = _source_infos(uid, _source_ids(data["clips"]))
        for c in data["clips"]:
            if c["source"] not in infos or not Path(infos[c["source"]]["path"]).is_file():
                raise ValueError("A video used in this project is missing on the server.")
        total = ep.total_seconds(data)
        kind = "short" if data["aspect"] == "9:16" and total <= 180 else "compilation"
        out = OUTPUT_DIR / ("shorts" if kind == "short" else "compilations") / uid / f"edit_{int(time.time())}_{secrets.token_hex(3)}.mp4"
        report(2, "Rendering…")
        music = (data.get("audio") or {}).get("music")
        music_path = None
        if music:
            from app.services import editor_service as editor_sources
            music_path = editor_sources.resolve_music(uid, music["ref"])
            if not music_path:
                raise ValueError("The music track of this project is not available any more.")
        from app.services import editor_service as editor_pics
        images = {}
        for c in data["clips"]:
            for o in c.get("overlays") or []:
                p_ = editor_pics.resolve_image(uid, o["ref"])
                if not p_:
                    raise ValueError("A sticker or logo picture used in this project is not available any more.")
                images[o["ref"]] = p_
        ep.render(data, infos, out, work, f"r{rid}", report, threads=_threads(), music_path=music_path, images=images)
        report(93, "Checking the video is safe…")
        title, description = doc.get("title") or "My edit", doc.get("description") or ""
        from app.engine import safety
        ok, why = safety.check_final_video(out, title, description)
        if not ok:
            out.unlink(missing_ok=True)
            raise ValueError(f"The finished video did not pass the safety check, so it was not saved ({why}).")
        report(97, "Saving…")
        thumb = out.with_suffix(".jpg")
        subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{total * 0.35:.2f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "3", str(thumb)],
                       check=False, timeout=120)
        credits, seen = [], set()
        for c in data["clips"]:
            cr = infos[c["source"]].get("credit")
            if cr and (cr.get("creator"), cr.get("video_url")) not in seen:
                seen.add((cr.get("creator"), cr.get("video_url")))
                credits.append(cr)
        desc = description.strip()
        if not desc and credits:
            desc = "\n".join(f"Original: {x.get('title') or ''} by {x.get('creator') or ''}\n{x.get('video_url') or ''}".strip() for x in credits[:5])
        vid = Video(user_id=uid, kind=kind, status="rendered", title=title, description=desc, tags=[], video_path=str(out), thumbnail_path=str(thumb) if thumb.is_file() else "",
                    audio_mode="original", clip_ids=[], game_name="Edited video", credits=credits, privacy_status="unlisted", upload_status="hold", edited=True, created_at=now(),
                    export_preset=ep.export_of(data)["preset"], export_quality=ep.export_of(data)["quality"], edit_summary=risk.edit_summary(data),
                    synthetic=bool((data.get("story") or {}).get("synthetic")), realistic=bool((data.get("story") or {}).get("realistic"))).save()
        from app.services import notification_service as notes
        from app.services import token_service as tokens
        tokens.charge_action(uid, "editor_render", ref=str(vid.id))        # only a finished, saved video is charged
        notes.notify(uid, "editor", "Your edited video is ready", f"{title} was saved to your Videos and is waiting for your check.", "#/videos", "success")
        EditRender.objects(id=doc["_id"]).update_one(set__status="done", set__pct=100, set__message="Done", set__result={"video_id": str(vid.id), "kind": kind, "seconds": total, "preset": ep.export_of(data)["preset"], "quality": ep.export_of(data)["quality"]})
    except Cancelled:
        if out:
            out.unlink(missing_ok=True)
        EditRender.objects(id=doc["_id"]).update_one(set__status="cancelled", set__message="Cancelled")
    except (ValueError, RuntimeError) as e:
        EditRender.objects(id=doc["_id"]).update_one(set__status="error", set__message=str(e)[:300])
    except Exception as e:
        print(f"[studio] editor render {rid} failed: {type(e).__name__}: {str(e)[:200]}")
        EditRender.objects(id=doc["_id"]).update_one(set__status="error", set__message=f"The video could not be made ({type(e).__name__}). Nothing was charged.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def worker_loop() -> None:
    """One render at a time per thread, oldest first. Runs in the worker service; the web service only queues and shows progress."""
    idle = 0.0
    while True:
        try:
            doc = claim()
            if doc:
                run_render(doc)
                continue
            if time.time() - idle > 60:
                idle = time.time()
                recover_stale()
        except Exception as e:
            print(f"[studio] editor queue error: {type(e).__name__}: {str(e)[:150]}")
            time.sleep(5)
        time.sleep(2)


def start_workers() -> None:
    recover_stale(mine_only=True)
    for _ in range(_renderers()):
        threading.Thread(target=worker_loop, daemon=True).start()
