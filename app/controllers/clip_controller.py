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


def _sources_payload(h) -> dict:
    from app.engine import clipcfg
    from app.utils.envfile import read_env
    env = read_env()
    keys = bool(env.get("TWITCH_CLIENT_ID") and env.get("TWITCH_CLIENT_SECRET"))
    return {"mine": clipcfg.sources(h.uid), "owner": h.is_owner(), "twitch_keys": keys if h.is_owner() else True,
            "choices": [
                {"id": "youtube", "name": "YouTube", "works": True, "note": "Videos, highlights and live streams. Needs no key."},
                {"id": "twitch", "name": "Twitch", "works": True, "note": "Clips and live streams."},
                {"id": "kick", "name": "Kick", "works": False,
                 "note": "Kick has no way to search clips by game, so the studio cannot look there by itself yet. You can still paste a Kick link in the Clip Finder or the Editor."}]}


def _trending_payload(h) -> dict:
    from app.engine import clipcfg
    from app.services import diy_service, token_service
    p = token_service.pricing()
    return {"on": clipcfg.trending_on(h.uid), "allowed": diy_service.trending_allowed(h.is_owner()), "price": {"short": p["trend_short"], "compilation": p["trend_compilation"]}}


def h_trending(h):
    from app.engine import clipcfg
    h.send_json(200, _trending_payload(h))


def h_trending_put(h):
    from app.engine import clipcfg
    from app.services import diy_service
    on = bool(h.body_json().get("on"))
    if on and not diy_service.trending_allowed(h.is_owner()):
        return h.send_json(403, {"error": "Trending mode is not switched on for you. Ask the owner."})
    clipcfg.save_trending(h.uid, on)
    h.send_json(200, _trending_payload(h))


def h_ai_saver(h):
    from app.engine import clipcfg
    h.send_json(200, {"on": clipcfg.ai_saver_on(h.uid)})


def h_ai_saver_put(h):
    from app.engine import clipcfg
    h.send_json(200, {"on": clipcfg.save_ai_saver(h.uid, bool(h.body_json().get("on")))})


def h_sources(h):
    """Where THIS person's videos look for clips: YouTube and / or Twitch (every account sets its own)."""
    h.send_json(200, _sources_payload(h))


def h_sources_put(h):
    from app.engine import clipcfg
    try:
        clipcfg.save_sources(h.uid, h.body_json().get("sources"))
    except ValueError as e:
        return h.send_json(400, {"error": str(e)})
    h.send_json(200, _sources_payload(h))


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
    (r"/api/trending", "GET", h_trending),
    (r"/api/trending", "PUT", h_trending_put),
    (r"/api/ai-saver", "GET", h_ai_saver),
    (r"/api/ai-saver", "PUT", h_ai_saver_put),
    (r"/api/sources", "GET", h_sources),
    (r"/api/sources", "PUT", h_sources_put),
    (r"/api/clips", "GET", h_clips),
    (r"/api/clips/([\w-]+)", "DELETE", h_clip_delete),
]
bp = Blueprint("clip", __name__)
register(bp, ROUTES)
