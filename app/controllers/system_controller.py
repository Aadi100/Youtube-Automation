"""Controller (the C of MVC): system endpoints."""
import shutil
from pathlib import Path

from flask import Blueprint

from app.config import FFMPEG_BIN, MUSIC_DIR
from app.http import register
from app.models import Clip, Job, Video, ping
from app.runtime import DASH, MUSIC_EXT
from app.services import notify_service as notify
from app.services.queue_service import busy
from app.utils.envfile import read_env


# --------------------------------------------------------------------- handler
def _ffmpeg_ok() -> bool:
    return bool(shutil.which(FFMPEG_BIN) or Path(FFMPEG_BIN).exists())


def h_healthz(h):
    p = ping()
    h.send_json(200 if p["ok"] else 503, {"ok": bool(p["ok"])})


def h_ui_version(h):
    """The dashboard page asks this every few seconds and reloads itself when the file changed."""
    h.send_json(200, {"v": int(DASH.stat().st_mtime)})


def h_index(h):
    body = DASH.read_bytes()
    h.send_response(200)
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


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
    })


def h_stats(h):
    def by(model, field):
        return {(k or "none"): n for k, n in model.count_by(field, user_id=h.uid).items()}
    h.send_json(200, {"videos_by_status": by(Video, "status"), "videos_by_kind": by(Video, "kind"),
                      "clips_by_status": by(Clip, "status"), "jobs_by_status": by(Job, "status")})


ROUTES = [
    (r"/", "GET", h_index),
    (r"/healthz", "GET", h_healthz),
    (r"/api/ui-version", "GET", h_ui_version),
    (r"/api/health", "GET", h_health),
    (r"/api/stats", "GET", h_stats),
]
bp = Blueprint("system", __name__)
register(bp, ROUTES)
