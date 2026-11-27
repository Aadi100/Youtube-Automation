"""Permission tracker: the creators who allowed clipping, with the date and the proof, kept per member.

A member writes down WHO said yes (or that they asked, or were refused), WHEN, and WHERE the proof is (a link to the message or post, and a short note).
Each member only ever sees and changes their own list. The list is used in three places: Trending mode prefers these creators, the reused-content risk
score is lower for a video made from them, and the Permission page shows what is on record.
"""
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

from app.models import Permission, now, oid

PLATFORMS = ("twitch", "youtube", "kick", "other")
STATUSES = ("allowed", "asked", "declined")
MAX_PER_MEMBER = 500


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def keys_for(platform: Optional[str], creator: Optional[str], channel_url: Optional[str] = None) -> List[str]:
    """Every form a creator can be known by, so a record made from a name matches a clip found from a channel link and the other way round.
    twitch.tv/<login> -> 'twitch:<login>' ; youtube.com/@handle -> 'youtube:@handle' ; /channel/<id> -> 'youtube:<id>' ; a plain name -> '<platform>:<name>' and 'name:<name>'."""
    out = []
    plat = (platform or "").lower()
    name = _flat(creator)
    if name:
        out.append(f"name:{name}")
        if plat in PLATFORMS:
            out.append(f"{plat}:{name}")
    url = str(channel_url or "").strip()
    if url.startswith("http"):
        u = urlparse(url)
        host, parts = (u.hostname or "").lower().replace("www.", ""), [unquote(p) for p in u.path.split("/") if p]
        if host.endswith("twitch.tv") and parts:
            out.append(f"twitch:{parts[0].lower()}")
        elif host.endswith("kick.com") and parts:
            out.append(f"kick:{parts[0].lower()}")
        elif host.endswith("youtube.com") and parts:
            if parts[0].startswith("@"):
                out.append(f"youtube:{parts[0].lower()}")
            elif parts[0] in ("channel", "c", "user") and len(parts) > 1:
                out.append(f"youtube:{parts[1].lower()}")
    return list(dict.fromkeys(out))


def _clean_date(v, required: bool) -> Optional[str]:
    v = str(v or "").strip()
    if not v:
        if required:
            raise ValueError("Write the date the creator said yes (year-month-day).")
        return None
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        raise ValueError("The date must look like 2026-11-27.")
    if d > date.today() + timedelta(days=1):                 # a day of slack: the member's clock may be ahead of the server's
        raise ValueError("That date is in the future.")
    return d.isoformat()


def _check(data: Dict) -> Dict:
    plat = str(data.get("platform") or "twitch").lower()
    if plat not in PLATFORMS:
        raise ValueError("Choose Twitch, YouTube, Kick or Other.")
    creator = " ".join(str(data.get("creator") or "").split())[:80]
    if len(creator) < 2:
        raise ValueError("Write the creator's name.")
    status = str(data.get("status") or "allowed").lower()
    if status not in STATUSES:
        raise ValueError("Status must be Allowed, Asked or Declined.")
    channel = str(data.get("channel_url") or "").strip()
    if channel and not (channel.startswith("https://") and len(channel) <= 300):
        raise ValueError("The channel link must start with https://")
    proof_url = str(data.get("proof_url") or "").strip()
    if proof_url and not (proof_url.startswith("https://") and len(proof_url) <= 400):
        raise ValueError("The proof link must start with https://")
    note = str(data.get("proof_note") or "").strip()[:600]
    if status == "allowed" and not (proof_url or note):
        raise ValueError("Keep proof: add a link to the message or post, or write down what was said and where.")
    granted = _clean_date(data.get("granted_on"), required=(status == "allowed"))
    expires = _clean_date(data.get("expires_on"), required=False) if data.get("expires_on") else None
    if expires and granted and expires < granted:
        raise ValueError("The end date is before the date it was given.")
    keys = keys_for(plat, creator, channel)
    return {"platform": plat, "creator": creator, "status": status, "channel_url": channel or None, "proof_url": proof_url or None, "proof_note": note or None,
            "granted_on": granted, "expires_on": expires, "key": keys[-1] if keys else f"name:{_flat(creator)}", "keys": keys}


def view(d: Dict) -> Dict:
    expired = bool(d.get("expires_on") and d["expires_on"] < date.today().isoformat())
    return {"id": str(d["_id"]), "platform": d.get("platform"), "creator": d.get("creator"), "status": d.get("status"), "channel_url": d.get("channel_url"),
            "proof_url": d.get("proof_url"), "proof_note": d.get("proof_note"), "granted_on": d.get("granted_on"), "expires_on": d.get("expires_on"), "expired": expired,
            "updated_at": d["updated_at"].isoformat() if d.get("updated_at") else None}


def list_for(uid, status: str = "") -> List[Dict]:
    q = {"user_id": str(uid)}
    if status in STATUSES:
        q["status"] = status
    return [view(d) for d in Permission.find_all(order=("-updated_at",), limit=MAX_PER_MEMBER + 5, **q)]


def add(uid, data: Dict) -> Dict:
    c = _check(data)
    if Permission.total(user_id=str(uid)) >= MAX_PER_MEMBER:
        raise ValueError(f"You can keep up to {MAX_PER_MEMBER} creators. Delete old ones first.")
    twin = next((d for d in Permission.find_all(user_id=str(uid)) if set(d.get("keys") or [d.get("key")]) & set(c["keys"]) and d.get("platform") == c["platform"]), None)
    if twin:
        raise ValueError(f"{twin.get('creator')} is already in your list. Open it and change it instead.")
    doc = Permission(user_id=str(uid), created_at=now(), updated_at=now(), **c).save()
    return view(Permission.find_one(id=doc.id))


def update(uid, pid: str, data: Dict) -> Dict:
    try:
        d = Permission.find_one(id=oid(pid))
    except Exception:
        d = None
    if not d or d.get("user_id") != str(uid):
        raise LookupError("not found")
    c = _check({**view(d), **data})
    Permission.objects(id=d["_id"]).update_one(**{f"set__{k}": v for k, v in {**c, "updated_at": now()}.items()})
    return view(Permission.find_one(id=d["_id"]))


def delete(uid, pid: str) -> bool:
    try:
        d = Permission.find_one(id=oid(pid))
    except Exception:
        return False
    if not d or d.get("user_id") != str(uid):
        return False
    Permission.objects(id=d["_id"]).delete()
    return True


def allowed_map(uid) -> Dict[str, Dict]:
    """{creator key: record} of the creators who allowed this member to clip them (not ended). Used by Trending mode and the risk score."""
    out: Dict[str, Dict] = {}
    today = date.today().isoformat()
    for d in Permission.find_all(user_id=str(uid), status="allowed"):
        if d.get("expires_on") and d["expires_on"] < today:
            continue
        for k in (d.get("keys") or [d.get("key")]):
            if k:
                out[k] = d
    return out


def is_permitted(allowed: Dict[str, Dict], platform, creator, channel_url=None) -> bool:
    return any(k in allowed for k in keys_for(platform, creator, channel_url))
