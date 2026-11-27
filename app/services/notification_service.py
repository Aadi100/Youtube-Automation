"""Notifications: the bell inside the dashboard, and optional emails.

    notify(user_id, "video_ready", "Your Short is ready", "...", link="#/videos", level="success")

Every member chooses, per kind of message, whether it shows in the app and whether it is also emailed. Nothing here ever raises:
a notification must never break the thing that caused it.
"""
import html
import threading
from datetime import timedelta
from typing import Dict, List, Optional

from app.models import Notification, User, UserPrefs, now, oid

# kind -> (what the member sees in the settings, shown in the app by default, emailed by default, who gets it)
KINDS: Dict[str, tuple] = {
    "video_ready": ("A video is ready for my review", True, False, "all"),
    "video_failed": ("A video could not be made", True, False, "all"),
    "upload_done": ("A video was uploaded to YouTube", True, False, "all"),
    "upload_problem": ("An upload needs my attention", True, True, "all"),
    "youtube": ("My YouTube connection needs attention", True, True, "all"),
    "tokens": ("Tokens added, or my balance is running low", True, False, "all"),
    "schedule": ("A scheduled run was skipped", True, False, "all"),
    "editor": ("An editor export is finished", True, False, "all"),
    "risk": ("A video was held back because it looks like reused content", True, True, "all"),
    "spike": ("A clip is taking off (spike alerts)", True, False, "all"),
    "story": ("A story video is ready", True, False, "all"),
    "account": ("My account and sign-in security", True, True, "all"),
    "signup": ("A new member is waiting for approval", True, True, "owner"),
    "system": ("Server problems (disk, repeated failures, workers)", True, True, "owner"),
}
LEVELS = ("info", "success", "warn", "error")
KEEP_DAYS = 60


def kinds_for(role: str) -> List[str]:
    return [k for k, v in KINDS.items() if v[3] == "all" or (v[3] == "owner" and role == "owner")]


def _pref(uid, kind: str) -> Dict[str, bool]:
    _, app_on, mail_on, _ = KINDS[kind]
    mine = ((UserPrefs.of(uid).get("notif") or {}).get(kind)) or {}
    return {"app": bool(mine.get("app", app_on)), "email": bool(mine.get("email", mail_on))}


def _email(uid: str, title: str, body: str, link: str, kind: str = "") -> None:
    try:
        from app.services import notify_service as mail
        user = User.find_one(id=oid(uid))
        if not user:
            return
        cfg = mail.get_cfg()
        cfg["to"] = UserPrefs.of(uid).get("notify_to") or user["email"]
        if not (cfg["host"] and cfg["from"]):
            return
        url = cfg["base_url"] + "/app" + (link if link.startswith("#") else "")
        from app.services import email_template_service as templates
        subject, text, page = templates.render(kind, title, body, user.get("name") or "", url)      # the owner's template (Settings -> Email templates)
        ok, _msg = mail.send_mail(subject, text, page, None, cfg)
        if ok:                                         # an email that really went out is paid for by the member (never the owner)
            from app.services import token_service as tokens
            tokens.charge_action(uid, "email_send")
    except Exception as e:
        print(f"[notify] email failed: {e}")


def notify(uid, kind: str, title: str, body: str = "", link: str = "", level: str = "info", key: Optional[str] = None) -> Optional[str]:
    """Tell one member something. Returns the notification id (None when it was switched off, or already shown)."""
    try:
        if not uid or kind not in KINDS:
            return None
        uid = str(uid)
        pref = _pref(uid, kind)
        level = level if level in LEVELS else "info"
        nid = None
        if pref["app"]:
            if key:
                same = Notification.objects(user_id=uid, key=key, read=False, created_at__gte=now() - timedelta(hours=24)).first()
                if same:                       # the same unread problem: do not pile up copies
                    return None
            nid = str(Notification(user_id=uid, kind=kind, title=title[:140], body=(body or "")[:400], link=(link or "")[:120], level=level,
                                   key=key, read=False, created_at=now()).save().id)
        if pref["email"]:
            threading.Thread(target=_email, args=(uid, title[:140], body or "", link or "", kind), daemon=True).start()
        return nid
    except Exception as e:
        print(f"[notify] could not notify: {e}")
        return None


def notify_owner(kind: str, title: str, body: str = "", link: str = "", level: str = "info", key: Optional[str] = None) -> Optional[str]:
    try:
        owner = User.find_one(role="owner")
        return notify(str(owner["_id"]), kind, title, body, link, level, key) if owner else None
    except Exception:
        return None


def view(n: Dict) -> Dict:
    return {"id": str(n["_id"]), "kind": n.get("kind"), "title": n.get("title"), "body": n.get("body") or "", "link": n.get("link") or "",
            "level": n.get("level") or "info", "read": bool(n.get("read")), "created_at": n["created_at"].replace(tzinfo=None).isoformat() + "Z" if n.get("created_at") else None}


def unread_count(uid) -> int:
    return Notification.total(user_id=str(uid), read=False)


def latest(uid) -> Optional[Dict]:
    r = Notification.find_all(user_id=str(uid), order=("-created_at",), limit=1)
    return view(r[0]) if r else None


def list_for(uid, unread_only: bool = False, limit: int = 30, skip: int = 0) -> List[Dict]:
    q = {"user_id": str(uid)}
    if unread_only:
        q["read"] = False
    return [view(n) for n in Notification.find_all(order=("-created_at",), limit=max(1, min(100, limit)), skip=max(0, skip), **q)]


def mark_read(uid, ids: Optional[List[str]] = None) -> int:
    q = {"user_id": str(uid), "read": False}
    if ids is not None:
        good = []
        for i in ids[:200]:
            try:
                good.append(oid(i))
            except ValueError:
                pass
        q["id__in"] = good
    return Notification.objects(**q).update(set__read=True)


def delete_one(uid, nid: str) -> bool:
    return bool(Notification.objects(user_id=str(uid), id=oid(nid)).delete())


def clear_read(uid) -> int:
    return Notification.objects(user_id=str(uid), read=True).delete()


def prefs_for(uid, role: str) -> List[Dict]:
    out = []
    for k in kinds_for(role):
        p = _pref(uid, k)
        out.append({"kind": k, "label": KINDS[k][0], "app": p["app"], "email": p["email"]})
    return out


def set_prefs(uid, role: str, data: Dict) -> List[Dict]:
    """data = {kind: {"app": bool, "email": bool}}. Unknown kinds are ignored."""
    allowed = set(kinds_for(role))
    cur = dict(UserPrefs.of(uid).get("notif") or {})
    for k, v in (data or {}).items():
        if k in allowed and isinstance(v, dict):
            old = _pref(uid, k)
            cur[k] = {"app": bool(v.get("app", old["app"])), "email": bool(v.get("email", old["email"]))}
    UserPrefs.set_fields(str(uid), {"notif": cur}, upsert=True)
    return prefs_for(uid, role)
