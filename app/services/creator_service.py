"""Favourite creators: a member saves the Twitch / YouTube creators they like once, then picks them on the Create page or
lets a schedule take clips from them in turn.

Stored in the member's preferences (`user_prefs.creators`). A saved creator is {id, platform, name, label}: `name` is the Twitch login or
the YouTube channel page (what discovery.parse_creator understood), `label` is what the member sees.
"""
import hashlib
from typing import Dict, List, Optional

from app.engine import discovery
from app.models import Setting, UserPrefs
from app.services import diy_service

MAX_SAVED = 20


def allowed(is_owner: bool) -> bool:
    """Members may use creators only when the owner switched it on."""
    return bool(is_owner or diy_service.flags()["pick_creator"])


def _id(platform: str, name: str) -> str:
    return hashlib.md5(f"{platform}:{name}".lower().encode()).hexdigest()[:10]


def list_for(uid) -> List[Dict]:
    return [c for c in (UserPrefs.of(uid).get("creators") or []) if isinstance(c, dict) and c.get("id")]


def add(uid, platform: str, text: str, label: str = "") -> Dict:
    """Save a creator (nothing is looked up online here: the Check button does that). Raises ValueError with a plain message."""
    plat, ident = discovery.parse_creator(platform, text)
    saved = list_for(uid)
    cid = _id(plat, ident)
    if any(c["id"] == cid for c in saved):
        raise ValueError("That creator is already in your list.")
    if len(saved) >= MAX_SAVED:
        raise ValueError(f"You can save up to {MAX_SAVED} creators. Remove one first.")
    nice = " ".join(str(label or "").split())[:60] or (ident if plat == "twitch" else ident.rsplit("/", 1)[-1])
    item = {"id": cid, "platform": plat, "name": ident, "label": nice}
    UserPrefs.set_fields(str(uid), {"creators": saved + [item]}, upsert=True)
    return item


def remove(uid, cid: str) -> bool:
    saved = list_for(uid)
    keep = [c for c in saved if c["id"] != cid]
    if len(keep) == len(saved):
        return False
    UserPrefs.set_fields(str(uid), {"creators": keep}, upsert=True)
    for kind in ("shorts", "compilation"):     # a schedule must not keep pointing at a removed creator
        sc = Setting.find_one(id=f"schedule:{uid}") or {}
        ids = (sc.get(kind) or {}).get("creators") or []
        if cid in ids:
            Setting.set_fields(f"schedule:{uid}", {f"{kind}.creators": [i for i in ids if i != cid]}, upsert=True)
    return True


def clean_ids(uid, ids) -> List[str]:
    """Keep only ids that really are in the member's list, in the order given, no repeats."""
    have = {c["id"] for c in list_for(uid)}
    out: List[str] = []
    for i in ids if isinstance(ids, list) else []:
        if str(i) in have and str(i) not in out:
            out.append(str(i))
    return out[:MAX_SAVED]


def rotation(uid, kind: str, ids: List[str], counter: int) -> List[Dict]:
    """The creators of a schedule in the order they will be used, starting with the one that is next."""
    by_id = {c["id"]: c for c in list_for(uid)}
    order = [by_id[i] for i in ids if i in by_id]
    if not order:
        return []
    k = counter % len(order)
    return order[k:] + order[:k]


def next_for_schedule(uid, kind: str, sched: Dict, is_owner: bool) -> Optional[Dict]:
    """The creator the next scheduled run of this kind takes clips from, as {"platform","name"} (None: search by game as usual).
    Moves the turn on, so every run uses the next creator in the list."""
    if not allowed(is_owner):
        return None
    ids = (sched.get(kind) or {}).get("creators") or []
    doc = Setting.find_one(id=f"schedule:{uid}") or {}
    counter = int((doc.get("cidx") or {}).get(kind, 0) or 0)
    order = rotation(uid, kind, ids, counter)
    if not order:
        return None
    Setting.set_fields(f"schedule:{uid}", {f"cidx.{kind}": counter + 1}, upsert=True)
    c = order[0]
    return {"platform": c["platform"], "name": c["name"], "label": c["label"]}
