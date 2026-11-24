"""Accounts, roles and sessions.

Roles
  owner   full access: every setting, user management, and (like everyone) their own workspace of games / videos / clips
  member  their own workspace only; cannot see other members' data or change server-wide settings
Status: active | pending (waiting for the owner's approval) | disabled

Security: passwords are hashed with scrypt (never stored), session tokens are random and only their hash is stored,
failed logins are rate limited, cookies are HttpOnly + SameSite=Lax (+ Secure behind HTTPS).
The very first account becomes the owner: from this computer directly, or with the setup code on a server.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import timedelta
from typing import Dict, Optional, Tuple

from mongoengine.errors import NotUniqueError

from app import models
from app.models import AuthAttempt, Clip, Game, Job, Session, Setting, System, User, UserPrefs, Video, migrate_legacy, now, oid, raw

SESSION_DAYS = 14
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
MAX_FAILS, FAIL_WINDOW_MIN = 8, 15
SIGNUP_MODES = ("open", "approval", "closed")


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$14$8$1${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n_exp, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(salt), n=2 ** int(n_exp), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


# ---------------------------------------------------------------- setup
def ensure_indexes() -> None:
    models.create_indexes()


def user_count() -> int:
    return User.objects.count()


def owner_id() -> Optional[str]:
    o = User.objects(role="owner", status="active").order_by("created_at").first()
    return str(o.id) if o else None


def signup_mode() -> str:
    doc = raw(System.objects(id="auth").first()) or {}
    return doc.get("signup") if doc.get("signup") in SIGNUP_MODES else "approval"


def set_signup_mode(mode: str) -> None:
    if mode not in SIGNUP_MODES:
        raise ValueError(f"signup must be one of {SIGNUP_MODES}")
    System.objects(id="auth").update_one(upsert=True, set__signup=mode)


def public(u: Dict) -> Dict:
    return {"id": str(u["_id"]), "email": u["email"], "name": u.get("name") or u["email"].split("@")[0], "role": u["role"],
            "status": u["status"], "tokens": int(u.get("tokens", 0)),
            "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
            "last_login": u["last_login"].isoformat() if u.get("last_login") else None}


# ---------------------------------------------------------------- rate limiting
def _attempts(key: str) -> int:
    return AuthAttempt.objects(key=key).count()


def _record(key: str) -> None:
    AuthAttempt(key=key, t=now()).save()


# ---------------------------------------------------------------- users
def create_user(email: str, name: str, password: str, role: str = "member", status: str = "active") -> Dict:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    if len(password or "") < 8:
        raise ValueError("The password must be at least 8 characters.")
    if len(password) > 200:
        raise ValueError("The password is too long.")
    name = " ".join((name or "").split())[:60] or email.split("@")[0]
    try:
        u = User(email=email, name=name, pw_hash=hash_password(password), role=role, status=status, tokens=0,
                 created_at=now()).save(force_insert=True)
    except NotUniqueError:
        raise ValueError("An account with this email already exists.")
    return raw(u)


def signup(email: str, name: str, password: str, ip: str, is_local: bool, setup_code: str = "") -> Tuple[Dict, str]:
    """Create an account. Returns (user, message). The first account is the owner."""
    key = f"signup:{ip}"
    if _attempts(key) >= 10:
        raise ValueError("Too many sign-up attempts from this address. Try again later.")
    _record(key)
    if user_count() == 0:
        from app.utils.envfile import setup_code as expected
        if not is_local and not hmac.compare_digest(setup_code or "", expected()):
            raise ValueError("This is a new server: enter the setup code shown in the server console (or run: python worker.py --show-setup-code).")
        u = create_user(email, name, password, role="owner", status="active")
        migrate_legacy(str(u["_id"]))
        return u, "Owner account created. Welcome!"
    mode = signup_mode()
    if mode == "closed":
        raise ValueError("Sign-up is closed. Ask the owner for an invitation.")
    status = "active" if mode == "open" else "pending"
    u = create_user(email, name, password, role="member", status=status)
    try:
        from app.services import notification_service as notes
        if status == "pending":
            notes.notify_owner("signup", f"{u.get('name') or u['email']} is waiting for approval", u["email"], "#/users", "info", key=f"signup-{u['_id']}")
        else:
            notes.notify(str(u["_id"]), "account", "Welcome to Clip Studio", "Connect your YouTube channel in Profile, then make your first video on the Create page.", "#/profile", "success")
    except Exception:
        pass
    try:
        from app.services import token_service as tokens
        bonus = tokens.pricing()["signup_bonus"]
        if bonus > 0:
            tokens.adjust(u["_id"], bonus, "Welcome bonus")
    except Exception:
        pass
    return u, ("Account created. You can log in now." if status == "active" else "Account created. The owner has to approve it before you can log in.")


def login(email: str, password: str, ip: str, ua: str) -> Tuple[Optional[str], Dict]:
    """Returns (session token, user). Raises ValueError with a safe message."""
    email = (email or "").strip().lower()
    for key in (f"login:{ip}", f"login:{email}"):
        if _attempts(key) >= MAX_FAILS:
            raise ValueError(f"Too many failed attempts. Wait {FAIL_WINDOW_MIN} minutes and try again.")
    u = raw(User.objects(email=email).first())
    if not u or not verify_password(password or "", u["pw_hash"]):
        _record(f"login:{ip}")
        _record(f"login:{email}")
        raise ValueError("Wrong email or password.")
    if u["status"] == "pending":
        raise ValueError("Your account is waiting for the owner's approval.")
    if u["status"] != "active":
        raise ValueError("This account is disabled. Contact the owner.")
    token = secrets.token_urlsafe(32)
    Session(id=hashlib.sha256(token.encode()).hexdigest(), user_id=u["_id"], created_at=now(),
            expires_at=now() + timedelta(days=SESSION_DAYS), ip=ip, ua=(ua or "")[:160]).save(force_insert=True)
    User.objects(id=u["_id"]).update(set__last_login=now())
    return token, u


def user_for_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    s = Session.objects(id=hashlib.sha256(token.encode()).hexdigest(), expires_at__gt=now()).first()
    if not s:
        return None
    u = raw(User.objects(id=s.user_id).first())
    return u if u and u["status"] == "active" else None


def logout(token: str) -> None:
    if token:
        Session.objects(id=hashlib.sha256(token.encode()).hexdigest()).delete()


def end_all_sessions(user_id) -> None:
    Session.objects(user_id=oid(str(user_id))).delete()


def set_status(user_id: str, status: str) -> None:
    if status not in ("active", "pending", "disabled"):
        raise ValueError("bad status")
    u = User.objects(id=oid(user_id)).first()
    if not u:
        raise ValueError("user not found")
    if u.role == "owner" and status != "active":
        raise ValueError("The owner account cannot be disabled.")
    was = u.status
    User.objects(id=u.id).update(set__status=status)
    if status != "active":
        end_all_sessions(user_id)
    elif was == "pending":
        from app.services import notification_service as notes
        notes.notify(str(u.id), "account", "Your account was approved", "Welcome! Connect your YouTube channel in Profile, then make your first video.", "#/profile", "success")


def delete_user(user_id: str) -> None:
    u = User.objects(id=oid(user_id)).first()
    if not u:
        raise ValueError("user not found")
    if u.role == "owner":
        raise ValueError("The owner account cannot be deleted.")
    end_all_sessions(user_id)
    uid = str(u.id)
    u.delete()
    for M in (Game, Clip, Job):
        M.objects(user_id=uid).delete()
    Video.objects(user_id=uid).update(set__status="discarded", set__orphaned=True)
    UserPrefs.objects(id=uid).delete()
    Setting.objects(id__in=[f"clipping:{uid}", f"schedule:{uid}"]).delete()


def change_password(user_id: str, old: str, new: str) -> None:
    u = User.objects(id=oid(user_id)).first()
    if not u or not verify_password(old or "", u.pw_hash):
        raise ValueError("The current password is wrong.")
    if len(new or "") < 8:
        raise ValueError("The new password must be at least 8 characters.")
    User.objects(id=u.id).update(set__pw_hash=hash_password(new))
    from app.services import notification_service as notes
    notes.notify(str(u.id), "account", "Your password was changed", "If this was not you, contact the owner right away.", "#/profile", "warn")
