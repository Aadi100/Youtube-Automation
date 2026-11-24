"""Controller (the C of MVC): admin endpoints."""
import re
import time
from datetime import timedelta

from flask import Blueprint
from mongoengine import Q

from app.http import OWNER_ONLY, register
from app.models import Game, Job, System, User, Video, YtAccount, now, oid
from app.runtime import MAX_JOBS, USER_ACTIVE_LIMIT
from app.services import auth_service as auth
from app.services import storage_service as storage
from app.services import token_service as tokens
from app.services import youtube_service as youtube_api


# ---------------------------------------------------------------- owner: users and system
def h_admin_users(h):
    q = (h.q.get("q") or "").strip()
    page = max(1, int(h.q.get("page") or 1))
    size = 50
    cond = (Q(email__iregex=re.escape(q)) | Q(name__iregex=re.escape(q))) if q else Q()
    total = User.total(cond)
    docs = User.find_all(cond, order=("created_at",), skip=(page - 1) * size, limit=size)
    ids = [str(u["_id"]) for u in docs]
    vids, games = Video.count_by("user_id", user_id__in=ids), Game.count_by("user_id", user_id__in=ids)
    active = Job.count_by("user_id", user_id__in=ids, status__in=["queued", "running"])
    yt = {a["user_id"]: a.get("channel_title") for a in YtAccount.find_all(user_id__in=ids, only=("user_id", "channel_title"))}
    today = Video.count_by("user_id", Q(uploaded_at__gte=tokens.day_start()) | Q(upload_status="uploading"), user_id__in=ids)
    out = [{**auth.public(u), "upload_limit": u.get("upload_limit"), "upload_limit_now": tokens.daily_limit(u), "uploads_today": today.get(str(u["_id"]), 0),
            "videos": vids.get(str(u["_id"]), 0), "games": games.get(str(u["_id"]), 0),
            "active_jobs": active.get(str(u["_id"]), 0), "youtube": yt.get(str(u["_id"]))} for u in docs]
    h.send_json(200, {"users": out, "total": total, "page": page, "pages": max(1, -(-total // size)), "pending": User.total(status="pending"),
                      "accounts": User.total(), "signup": auth.signup_mode(), "pricing": tokens.pricing()})


def h_admin_user_status(h, uid):
    auth.set_status(uid, str(h.body_json().get("status")))
    h_admin_users(h)


def h_admin_user_delete(h, uid):
    if uid == h.uid:
        raise ValueError("You cannot delete your own account.")
    auth.delete_user(uid)
    h_admin_users(h)


def h_admin_signup(h):
    auth.set_signup_mode(str(h.body_json().get("mode")))
    h_admin_users(h)


def h_admin_system(h):
    alive = [w for w in System.find_all(id__regex="^worker:") if time.time() - w.get("t", 0) < 60]
    day = now() - timedelta(hours=24)
    h.send_json(200, {
        "max_jobs": sum(int(w.get("max", 0)) for w in alive) or MAX_JOBS, "running": Job.total(status="running"),
        "queued": Job.total(status="queued"), "users": auth.user_count(), "per_user_limit": USER_ACTIVE_LIMIT,
        "workers": [{"id": w["_id"][7:], "running": w.get("running", 0), "max": w.get("max", 0), "role": w.get("role", "")} for w in alive],
        "failed_24h": Job.total(status="failed", finished_at__gte=day),
        "done_24h": Job.total(status="done", finished_at__gte=day),
        "uploads_waiting": Video.total(upload_status__in=["queued", "uploading"]),
        "disk": storage.disk(), "yt_quota": {"used": youtube_api.quota_used(), "total": youtube_api.daily_units(), "uploads_used": youtube_api.uploads_used(), "uploads_total": youtube_api.daily_uploads()}})


# ---------------------------------------------------------------- tokens
def h_tokens(h):
    p = tokens.pricing()
    lim = tokens.daily_limit(h.user)
    h.send_json(200, {"balance": tokens.balance(h.uid), "owner": h.is_owner(), "pricing": p if h.is_owner() else {}, "ledger": tokens.ledger(h.uid),
                      "reserve": {"short": tokens.cost("auto-short"), "compilation": tokens.cost("auto-compilation")},
                      "upload_fee": {"short": tokens.upload_fee("short"), "compilation": tokens.upload_fee("compilation")},
                      "daily_uploads": lim, "uploaded_today": tokens.uploads_today(h.uid)})


def h_admin_tokens(h, uid):
    d = h.body_json()
    delta = int(d.get("delta", 0))
    if delta == 0 or abs(delta) > 1_000_000:
        raise ValueError("Enter a number of tokens to add (or a negative number to remove).")
    if not User.find_one(id=oid(uid)):
        return h.send_json(404, {"error": "user not found"})
    note = str(d.get("note") or ("Added by the owner" if delta > 0 else "Removed by the owner"))[:120]
    tokens.adjust(uid, delta, note)
    from app.services import notification_service as notes
    notes.notify(uid, "tokens", f"{delta} tokens were added" if delta > 0 else f"{-delta} tokens were removed", note, "#/usage", "success" if delta > 0 else "info")
    h_admin_users(h)


def h_admin_pricing(h):
    tokens.set_pricing(h.body_json())
    h_admin_users(h)


def h_admin_diy(h):
    """Which do-it-yourself options members may use."""
    from app.services import diy_service
    data = h.body_json() if h.q is not None and h.headers.get("Content-Length") not in (None, "", "0") else {}
    if data:
        diy_service.set_flags(data)
    h.send_json(200, {"flags": diy_service.flags(), "labels": diy_service.FLAGS})


def h_admin_user_limit(h, uid):
    """How many videos this member may upload per day (empty = the default for everybody)."""
    if not User.find_one(id=oid(uid)):
        return h.send_json(404, {"error": "user not found"})
    tokens.set_upload_limit(uid, h.body_json().get("upload_limit"))
    h_admin_users(h)


ROUTES = [
    (r"/api/admin/users", "GET", h_admin_users),
    (r"/api/admin/users/([0-9a-f]{24})/status", "POST", h_admin_user_status),
    (r"/api/admin/users/([0-9a-f]{24})", "DELETE", h_admin_user_delete),
    (r"/api/admin/signup", "PUT", h_admin_signup),
    (r"/api/admin/users/([0-9a-f]{24})/tokens", "POST", h_admin_tokens),
    (r"/api/admin/pricing", "PUT", h_admin_pricing),
    (r"/api/admin/diy", "PUT", h_admin_diy),
    (r"/api/admin/diy", "GET", h_admin_diy),
    (r"/api/admin/users/([0-9a-f]{24})/limit", "POST", h_admin_user_limit),
    (r"/api/tokens", "GET", h_tokens),
    (r"/api/admin/system", "GET", h_admin_system),
]
OWNER_ONLY.update({h_admin_users, h_admin_user_status, h_admin_user_delete, h_admin_signup, h_admin_system, h_admin_tokens, h_admin_pricing,
                   h_admin_user_limit, h_admin_diy})
bp = Blueprint("admin", __name__)
register(bp, ROUTES)
