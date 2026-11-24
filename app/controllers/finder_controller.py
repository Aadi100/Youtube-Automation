"""Controller (the C of MVC): the clip finder (scan a source, show the moments found, process the ones the member picks)."""
from flask import Blueprint

from app.http import register
from app.services import diy_service
from app.services import finder_service as fs
from app.utils.envfile import read_env


def _safety_on() -> bool:
    return (read_env().get("SAFE_MODE") or "on").strip().lower() not in ("off", "0", "no", "false")


def _allowed(h) -> bool:
    """Choosing your own source is an owner switch for members ('Members may pick their own clip')."""
    if h.is_owner() or diy_service.flags()["own_source"]:
        return True
    h.send_json(403, {"error": "The owner has switched off: choosing your own clips."})
    return False


def _safe(fn):
    def wrap(h, *a):
        try:
            return fn(h, *a)
        except ValueError as e:
            h.send_json(400, {"error": str(e)})
    wrap.__name__ = fn.__name__
    return wrap


def _scan(h, sid):
    d = fs.get_scan(h.uid, sid, h.is_owner())
    if not d:
        h.send_json(404, {"error": "That scan is not available any more. Start a new one."})
    return d


@_safe
def h_scan(h):
    if not _allowed(h):
        return
    d = h.body_json()
    h.send_json(202, {"scan": fs.start_scan(h.uid, d.get("url"), d.get("start"), d.get("end"), _safety_on())})


def h_scans(h):
    h.send_json(200, {"scans": fs.list_scans(h.uid)})


def h_scan_get(h, sid):
    d = _scan(h, sid)
    if d:
        h.send_json(200, fs.view(d))


@_safe
def h_more(h, sid):
    if _allowed(h) and _scan(h, sid):
        h.send_json(202, {"scan": fs.scan_more(h.uid, sid, _safety_on())})


def h_delete(h, sid):
    ok = fs.delete_scan(h.uid, sid)
    h.send_json(200 if ok else 404, {"ok": ok})


def _file(h, sid, cid, what):
    d = _scan(h, sid)
    if not d:
        return
    p = fs.file_of(d["user_id"], sid, cid, what)
    if not p:
        return h.send_json(404, {"error": "not ready"})
    h.send_file(p)


def h_video(h, sid, cid):
    _file(h, sid, cid, "video")


def h_thumb(h, sid, cid):
    _file(h, sid, cid, "thumb")


@_safe
def h_pick(h, sid):
    if not (_allowed(h) and _scan(h, sid)):
        return
    d = h.body_json()
    ids = [str(i) for i in (d.get("ids") or []) if isinstance(i, str)][:6]
    action = d.get("action")
    if action == "editor":
        tasks = fs.pick_editor(h.uid, sid, ids)
    elif action == "short":
        tasks = fs.pick_short(h.uid, sid, ids, str(d.get("audio_mode") or "default"), str(d.get("after") or ""))
    else:
        raise ValueError("Choose what to do with the clips.")
    h.send_json(202, {"tasks": tasks})


ROUTES = [
    (r"/api/finder/scan", "POST", h_scan),
    (r"/api/finder/scans", "GET", h_scans),
    (r"/api/finder/scans/([0-9a-f]{24})", "GET", h_scan_get),
    (r"/api/finder/scans/([0-9a-f]{24})", "DELETE", h_delete),
    (r"/api/finder/scans/([0-9a-f]{24})/more", "POST", h_more),
    (r"/api/finder/scans/([0-9a-f]{24})/pick", "POST", h_pick),
    (r"/api/finder/scans/([0-9a-f]{24})/c/(c\d{1,3})/video", "GET", h_video),
    (r"/api/finder/scans/([0-9a-f]{24})/c/(c\d{1,3})/thumb", "GET", h_thumb),
]
bp = Blueprint("finder", __name__)
register(bp, ROUTES)
