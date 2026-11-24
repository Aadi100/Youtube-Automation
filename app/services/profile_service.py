"""A member's own profile: name, email, picture, the devices that are signed in, and closing the account."""
import hashlib
import io
import re
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from mongoengine.errors import NotUniqueError

from app.config import STATE_DIR
from app.models import Job, Session, User, UserPrefs, Video, now, oid, raw
from app.services import auth_service as auth
from app.services import notification_service as notes
from app.services import token_service as tokens


# ---------------------------------------------------------------- picture
def avatar_path(uid) -> Path:
    d = STATE_DIR / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{uid}.png"


def has_avatar(uid) -> bool:
    return avatar_path(uid).is_file()


def save_avatar(uid, data: bytes) -> None:
    """Any picture up to 5 MB becomes a 256 x 256 square (centre cropped), so every avatar is small and the same shape."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not 0 < len(data) <= 5_000_000:
        raise ValueError("Choose a picture up to 5 MB.")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("That file is not a picture. Use a JPG or PNG.")
    im = ImageOps.exif_transpose(im).convert("RGBA")
    im = ImageOps.fit(im, (256, 256), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    avatar_path(uid).write_bytes(buf.getvalue())


def remove_avatar(uid) -> None:
    avatar_path(uid).unlink(missing_ok=True)


# ---------------------------------------------------------------- details
def overview(user: Dict) -> Dict:
    uid = str(user["_id"])
    by = Video.count_by("status", user_id=uid)
    return {"user": auth.public(user), "avatar": has_avatar(uid), "email_changed_at": (UserPrefs.of(uid).get("email_changed_at") or None),
            "stats": {"videos": sum(by.values()), "live": by.get("public", 0), "uploaded": by.get("uploaded", 0) + by.get("public", 0),
                      "waiting": by.get("rendered", 0) + by.get("uploaded", 0), "runs": Job.total(user_id=uid, status="done")}}


def update(user: Dict, name: Optional[str], email: Optional[str], current_password: Optional[str]) -> Dict:
    uid = user["_id"]
    upd = {}
    if name is not None:
        nm = " ".join(str(name).split())[:60]
        if len(nm) < 2:
            raise ValueError("Enter your name (at least 2 letters).")
        upd["name"] = nm
    changed_email = False
    if email is not None and str(email).strip().lower() != user["email"]:
        e = str(email).strip().lower()
        if not auth.EMAIL_RE.match(e):
            raise ValueError("Enter a valid email address.")
        fresh = User.objects(id=uid).first()
        if not fresh or not auth.verify_password(current_password or "", fresh.pw_hash):
            raise ValueError("To change your email, enter your current password.")
        upd["email"] = e
        changed_email = True
    if upd:
        try:
            User.objects(id=uid).update(**{f"set__{k}": v for k, v in upd.items()})
        except NotUniqueError:
            raise ValueError("Another account already uses that email.")
    if changed_email:
        notes.notify(str(uid), "account", "Your email address was changed", f"Your sign-in email is now {upd['email']}. If this was not you, change your password now.", "#/profile", "warn")
    return raw(User.objects(id=uid).first())


# ---------------------------------------------------------------- devices that are signed in
def _device(ua: str) -> str:
    ua = ua or ""
    b = next((n for n, rx in (("Edge", r"Edg/"), ("Opera", r"OPR/"), ("Chrome", r"Chrome/"), ("Firefox", r"Firefox/"), ("Safari", r"Safari/")) if re.search(rx, ua)), "Browser")
    o = next((n for n, rx in (("Windows", r"Windows"), ("Android", r"Android"), ("iPhone", r"iPhone|iPad"), ("Mac", r"Mac OS"), ("Linux", r"Linux")) if re.search(rx, ua)), "")
    return f"{b} on {o}" if o else b


def sessions(uid, current_token: str) -> List[Dict]:
    cur = hashlib.sha256((current_token or "").encode()).hexdigest()
    out = []
    for s in Session.objects(user_id=oid(str(uid)), expires_at__gt=now()).order_by("-created_at"):
        d = s.to_mongo().to_dict()
        out.append({"id": d["_id"][:12], "device": _device(d.get("ua", "")), "ip": d.get("ip") or "", "current": d["_id"] == cur,
                    "created_at": d["created_at"].replace(tzinfo=None).isoformat() + "Z" if d.get("created_at") else None})
    return out


def end_session(uid, short_id: str, current_token: str) -> bool:
    cur = hashlib.sha256((current_token or "").encode()).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{12}", short_id or ""):
        return False
    n = 0
    for s in Session.objects(user_id=oid(str(uid)), id__startswith=short_id):
        if s.id != cur:
            s.delete()
            n += 1
    return bool(n)


def end_other_sessions(uid, current_token: str) -> int:
    cur = hashlib.sha256((current_token or "").encode()).hexdigest()
    return Session.objects(user_id=oid(str(uid)), id__ne=cur).delete()


# ---------------------------------------------------------------- closing the account
def close_account(user: Dict, password: str, confirm: str) -> None:
    """A member closes their own account: they are signed out everywhere and cannot sign in again. Their videos and history are kept,
    and the owner can switch the account back on. (Deleting the data is the owner's decision.)"""
    if user.get("role") == "owner":
        raise ValueError("The owner account cannot be closed.")
    fresh = User.objects(id=user["_id"]).first()
    if not fresh or not auth.verify_password(password or "", fresh.pw_hash):
        raise ValueError("The password is wrong.")
    if (confirm or "").strip().upper() != "CLOSE":
        raise ValueError("Type CLOSE to confirm.")
    auth.set_status(str(user["_id"]), "disabled")
    notes.notify_owner("signup", f"{user.get('name') or user['email']} closed their account", f"{user['email']} can no longer sign in. You can switch the account back on under Users.", "#/users", "info")
