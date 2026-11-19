"""Controller (the C of MVC): clip endpoints."""
from pathlib import Path

from flask import Blueprint

from app.config import BASE_DIR
from app.http import register
from app.models import Clip, clean
from app.views.serializers import _clipping_payload


def h_clipping(h):
    h.send_json(200, _clipping_payload(h.uid))


def h_clipping_put(h):
    from app.engine import clipcfg
    try:
        clipcfg.save(h.body_json(), h.uid)
    except (TypeError, ValueError) as e:
        return h.send_json(400, {"error": f"Check the numbers: {e}"})
    h.send_json(200, _clipping_payload(h.uid))


def h_clips(h):
    docs = Clip.find_all(user_id=h.uid, order=("-created_at",), limit=300)
    h.send_json(200, [clean(x) | {"file_exists": Path(x.get("path", "")).is_file()} for x in docs])


def h_clip_delete(h, cid):
    doc = Clip.find_one(id=cid, user_id=h.uid)
    if not doc:
        return h.send_json(404, {"error": "not found"})
    if h.q.get("file") == "1":
        p = Path(doc.get("path") or "")
        try:
            p.resolve().relative_to((BASE_DIR / "inputs").resolve())
            if p.is_file():
                p.unlink()
        except ValueError:
            pass
    Clip.remove_where(id=cid)
    h.send_json(200, {"ok": True})


ROUTES = [
    (r"/api/clipping", "GET", h_clipping),
    (r"/api/clipping", "PUT", h_clipping_put),
    (r"/api/clips", "GET", h_clips),
    (r"/api/clips/([\w-]+)", "DELETE", h_clip_delete),
]
bp = Blueprint("clip", __name__)
register(bp, ROUTES)
