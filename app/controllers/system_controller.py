"""Controller (the C of MVC): system endpoints."""
import shutil
from pathlib import Path

from flask import Blueprint

from app.config import FFMPEG_BIN, MUSIC_DIR
from app.http import register
from app.models import Clip, Job, User, Video, ping
from app.runtime import ASSETS, DASH, LANDING, MUSIC_EXT
from app.services import auth_service as auth
from app.services import notify_service as notify
from app.services.queue_service import busy
from app.utils.envfile import read_env


# --------------------------------------------------------------------- handler
def _ffmpeg_ok() -> bool:
    return bool(shutil.which(FFMPEG_BIN) or Path(FFMPEG_BIN).exists())


def h_healthz(h):
    p = ping()
    h.send_json(200 if p["ok"] else 503, {"ok": bool(p["ok"])})


def _ui_version() -> int:
    """Changes whenever the dashboard page or any of its css/js files changes."""
    try:
        return int(max([DASH.stat().st_mtime] + [f.stat().st_mtime for f in ASSETS.rglob("*") if f.is_file()]))
    except OSError:
        return 0


def h_ui_version(h):
    """The dashboard page asks this every few seconds and reloads itself when something changed."""
    h.send_json(200, {"v": _ui_version()})


ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2"}


def h_asset(h, kind, name):
    """A css / js file of the dashboard. The page asks for it with ?v=<version>, so a browser keeps it until the version changes."""
    f = (ASSETS / kind / name).resolve()
    if ASSETS.resolve() not in f.parents or not f.is_file() or f.suffix not in ASSET_TYPES:
        return h.send_json(404, {"error": "Not found"})
    body = f.read_bytes()
    h.send_response(200)
    h.send_header("Cache-Control", "public, max-age=31536000, immutable" if h.q.get("v") else "no-cache")
    h.send_header("Content-Type", ASSET_TYPES[f.suffix])
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def _page(h, path: Path) -> None:
    body = path.read_bytes()
    if path == DASH:
        body = body.replace(b"__V__", str(_ui_version()).encode())       # the css/js links carry the version
    h.send_response(200)
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def h_index(h):
    """The home page. Visitors who are not signed in see the public landing page; members go straight to the dashboard.
    The very first start (no account yet) and the Google sign-in return trip also open the dashboard."""
    signed_in = bool(auth.user_for_token(h.session_token()))
    if signed_in or h.q.get("yt") or User.total() == 0:
        return _page(h, DASH)
    _page(h, LANDING)


def h_app(h):
    """The dashboard itself: shows the sign-in form to visitors."""
    _page(h, DASH)


def h_health(h):
    env = read_env()
    if not h.is_owner():   # members only need to know the service is working, not how the server is set up
        return h.send_json(200, {"mongo": {"ok": True}, "ffmpeg": True, "busy": busy(), "email": True,
                                 "keys": {"twitch": True, "youtube_api": True, "gemini": True, "deepseek": True, "contact_email": True},
                                 "music_tracks": 1, "member": True})
    h.send_json(200, {
        "mongo": ping(), "ffmpeg": _ffmpeg_ok(), "busy": busy(), "email": notify.configured(),
        "keys": {"twitch": bool(env.get("TWITCH_CLIENT_ID") and env.get("TWITCH_CLIENT_SECRET")),
                 "youtube_api": bool(env.get("YOUTUBE_API_KEY")),
                 "gemini": bool(env.get("GEMINI_API_KEY")), "deepseek": bool(env.get("DEEPSEEK_API_KEY")), "contact_email": bool(env.get("CONTACT_EMAIL"))},
        "music_tracks": len([p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in MUSIC_EXT]),
        "yt_blocked": __import__("app.engine.yt_access", fromlist=["x"]).blocked_seconds() > 0,
    })


def h_stats(h):
    def by(model, field):
        return {(k or "none"): n for k, n in model.count_by(field, user_id=h.uid).items()}
    h.send_json(200, {"videos_by_status": by(Video, "status"), "videos_by_kind": by(Video, "kind"),
                      "clips_by_status": by(Clip, "status"), "jobs_by_status": by(Job, "status")})


ROUTES = [
    (r"/", "GET", h_index),
    (r"/app", "GET", h_app),
    (r"/healthz", "GET", h_healthz),
    (r"/assets/(css|js)/([\w.-]+)", "GET", h_asset),
    (r"/api/ui-version", "GET", h_ui_version),
    (r"/api/health", "GET", h_health),
    (r"/api/stats", "GET", h_stats),
]
bp = Blueprint("system", __name__)
register(bp, ROUTES)
