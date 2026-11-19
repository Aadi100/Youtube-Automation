"""'What to clip' settings, edited on the dashboard (Settings -> What to clip) and read by every part of the clipper.

Stored in MongoDB (collection `settings`, document "clipping") so changes apply to the very next run - no restart.
The moment types, your own ideas and the 'never clip' list are written into the instructions the AI receives
(DeepSeek / Gemini), so they steer which moments it picks and how it scores them.
"""
import os
from typing import Dict, List, Optional

# id, name, what it means (this wording goes to the AI), on by default
TYPES = [
    ("funny", "Funny moments & fails", "laugh-out-loud moments, awkward fails, chaotic mistakes and jokes that land", True),
    ("hype", "Hype & clutch plays", "big wins, comebacks, perfect plays and 'no way' moments", True),
    ("shock", "Shocking & surprising", "sudden twists, unexpected events, jump scares and disbelief", True),
    ("emotion", "Emotional reactions", "rage, joy, screaming, tears and speechless reactions", True),
    ("conflict", "Competition & conflict", "rivalries, arguments, trash talk and intense duels", True),
    ("quotes", "Quotable one-liners", "memorable lines viewers will repeat or comment on", True),
    ("chaos", "Chaos & destruction", "explosions, police chases, crashes and over-the-top mayhem", True),
    ("skill", "Impressive skill", "tricks, outplays, great aim, driving or speedrun tech", False),
    ("glitch", "Glitches & bugs", "funny physics, broken AI and unexpected game bugs", False),
    ("story", "Story & reveals", "plot twists, secrets and first reactions to big reveals", False),
    ("news", "Release news & first impressions", "launch reactions, first looks and trailer breakdowns", False),
]
BASE_LOOK = "a strong hook in the first 3 seconds and a clear payoff"
BASE_AVOID = ("intros, waiting, menus, long explanations and ads; ANY sexual, nude or suggestive material; hate; graphic gore")

DEFAULT: Dict = {
    "types": {t[0]: t[3] for t in TYPES},
    "custom": [],            # your own ideas, one per line
    "avoid": [],             # things never to clip, one per line
    "clip_seconds": 45,      # length of a clip cut from a long video (live clips are scaled to match)
    "min_score": 60,         # AI score a moment from a long video needs (live moments need this minus 20)
    "live_sensitivity": "normal",   # strict | normal | loose: how big a loudness / chat spike must be
    "moments_per_video": 4,  # best moments taken from one long video (the extras go to the clip bank)
    "bank_days": 4,          # how long a banked moment is kept before it expires
}


def _clean_lines(v, limit: int = 12, width: int = 140) -> List[str]:
    items = v if isinstance(v, list) else str(v or "").splitlines()
    out = []
    for x in items:
        x = " ".join(str(x).split())[:width]
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out[:limit]


def _doc_id(uid: Optional[str] = None) -> str:
    u = uid or os.environ.get("GTA6_USER_ID")
    return f"clipping:{u}" if u else "clipping"


def load(uid: Optional[str] = None) -> Dict:
    cfg = {**DEFAULT, "types": dict(DEFAULT["types"])}
    try:
        from app.models import Setting
        doc = Setting.find_one(id=_doc_id(uid)) or {}
        for k in ("custom", "avoid"):
            if k in doc:
                cfg[k] = _clean_lines(doc[k])
        for k, lo, hi in (("clip_seconds", 20, 58), ("min_score", 30, 95), ("moments_per_video", 1, 8), ("bank_days", 1, 30)):
            if k in doc:
                try:
                    cfg[k] = max(lo, min(hi, int(doc[k])))
                except (TypeError, ValueError):
                    pass
        if doc.get("live_sensitivity") in ("strict", "normal", "loose"):
            cfg["live_sensitivity"] = doc["live_sensitivity"]
        if isinstance(doc.get("types"), dict):
            for tid in cfg["types"]:
                if tid in doc["types"]:
                    cfg["types"][tid] = bool(doc["types"][tid])
    except Exception:
        pass
    return cfg


def save(data: Dict, uid: Optional[str] = None) -> Dict:
    cur = load(uid)
    upd: Dict = {}
    if isinstance(data.get("types"), dict):
        upd["types"] = {tid: bool(data["types"].get(tid, cur["types"][tid])) for tid in cur["types"]}
    for k in ("custom", "avoid"):
        if k in data:
            upd[k] = _clean_lines(data[k])
    for k, lo, hi in (("clip_seconds", 20, 58), ("min_score", 30, 95), ("moments_per_video", 1, 8), ("bank_days", 1, 30)):
        if k in data:
            upd[k] = max(lo, min(hi, int(data[k])))
    if data.get("live_sensitivity") in ("strict", "normal", "loose"):
        upd["live_sensitivity"] = data["live_sensitivity"]
    if upd:
        from app.models import Setting
        Setting.set_fields(_doc_id(uid), upd, upsert=True)
    return load(uid)


def criteria_text(cfg: Optional[Dict] = None, uid: Optional[str] = None) -> str:
    """The 'what to look for / what to avoid' paragraph that goes into every AI prompt."""
    cfg = cfg or load(uid)
    on = [t for t in TYPES if cfg["types"].get(t[0])]
    look = "; ".join(f"{t[1].lower()} ({t[2]})" for t in on) or "the most entertaining moments"
    text = f"Look for {BASE_LOOK}, especially these kinds of moments: {look}."
    if cfg["custom"]:
        text += " The channel owner also specifically wants: " + "; ".join(cfg["custom"]) + "."
    text += f" Avoid: {BASE_AVOID}"
    if cfg["avoid"]:
        text += "; and NEVER pick: " + "; ".join(cfg["avoid"])
    return text + "."


def span(cfg: Optional[Dict] = None) -> tuple:
    """(seconds before the peak, seconds after) for a live clip, scaled to clip_seconds."""
    total = (cfg or load())["clip_seconds"]
    before = round(total * 0.74)
    return before, total - before


def live_factor(cfg: Optional[Dict] = None) -> float:
    return {"strict": 1.35, "normal": 1.0, "loose": 0.7}[(cfg or load())["live_sensitivity"]]
