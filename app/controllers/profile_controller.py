"""Controller (the C of MVC): my profile."""
from flask import Blueprint

from app.http import register
from app.models import User
from app.services import notification_service as notes
from app.services import profile_service as ps
from app.views.serializers import _me


def h_profile(h):
    h.send_json(200, ps.overview(h.user))


def h_profile_put(h):
    d = h.body_json()
    user = ps.update(h.user, d.get("name") if "name" in d else None, d.get("email") if "email" in d else None, d.get("current_password"))
    h.send_json(200, {"user": _me(user)})


def h_avatar_post(h):
    n = int(h.headers.get("Content-Length") or 0)
    if not 0 < n <= 5_000_000:
        raise ValueError("Choose a picture up to 5 MB.")
    ps.save_avatar(h.uid, h.rfile.read(n))
    h.send_json(200, {"ok": True, "user": _me(User.find_one(id=h.user["_id"]))})


def h_avatar_delete(h):
    ps.remove_avatar(h.uid)
    h.send_json(200, {"ok": True, "user": _me(User.find_one(id=h.user["_id"]))})


def h_avatar_get(h):
    p = ps.avatar_path(h.uid)
    if not p.is_file():
        return h.send_json(404, {"error": "no picture"})
    h.send_file(p, "image/png")


def h_sessions(h):
    h.send_json(200, {"sessions": ps.sessions(h.uid, h.session_token())})


def h_session_end(h, sid):
    ok = ps.end_session(h.uid, sid, h.session_token())
    if ok:
        notes.notify(h.uid, "account", "A device was signed out", "You signed out one of your devices.", "#/profile", "info")
    h.send_json(200 if ok else 404, {"ok": ok, "sessions": ps.sessions(h.uid, h.session_token())})


def h_sessions_others(h):
    n = ps.end_other_sessions(h.uid, h.session_token())
    if n:
        notes.notify(h.uid, "account", "Signed out of your other devices", f"{n} other device{'s were' if n > 1 else ' was'} signed out.", "#/profile", "info")
    h.send_json(200, {"ended": n, "sessions": ps.sessions(h.uid, h.session_token())})


def h_close(h):
    d = h.body_json()
    ps.close_account(h.user, d.get("password"), d.get("confirm"))
    h.send_json(200, {"ok": True})


ROUTES = [
    (r"/api/profile", "GET", h_profile),
    (r"/api/profile", "PUT", h_profile_put),
    (r"/api/profile/avatar", "POST", h_avatar_post),
    (r"/api/profile/avatar", "DELETE", h_avatar_delete),
    (r"/api/profile/avatar", "GET", h_avatar_get),
    (r"/api/profile/sessions", "GET", h_sessions),
    (r"/api/profile/sessions/others", "POST", h_sessions_others),
    (r"/api/profile/sessions/([0-9a-f]{12})", "DELETE", h_session_end),
    (r"/api/profile/close", "POST", h_close),
]
bp = Blueprint("profile", __name__)
register(bp, ROUTES)
