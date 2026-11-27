"""Controller (the C of MVC): youtube endpoints."""
import secrets as pysecrets
from datetime import timedelta

from flask import Blueprint

from app.http import register
from app.models import OAuthState, Video, now
from app.runtime import PORT, UPLOAD_WAKE
from app.services import youtube_service as youtube_api
from app.utils.envfile import read_env


# ---------------------------------------------------------------- YouTube connection (Sign in with Google)
def _redirect_uri(h) -> str:
    base = (read_env().get("PUBLIC_BASE_URL") or "").rstrip("/") or f"http://{h.headers.get('Host', f'localhost:{PORT}')}"
    return base + "/api/youtube/callback"


def h_yt_status(h):
    st = youtube_api.public_status(h.uid)
    if h.is_owner():
        st.update(redirect_uri=_redirect_uri(h), quota_used=youtube_api.quota_used(), quota_total=youtube_api.daily_units(),
                      uploads_used=youtube_api.uploads_used(), uploads_total=youtube_api.daily_uploads())
    st["queued_uploads"] = Video.total(user_id=h.uid, upload_status__in=["queued", "uploading"])
    h.send_json(200, st)


def h_yt_connect(h):
    if not youtube_api.configured():
        raise ValueError("The owner has not set up Google sign-in yet (Settings -> Accounts & keys -> Google client ID / secret).")
    state = pysecrets.token_urlsafe(24)
    OAuthState(id=state, user_id=h.uid, t=now()).save(force_insert=True)
    h.send_json(200, {"url": youtube_api.auth_url(_redirect_uri(h), state)})


def h_yt_connect_analytics(h):
    """Ask the member for the ONE extra permission (read-only Analytics). The upload permission they already gave is kept."""
    if not youtube_api.configured():
        raise ValueError("The owner has not set up Google sign-in yet (Settings -> Accounts & keys -> Google client ID / secret).")
    if not youtube_api.get_account(h.uid):
        raise ValueError("Connect your YouTube channel first (Settings -> YouTube), then allow Analytics.")
    state = pysecrets.token_urlsafe(24)
    OAuthState(id=state, user_id=h.uid, t=now()).save(force_insert=True)
    h.send_json(200, {"url": youtube_api.auth_url(_redirect_uri(h), state, scopes=[youtube_api.ANALYTICS_SCOPE])})


def _redirect(h, url: str) -> None:
    h.send_response(302)
    h.send_header("Location", url)
    h.send_header("Content-Length", "0")
    h.end_headers()


def h_yt_callback(h):
    from urllib.parse import quote
    st = OAuthState.take(id=h.q.get("state", ""))
    if h.q.get("error") or not st or not h.q.get("code"):
        return _redirect(h, "/?yt=err&msg=" + quote(h.q.get("error") or "The sign-in link expired. Try connecting again.") + "#/settings")
    try:
        info = youtube_api.save_account(st["user_id"], youtube_api.exchange_code(h.q["code"], _redirect_uri(h)))
    except youtube_api.YTError as e:
        return _redirect(h, "/?yt=err&msg=" + quote(str(e)[:200]) + "#/settings")
    # videos made before the channel was connected go up now
    since = now() - timedelta(days=3)
    Video.update_where(user_id=st["user_id"], status="rendered", youtube_id=None, created_at__gte=since, one=False,
                       fields={"upload_status": "queued", "upload_privacy": "unlisted"})
    UPLOAD_WAKE.set()
    _redirect(h, "/?yt=ok&msg=" + quote(info["channel_title"]) + "#/settings")


def h_yt_disconnect(h):
    youtube_api.disconnect(h.uid)
    h.send_json(200, {"ok": True})


ROUTES = [
    (r"/api/youtube/status", "GET", h_yt_status),
    (r"/api/youtube/connect", "POST", h_yt_connect),
    (r"/api/youtube/connect-analytics", "POST", h_yt_connect_analytics),
    (r"/api/youtube/callback", "GET", h_yt_callback),
    (r"/api/youtube/disconnect", "POST", h_yt_disconnect),
]
bp = Blueprint("youtube", __name__)
register(bp, ROUTES)
