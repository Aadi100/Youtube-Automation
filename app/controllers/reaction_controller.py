"""Controller (the C of MVC): the Reaction Lab (beta). Owner only, separate from everything else: it never starts a video job, uploads or spends AI tokens."""
from flask import Blueprint

from app.engine import reaction_model as rm
from app.http import OWNER_ONLY, register
from app.services import reaction_service as rx


def _safe(fn):
    def wrap(h, *a):
        try:
            return fn(h, *a)
        except ValueError as e:
            h.send_json(400, {"error": str(e)})
    wrap.__name__ = fn.__name__
    return wrap


def _scan(h, sid):
    d = rx.get_scan(h.uid, sid)
    if not d:
        h.send_json(404, {"error": "That scan is not available any more. Start a new one."})
    return d


def h_options(h):
    h.send_json(200, {"signals": [{"id": s, "label": rm.LABEL[s], "help": rm.HELP[s], "prior": rm.PRIOR[s]} for s in rm.SIGNALS], "categories": rm.CATEGORIES, "moments": list(rx.MOMENTS),
                      "model": rx.model_status(h.uid)})


@_safe
def h_scan(h):
    d = h.body_json()
    h.send_json(202, {"scan": rx.start_scan(h.uid, d.get("url"), str(d.get("category") or "any"), int(d.get("moments") or 12), bool(d.get("faces", True)), bool(d.get("words", False)),
                                            d.get("start"), d.get("end"))})


def h_scans(h):
    h.send_json(200, {"scans": rx.list_scans(h.uid)})


def h_scan_get(h, sid):
    d = _scan(h, sid)
    if d:
        h.send_json(200, rx.view(d))


def h_scan_delete(h, sid):
    ok = rx.delete_scan(h.uid, sid)
    h.send_json(200 if ok else 404, {"ok": ok})


@_safe
def h_rescore(h, sid):
    if _scan(h, sid):
        h.send_json(200, rx.rescore(h.uid, sid))


@_safe
def h_label(h, sid, cid):
    if not _scan(h, sid):
        return
    d = h.body_json()
    y = d.get("y")
    h.send_json(200, {"model": rx.judge(h.uid, sid, cid, None if y is None else int(bool(y)), str(d.get("category") or ""))})


def h_model(h):
    h.send_json(200, rx.model_status(h.uid))


def h_model_reset(h):
    h.send_json(200, {"reset": rx.reset_model(h.uid), "model": rx.model_status(h.uid)})


def _file(h, sid, cid, what):
    if not _scan(h, sid):
        return
    p = rx.file_of(h.uid, sid, cid, what)
    if not p:
        return h.send_json(404, {"error": "not ready"})
    h.send_file(p)


def h_video(h, sid, cid):
    _file(h, sid, cid, "video")


def h_thumb(h, sid, cid):
    _file(h, sid, cid, "thumb")


ROUTES = [
    (r"/api/reactions/options", "GET", h_options),
    (r"/api/reactions/scan", "POST", h_scan),
    (r"/api/reactions/scans", "GET", h_scans),
    (r"/api/reactions/scans/([0-9a-f]{24})", "GET", h_scan_get),
    (r"/api/reactions/scans/([0-9a-f]{24})", "DELETE", h_scan_delete),
    (r"/api/reactions/scans/([0-9a-f]{24})/rescore", "POST", h_rescore),
    (r"/api/reactions/scans/([0-9a-f]{24})/c/(c\d{1,3})/label", "POST", h_label),
    (r"/api/reactions/scans/([0-9a-f]{24})/c/(c\d{1,3})/video", "GET", h_video),
    (r"/api/reactions/scans/([0-9a-f]{24})/c/(c\d{1,3})/thumb", "GET", h_thumb),
    (r"/api/reactions/model", "GET", h_model),
    (r"/api/reactions/model", "DELETE", h_model_reset),
]
OWNER_ONLY.update({h_options, h_scan, h_scans, h_scan_get, h_scan_delete, h_rescore, h_label, h_model, h_model_reset, h_video, h_thumb})
bp = Blueprint("reactions", __name__)
register(bp, ROUTES)
