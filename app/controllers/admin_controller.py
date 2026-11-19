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
    out = [{**auth.public(u), "videos": vids.get(str(u["_id"]), 0), "games": games.get(str(u["_id"]), 0),
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
        "disk": storage.disk(), "yt_quota": {"used": youtube_api.quota_used(), "total": youtube_api.daily_units()}})


# ---------------------------------------------------------------- tokens
def h_tokens(h):
    p = tokens.pricing()
    h.send_json(200, {"balance": tokens.balance(h.uid), "owner": h.is_owner(), "pricing": p, "ledger": tokens.ledger(h.uid),
                      "costs": {"short": tokens.cost("auto-short", "all"), "short_clips": tokens.cost("auto-short", "both"),
                                "compilation": tokens.cost("auto-compilation", "all"), "compilation_clips": tokens.cost("auto-compilation", "both")}})


def h_admin_tokens(h, uid):
    d = h.body_json()
    delta = int(d.get("delta", 0))
    if delta == 0 or abs(delta) > 1_000_000:
        raise ValueError("Enter a number of tokens to add (or a negative number to remove).")
    if not User.find_one(id=oid(uid)):
        return h.send_json(404, {"error": "user not found"})
    tokens.adjust(uid, delta, str(d.get("note") or ("Added by the owner" if delta > 0 else "Removed by the owner"))[:120])
    h_admin_users(h)


def h_admin_pricing(h):
    tokens.set_pricing(h.body_json())
    h_admin_users(h)


ROUTES = [
    (r"/api/admin/users", "GET", h_admin_users),
    (r"/api/admin/users/([0-9a-f]{24})/status", "POST", h_admin_user_status),
    (r"/api/admin/users/([0-9a-f]{24})", "DELETE", h_admin_user_delete),
    (r"/api/admin/signup", "PUT", h_admin_signup),
    (r"/api/admin/users/([0-9a-f]{24})/tokens", "POST", h_admin_tokens),
    (r"/api/admin/pricing", "PUT", h_admin_pricing),
    (r"/api/tokens", "GET", h_tokens),
    (r"/api/admin/system", "GET", h_admin_system),
]
OWNER_ONLY.update({h_admin_users, h_admin_user_status, h_admin_user_delete, h_admin_signup, h_admin_system, h_admin_tokens, h_admin_pricing})
bp = Blueprint("admin", __name__)
register(bp, ROUTES)
