"""Controller (the C of MVC): the notification bell, its list and each member's notification choices."""
from flask import Blueprint

from app.http import register
from app.models import UserPrefs
from app.services import auth_service as auth
from app.services import notification_service as notes
from app.services import notify_service as mail


def h_list(h):
    unread = h.q.get("unread") in ("1", "true")
    try:
        limit, skip = int(h.q.get("limit") or 30), int(h.q.get("skip") or 0)
    except ValueError:
        raise ValueError("bad paging")
    h.send_json(200, {"items": notes.list_for(h.uid, unread, limit, skip), "unread": notes.unread_count(h.uid)})


def h_count(h):
    """Asked every few seconds by the dashboard: how many unread, and the newest one (so a new message can pop up)."""
    h.send_json(200, {"unread": notes.unread_count(h.uid), "latest": notes.latest(h.uid)})


def h_read(h):
    ids = h.body_json().get("ids")
    n = notes.mark_read(h.uid, ids if isinstance(ids, list) else None)
    h.send_json(200, {"marked": n, "unread": notes.unread_count(h.uid)})


def h_delete(h, nid):
    ok = notes.delete_one(h.uid, nid)
    h.send_json(200 if ok else 404, {"ok": ok, "unread": notes.unread_count(h.uid)})


def h_clear(h):
    h.send_json(200, {"removed": notes.clear_read(h.uid), "unread": notes.unread_count(h.uid)})


def _prefs_view(h) -> dict:
    p = UserPrefs.of(h.uid)
    return {"prefs": notes.prefs_for(h.uid, h.user["role"]), "notify_to": p.get("notify_to", ""), "account_email": h.user["email"], "email_ready": mail.configured({**mail.get_cfg(), "to": "x"})}


def h_prefs(h):
    h.send_json(200, _prefs_view(h))


def h_prefs_put(h):
    d = h.body_json()
    if "notify_to" in d:
        v = str(d["notify_to"] or "").strip()[:120]
        if v and not auth.EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        UserPrefs.set_fields(h.uid, {"notify_to": v}, upsert=True)
    if isinstance(d.get("prefs"), dict):
        notes.set_prefs(h.uid, h.user["role"], d["prefs"])
    h.send_json(200, _prefs_view(h))


ROUTES = [
    (r"/api/notifications", "GET", h_list),
    (r"/api/notifications/count", "GET", h_count),
    (r"/api/notifications/read", "POST", h_read),
    (r"/api/notifications/clear", "POST", h_clear),
    (r"/api/notifications/prefs", "GET", h_prefs),
    (r"/api/notifications/prefs", "PUT", h_prefs_put),
    (r"/api/notifications/([0-9a-f]{24})", "DELETE", h_delete),
]
bp = Blueprint("notification", __name__)
register(bp, ROUTES)
