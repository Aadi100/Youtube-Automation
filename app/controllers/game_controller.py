"""Controller (the C of MVC): game endpoints."""
import re

from flask import Blueprint

from app.http import register
from app.models import Clip, Game, Video


def _game_fields(d: dict, partial: bool = False) -> dict:
    """Validate/clean a game form. Raises ValueError with a message the dashboard can show."""
    out = {}
    if not partial:  # new game: blank fields mean "fill in automatically"
        d = {k: v for k, v in d.items() if v not in ("", None, [])}
    if "name" in d or not partial:
        name = str(d.get("name", "")).strip()
        if not 1 <= len(name) <= 60:
            raise ValueError("Game name is required (max 60 characters).")
        out["name"] = name
    if "twitch_category" in d:
        out["twitch_category"] = "\n".join(l.strip() for l in str(d["twitch_category"]).splitlines() if l.strip())[:400]
    if "youtube_query" in d:
        out["youtube_query"] = "\n".join(l.strip() for l in str(d["youtube_query"]).splitlines() if l.strip())[:800]
    if "hashtags" in d:
        raw = d["hashtags"] if isinstance(d["hashtags"], list) else re.split(r"[,\s]+", str(d["hashtags"]))
        out["hashtags"] = [t for t in (re.sub(r"[^A-Za-z0-9_]", "", str(x)) for x in raw) if t][:10]
    if "thumb_label" in d:
        out["thumb_label"] = str(d["thumb_label"]).strip()[:20]
    if "enabled" in d:
        out["enabled"] = bool(d["enabled"])
    if not partial:  # sensible defaults for a new game
        out.setdefault("twitch_category", out["name"])
        out.setdefault("youtube_query", f"{out['name']} gameplay highlights")
        out.setdefault("hashtags", [re.sub(r"[^A-Za-z0-9]", "", out["name"])] if re.sub(r"[^A-Za-z0-9]", "", out["name"]) else [])
        out.setdefault("thumb_label", out["name"].upper()[:20])
        out.setdefault("enabled", True)
    return out


def h_games(h):
    games = Game.list_for(h.uid)
    for g in games:
        g["videos"] = Video.total(game_id=g["id"], user_id=h.uid)
        g["clips"] = Clip.total(game_id=g["id"], user_id=h.uid)
    h.send_json(200, games)


def h_game_create(h):
    if Game.total(user_id=h.uid) >= (200 if h.is_owner() else 12):
        raise ValueError("You have reached the limit for games.")
    h.send_json(201, Game.create_for(_game_fields(h.body_json()), h.uid))


def h_game_patch(h, gid):
    g = Game.update_for(gid, _game_fields(h.body_json(), partial=True) or {"enabled": True}, h.uid)
    h.send_json(200 if g else 404, g or {"error": "not found"})


def h_game_delete(h, gid):
    if not Game.get_for(gid, h.uid):
        return h.send_json(404, {"error": "not found"})
    Game.delete_for(gid, h.uid)  # existing videos/clips keep their game name; nothing else is deleted
    h.send_json(200, {"ok": True})


def h_game_test(h, gid):
    """Check that this game's Twitch category and YouTube search return something."""
    from app.engine import discovery
    g = Game.get_for(gid, h.uid)
    if not g:
        return h.send_json(404, {"error": "not found"})
    t_ok, t_msg = discovery.twitch_check(g.get("twitch_category", ""))
    y_ok, y_msg = discovery.youtube_check(g.get("youtube_query", ""))
    h.send_json(200, {"twitch": {"ok": t_ok, "message": t_msg}, "youtube": {"ok": y_ok, "message": y_msg}})


ROUTES = [
    (r"/api/games", "GET", h_games),
    (r"/api/games", "POST", h_game_create),
    (r"/api/games/([a-z0-9-]{1,40})", "PATCH", h_game_patch),
    (r"/api/games/([a-z0-9-]{1,40})", "DELETE", h_game_delete),
    (r"/api/games/([a-z0-9-]{1,40})/test", "POST", h_game_test),
]
bp = Blueprint("game", __name__)
register(bp, ROUTES)
