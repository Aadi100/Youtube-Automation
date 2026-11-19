"""Process-wide settings and shared state: ports, roles, worker id, limits, the settings the dashboard may edit."""
import os
import socket
import sys
import threading

from app.config import BASE_DIR
from app.utils.envfile import read_env

HOST = os.environ.get("STUDIO_HOST") or read_env().get("STUDIO_HOST") or "127.0.0.1"   # a server behind a proxy uses 0.0.0.0
PORT = int(os.environ.get("STUDIO_PORT") or 8765)
DASH = BASE_DIR / "app" / "views" / "dashboard" / "index.html"
ENV_FILE = BASE_DIR / ".env"
N8N_PUBLISH_URL = "http://localhost:5678/webhook/clip-studio-publish"
N8N_UPLOAD_URL = "http://localhost:5678/webhook/clip-studio-upload"
N8N_THUMB_URL = "http://localhost:5678/webhook/clip-studio-thumbnail"


def allowed_hosts() -> set:
    """localhost, plus the host of PUBLIC_BASE_URL if you expose the server (e.g. via a tunnel)."""
    hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    base = read_env().get("PUBLIC_BASE_URL", "")
    if base:
        from urllib.parse import urlparse
        u = urlparse(base)
        if u.netloc:
            hosts.add(u.netloc)
    return hosts


MODES = {"auto-short", "auto-compilation"}
AUDIO = {"replace", "bed", "original"}
STATUSES = {"rendered", "uploaded", "public", "failed", "discarded"}
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
MAX_UPLOAD = 60 * 1024 * 1024


# settings editable from the dashboard (secret values are never sent back to the browser)
SETTINGS = {
    "TWITCH_CLIENT_ID": False, "TWITCH_CLIENT_SECRET": True,
    "YOUTUBE_API_KEY": True, "GEMINI_API_KEY": True, "DEEPSEEK_API_KEY": True, "DEEPSEEK_MODEL": False, "LLM_SPLIT": False, "GEMINI_MODEL": False, "CONTACT_EMAIL": False, "TTS_VOICE": False,
    "CLIP_COUNTRIES": False, "CLIP_LANGUAGES": False, "LIVE_WATCH_MINUTES": False, "LIVE_STREAMS": False, "AI_THUMBNAILS": False, "AI_IMAGE_PROVIDER": False, "DEFAULT_AUDIO_MODE": False, "SAFE_MODE": False,
    # email notifications (SMTP)
    "SMTP_HOST": False, "SMTP_PORT": False, "SMTP_SECURITY": False, "SMTP_USER": False, "SMTP_PASSWORD": True,
    "SMTP_FROM": False, "NOTIFY_TO": False, "PUBLIC_BASE_URL": False,
    # YouTube sign-in for members (Google Cloud OAuth client) and the daily upload allowance
    "GOOGLE_CLIENT_ID": False, "GOOGLE_CLIENT_SECRET": True, "YT_DAILY_UNITS": False,
}
MAX_JOBS = max(1, int(os.environ.get("MAX_CONCURRENT_JOBS") or read_env().get("MAX_CONCURRENT_JOBS") or 1))   # jobs rendering at the same time
USER_ACTIVE_LIMIT = 4          # queued + running jobs one member may have at once
RUNNING: dict = {}             # job id -> subprocess (None while it is starting)
WAKE = threading.Event()
WORKER_ID = os.environ.get("WORKER_ID") or socket.gethostname()
ROLE = (os.environ.get("STUDIO_ROLE") or "all").lower()   # web = dashboard/API only | worker = renders, schedules, uploads | all = both


for i, a in enumerate(sys.argv):
    if a == "--role" and i + 1 < len(sys.argv):
        ROLE = sys.argv[i + 1].lower()
    elif a.startswith("--role="):
        ROLE = a.split("=", 1)[1].lower()


# ------------------------------------------------------------------ job runner + queue
KEEP_LOG = 300
COOKIE = "studio_session"
TWITCH_STATUSES = {"pending", "uploaded", "skipped"}


# ------------------------------------------------- upload queue
UPLOAD_WAKE = threading.Event()
DEFAULTS = {"SMTP_PORT": "587", "SMTP_SECURITY": "starttls", "PUBLIC_BASE_URL": f"http://localhost:{PORT}", "GEMINI_MODEL": "gemini-flash-latest", "TTS_VOICE": "en-US-GuyNeural",
            "DEEPSEEK_MODEL": "deepseek-chat", "LLM_SPLIT": "balanced", "LIVE_WATCH_MINUTES": "8", "LIVE_STREAMS": "4", "AI_THUMBNAILS": "on", "AI_IMAGE_PROVIDER": "free", "DEFAULT_AUDIO_MODE": "replace", "SAFE_MODE": "on", "YT_DAILY_UNITS": "10000",
            "CLIP_COUNTRIES": "US,CA,GB,IE,DE,FR,ES,IT,NL,BE,SE,NO,DK,FI,PL,PT,AT,CH,CZ,RO,GR,HU",
            "CLIP_LANGUAGES": "en,de,fr,it,nl,sv,da,no,fi,pl,pt,cs,ro,el,hu"}


# ---------------------------------------------------------------- schedule (edited on the dashboard)
# n8n's schedule nodes poll every few minutes and ask /api/schedule/claim/<kind>; the times live here so they
# can be changed on the dashboard without touching n8n.
SCHED_DEFAULT = {"timezone": "Europe/London",  # targets Europe + US/Canada audiences
                 "shorts": {"enabled": True, "times": ["11:30", "14:30", "17:30", "20:30", "23:30"]},
                 "compilation": {"enabled": True, "times": ["09:00"]}}
SCHED_CATCHUP_MIN = 30  # a slot missed by a restart/busy worker is still run if we're within this many minutes
