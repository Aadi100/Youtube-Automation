"""Controller (the C of MVC): auth endpoints."""
import re

from flask import Blueprint

from app.http import register
from app.models import User, UserPrefs
from app.runtime import AUDIO, COOKIE
from app.services import auth_service as auth
from app.utils.envfile import read_env
from app.views.serializers import _me


# ---------------------------------------------------------------- accounts
def _set_cookie(h, token: str, max_age: int) -> None:
    secure = "; Secure" if (h.headers.get("X-Forwarded-Proto") == "https" or read_env().get("PUBLIC_BASE_URL", "").startswith("https://")) else ""
    h._extra.append(("Set-Cookie", f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"))


def h_auth_status(h):
    n = auth.user_count()
    h.send_json(200, {"needs_owner": n == 0, "signup": auth.signup_mode(), "local": h.is_local()})


def h_signup(h):
    d = h.body_json()
    u, msg = auth.signup(d.get("email"), d.get("name"), d.get("password"), h.client_ip(), h.is_local(), str(d.get("setup_code") or "").strip().upper())
    logged_in = False
    if u["role"] == "owner":   # the first account is signed in straight away
        token, _ = auth.login(u["email"], d.get("password"), h.client_ip(), h.headers.get("User-Agent", ""))
        _set_cookie(h, token, auth.SESSION_DAYS * 86400)
        logged_in = True
    h.send_json(201, {"ok": True, "message": msg, "logged_in": logged_in, "status": u["status"]})


def h_login(h):
    d = h.body_json()
    try:
        token, u = auth.login(d.get("email"), d.get("password"), h.client_ip(), h.headers.get("User-Agent", ""))
    except ValueError as e:
        return h.send_json(401, {"error": str(e)})
    _set_cookie(h, token, auth.SESSION_DAYS * 86400)
    h.send_json(200, {"user": _me(u)})


def h_logout(h):
    auth.logout(h.session_token())
    _set_cookie(h, "", 0)
    h.send_json(200, {"ok": True})


def h_me(h):
    h.send_json(200, {"user": _me(h.user)})


def h_password(h):
    d = h.body_json()
    auth.change_password(h.uid, d.get("old"), d.get("new"))
    from app.services import profile_service
    profile_service.end_other_sessions(h.uid, h.session_token())      # a new password signs every other device out
    h.send_json(200, {"ok": True, "message": "Password changed."})


def h_prefs_put(h):
    d, upd = h.body_json(), {}
    if "tts_voice" in d:
        v = str(d["tts_voice"] or "").strip()
        if v and not re.fullmatch(r"(random|en-[A-Za-z]{2}-\w+Neural)", v):
            raise ValueError("bad voice")
        upd["tts_voice"] = v
    if "default_audio" in d:
        v = str(d["default_audio"] or "").strip()
        if v and v not in AUDIO:
            raise ValueError("bad audio mode")
        upd["default_audio"] = v
    if "hold_uploads" in d:
        upd["hold_uploads"] = bool(d["hold_uploads"])
    if "notify_to" in d:
        v = str(d["notify_to"] or "").strip()[:120]
        if v and not auth.EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address for notifications.")
        upd["notify_to"] = v
    if "tour" in d:                                   # the first-visit tour: done, skipped, or empty to see it again
        v = str(d["tour"] or "")
        if v not in ("", "done", "skipped"):
            raise ValueError("bad tour state")
        upd["tour"] = v
    if upd:
        UserPrefs.set_fields(h.uid, upd, upsert=True)
    h.send_json(200, {"user": _me(User.find_one(id=h.user["_id"]))})


ROUTES = [
    (r"/api/auth/status", "GET", h_auth_status),
    (r"/api/auth/signup", "POST", h_signup),
    (r"/api/auth/login", "POST", h_login),
    (r"/api/auth/logout", "POST", h_logout),
    (r"/api/auth/password", "POST", h_password),
    (r"/api/me", "GET", h_me),
    (r"/api/prefs", "PUT", h_prefs_put),
]
bp = Blueprint("auth", __name__)
register(bp, ROUTES)
