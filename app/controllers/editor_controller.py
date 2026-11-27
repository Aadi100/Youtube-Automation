"""Controller (the C of MVC): the video editor."""
from pathlib import Path

from flask import Blueprint

from app.engine import editor
from app.http import register
from app.models import Video, oid
from app.services import edit_project_service as ed_projects
from app.services import editor_service as ed
from app.utils.envfile import read_env


def _src(h, sid):
    doc = ed.get_source(h.uid, sid, h.is_owner())
    if not doc:
        h.send_json(404, {"error": "That video is not in your editor any more. Open it again."})
    return doc


def _safe(fn):
    """Run a service call; its plain-language ValueErrors become a 400 with the message."""
    def wrap(h, *a):
        try:
            return fn(h, *a)
        except ed_projects.Conflict as e:
            h.send_json(409, {"error": "This project was changed somewhere else (another tab or device). Reload it to see the newest version.", "current": e.current})
        except LookupError:
            h.send_json(404, {"error": "That project is not there any more."})
        except ValueError as e:
            h.send_json(400, {"error": str(e)})
        except RuntimeError as e:
            h.send_json(502, {"error": str(e)[:300]})
    wrap.__name__ = fn.__name__
    return wrap


def h_sources(h):
    h.send_json(200, {"sources": ed.list_sources(h.uid), "aspects": list(editor.ASPECTS), "fits": list(editor.FITS), "max_upload_mb": ed.MAX_UPLOAD // 1024 // 1024})


@_safe
def h_upload(h):
    n = int(h.headers.get("Content-Length") or 0)
    h.send_json(200, {"source": ed.save_upload(h.uid, h.q.get("name") or "video.mp4", h.rfile, n)})


@_safe
def h_from_video(h):
    vid = str(h.body_json().get("video_id") or "")
    doc = Video.find_one(id=oid(vid)) if len(vid) == 24 else None
    if not doc or (doc.get("user_id") != h.uid and not h.is_owner()):
        return h.send_json(404, {"error": "video not found"})
    h.send_json(200, {"source": ed.from_video(h.uid, doc)})


@_safe
def h_from_link(h):
    d = h.body_json()
    safety_on = (read_env().get("SAFE_MODE") or "on").strip().lower() not in ("off", "0", "no", "false")
    h.send_json(202, {"task": ed.start_link(h.uid, d.get("url"), d.get("start"), d.get("end"), safety_on)})


def h_task(h, tid):
    t = ed.task_view(h.uid, tid, h.is_owner())
    h.send_json(200 if t else 404, t or {"error": "not found"})


@_safe
def h_twitch_search(h):
    h.send_json(200, {"channels": ed.twitch_search(h.q.get("q"))})


@_safe
def h_twitch_videos(h):
    h.send_json(200, ed.twitch_videos(h.q.get("login") or ""))


def h_source(h, sid):
    doc = _src(h, sid)
    if doc:
        h.send_json(200, ed.view(doc))


def h_video(h, sid):
    doc = _src(h, sid)
    if doc:
        h.send_file(Path(doc["path"]))


def h_strip(h, sid):
    doc = _src(h, sid)
    if doc:
        try:
            h.send_file(ed.filmstrip_for(doc), "image/jpeg")
        except Exception:
            h.send_json(500, {"error": "Could not make the timeline pictures."})


def h_auto(h, sid):
    doc = _src(h, sid)
    if doc:
        h.send_json(202, {"task": ed.auto_edit(h.uid, doc, bool(h.body_json().get("ums")))})


def h_face(h, sid):
    doc = _src(h, sid)
    if doc:
        h.send_json(202, {"task": ed.find_face(h.uid, doc)})


@_safe
def h_ask(h, sid):
    doc = _src(h, sid)
    if not doc:
        return
    d = h.body_json()
    st = d.get("state") if isinstance(d.get("state"), dict) else {}
    segs = editor.normalize([[s[0], s[1]] for s in (st.get("segments") or []) if isinstance(s, (list, tuple)) and len(s) == 2], float(doc["duration"]))
    new, done = editor.ask(str(d.get("text") or "")[:300], {**st, "segments": segs or [[0.0, float(doc["duration"])]]}, float(doc["duration"]))
    h.send_json(200, {"state": {k: new.get(k) for k in ("segments", "aspect", "fit", "captions") if k in new}, "done": done})


@_safe
def h_render(h, sid):
    doc = _src(h, sid)
    if not doc:
        return
    d = h.body_json()
    h.send_json(202, {"task": ed.start_render(h.uid, doc, d.get("spec") or {}, d.get("title") or "", str(d.get("description") or "")[:4000])})


@_safe
def h_delete(h, sid):
    ok = ed.delete_source(h.uid, sid)
    h.send_json(200 if ok else 404, {"ok": ok})


# ---- music for projects: the studio's library, and audio files the member uploaded
def h_audio(h):
    h.send_json(200, {"library": ed.music_library(), "mine": ed.list_audio(h.uid), "max_mb": ed.MAX_AUDIO // 1024 // 1024})


@_safe
def h_audio_upload(h):
    n = int(h.headers.get("Content-Length") or 0)
    h.send_json(200, {"source": ed.save_audio(h.uid, h.q.get("name") or "music.mp3", h.rfile, n)})


def h_audio_file(h):
    p = ed.resolve_music(h.uid, h.q.get("ref") or "")
    if not p:
        return h.send_json(404, {"error": "That track is not available."})
    h.send_file(p)


def h_export_options(h):
    from app.engine import edit_project as ep
    h.send_json(200, {"presets": [{"id": k, **v} for k, v in ep.PRESETS.items()], "quality": [{"id": k, "label": v[2]} for k, v in ep.QUALITY.items()]})


# ---- pictures for stickers and logos (the member's own)
def h_images(h):
    h.send_json(200, {"images": ed.list_images(h.uid), "max_mb": ed.MAX_IMAGE // 1024 // 1024})


@_safe
def h_image_upload(h):
    n = int(h.headers.get("Content-Length") or 0)
    h.send_json(200, {"source": ed.save_image(h.uid, h.q.get("name") or "logo.png", h.rfile, n)})


def h_image_file(h):
    p = ed.resolve_image(h.uid, h.q.get("ref") or "")
    if not p:
        return h.send_json(404, {"error": "That picture is not available."})
    h.send_file(p, "image/png")


# ---- projects: a timeline of several clips (every one belongs to the member who made it)
def h_projects(h):
    h.send_json(200, ed_projects.list_projects(h.uid))


@_safe
def h_project_new(h):
    d = h.body_json()
    h.send_json(200, ed_projects.create(h.uid, d.get("title") or "", str(d.get("source") or "")))


@_safe
def h_project(h, pid):
    p = ed_projects.get(h.uid, pid)
    h.send_json(200 if p else 404, p or {"error": "That project is not there any more."})


@_safe
def h_project_save(h, pid):
    d = h.body_json()
    try:
        version = int(d.get("version"))
    except (TypeError, ValueError):
        raise ValueError("The project version is missing. Reload the page.")
    h.send_json(200, ed_projects.save(h.uid, pid, version, d.get("title"), d.get("data")))


@_safe
def h_project_rename(h, pid):
    h.send_json(200, ed_projects.rename_only(h.uid, pid, str(h.body_json().get("title") or "")))


@_safe
def h_project_copy(h, pid):
    h.send_json(200, ed_projects.duplicate(h.uid, pid))


@_safe
def h_project_delete(h, pid):
    ok = ed_projects.delete(h.uid, pid)
    h.send_json(200 if ok else 404, {"ok": ok})


@_safe
def h_project_render(h, pid):
    d = h.body_json()
    h.send_json(202, {"render": ed_projects.enqueue(h.uid, pid, d.get("title") or "", d.get("description") or "")})


def h_render_status(h, rid):
    r = ed_projects.get_render(h.uid, rid)
    h.send_json(200 if r else 404, r or {"error": "not found"})


def h_render_cancel(h, rid):
    r = ed_projects.cancel(h.uid, rid)
    h.send_json(200 if r else 404, r or {"error": "not found"})


ROUTES = [
    (r"/api/editor/audio", "GET", h_audio),
    (r"/api/editor/audio/upload", "POST", h_audio_upload),
    (r"/api/editor/audio/file", "GET", h_audio_file),
    (r"/api/editor/export-options", "GET", h_export_options),
    (r"/api/editor/images", "GET", h_images),
    (r"/api/editor/images/upload", "POST", h_image_upload),
    (r"/api/editor/images/file", "GET", h_image_file),
    (r"/api/editor/projects", "GET", h_projects),
    (r"/api/editor/projects", "POST", h_project_new),
    (r"/api/editor/projects/([0-9a-f]{24})", "GET", h_project),
    (r"/api/editor/projects/([0-9a-f]{24})", "PUT", h_project_save),
    (r"/api/editor/projects/([0-9a-f]{24})/title", "PUT", h_project_rename),
    (r"/api/editor/projects/([0-9a-f]{24})", "DELETE", h_project_delete),
    (r"/api/editor/projects/([0-9a-f]{24})/copy", "POST", h_project_copy),
    (r"/api/editor/projects/([0-9a-f]{24})/render", "POST", h_project_render),
    (r"/api/editor/renders/([0-9a-f]{24})", "GET", h_render_status),
    (r"/api/editor/renders/([0-9a-f]{24})/cancel", "POST", h_render_cancel),
    (r"/api/editor/sources", "GET", h_sources),
    (r"/api/editor/sources/upload", "POST", h_upload),
    (r"/api/editor/from-video", "POST", h_from_video),
    (r"/api/editor/from-link", "POST", h_from_link),
    (r"/api/editor/tasks/([0-9a-f]{16})", "GET", h_task),
    (r"/api/editor/twitch/search", "GET", h_twitch_search),
    (r"/api/editor/twitch/videos", "GET", h_twitch_videos),
    (r"/api/editor/sources/([0-9a-f]{24})", "GET", h_source),
    (r"/api/editor/sources/([0-9a-f]{24})", "DELETE", h_delete),
    (r"/api/editor/sources/([0-9a-f]{24})/video", "GET", h_video),
    (r"/api/editor/sources/([0-9a-f]{24})/strip", "GET", h_strip),
    (r"/api/editor/sources/([0-9a-f]{24})/auto", "POST", h_auto),
    (r"/api/editor/sources/([0-9a-f]{24})/face", "POST", h_face),
    (r"/api/editor/sources/([0-9a-f]{24})/ask", "POST", h_ask),
    (r"/api/editor/sources/([0-9a-f]{24})/render", "POST", h_render),
]
bp = Blueprint("editor", __name__)
register(bp, ROUTES)
