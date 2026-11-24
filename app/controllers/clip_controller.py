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


def _audience_payload(h) -> dict:
    from app.engine import audience
    dflt = {"countries": "all", "languages": "all"} if h.is_owner() else audience.server_default()
    return {"mine": audience.get(h.uid), "default": dflt, "catalog": audience.catalog(), "owner": h.is_owner()}


def h_audience(h):
    """Which creators' clips THIS person wants: the countries they live in and the language of the streams (every account sets its own)."""
    h.send_json(200, _audience_payload(h))


def h_audience_put(h):
    from app.engine import audience
    try:
        audience.save(h.uid, h.body_json())
    except ValueError as e:
        return h.send_json(400, {"error": str(e)})
    h.send_json(200, _audience_payload(h))


def h_clips(h):
    docs = Clip.find_all(user_id=h.uid, order=("-created_at",), limit=300)
    h.send_json(200, [clean(x) | {"file_exists": Path(x.get("path") or "").is_file()} for x in docs])


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
    (r"/api/audience", "GET", h_audience),
    (r"/api/audience", "PUT", h_audience_put),
    (r"/api/clips", "GET", h_clips),
    (r"/api/clips/([\w-]+)", "DELETE", h_clip_delete),
]
bp = Blueprint("clip", __name__)
register(bp, ROUTES)
