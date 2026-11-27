"""Spike alerts: clip while it is hot.

Every few minutes the studio looks at the newest Twitch clips of the games its members cover and writes down how many views each one has. A clip whose views
jump between two looks (and that is still young) is "taking off". Each member who switched spike alerts on is told, once per clip; a member who chose
"make the Short by itself" also gets a Short made through the normal job queue (so the usual checks apply: their tokens, their daily limit for this, their job limit).

Only Twitch is watched: YouTube's search costs 100 quota units per call, so watching it all day would use the whole allowance.
One look at Twitch per game, shared by every member who covers that game. Every alert belongs to one member.
"""
import os
import threading
import time
from datetime import timedelta
from typing import Dict, List, Optional

from app.models import ClipSnap, Game, SpikeAlert, User, now

INTERVAL = int(os.environ.get("SPIKE_INTERVAL") or 600)          # seconds between two looks
MIN_GAP = 480                                                    # a clip is compared with a look at least this many seconds ago
KEEP_SNAPS = 3 * 3600
MAX_CATEGORIES = 12                                              # games watched in one round (Twitch is asked once for each)
MAX_AGE_MIN = 360                                                # only clips younger than this can "take off"
MIN_JUMP = 60                                                    # views gained between two looks, at least ...
JUMP_SHARE = 0.20                                                # ... and at least this share of the views it already had
NEW_RISER_VPH = 600                                              # a very young clip (under 45 minutes) with this many views per hour counts too
ALERTS_PER_HOUR = 5                                              # per member


def _age_minutes(published) -> Optional[float]:
    """Minutes since a clip was made (an ISO time or a unix time); None when it is not known. (Not rounded up to an hour like Trending mode's age.)"""
    try:
        from datetime import datetime, timezone
        t = datetime.fromtimestamp(float(published), tz=timezone.utc) if isinstance(published, (int, float)) else datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 60.0)
    except Exception:
        return None


def detect(row: Dict, prev: Optional[Dict], t_now: float, min_views: int) -> Optional[Dict]:
    """Is this clip taking off? `row` = the clip now ({views, published, ...}), `prev` = an earlier look ({views, t}) or None.
    Returns {"jump", "per_hour", "kind"} or None."""
    views = int(row.get("views") or 0)
    if views < min_views:
        return None
    age_min = _age_minutes(row.get("published"))
    if age_min is not None and age_min > MAX_AGE_MIN:
        return None
    if prev:
        gap = t_now - float(prev["t"])
        jump = views - int(prev["views"])
        if gap >= MIN_GAP and jump >= max(MIN_JUMP, JUMP_SHARE * int(prev["views"])):
            return {"jump": jump, "per_hour": round(jump / (gap / 3600.0)), "kind": "jump"}
        return None
    if age_min is not None and age_min <= 45 and views / max(age_min / 60.0, 0.25) >= NEW_RISER_VPH:
        return {"jump": views, "per_hour": round(views / max(age_min / 60.0, 0.25)), "kind": "new"}
    return None


def watchers() -> Dict[str, List[Dict]]:
    """{twitch category: [{"user_id", "game_id", "mode"}]}: who watches what. Members who left spike alerts off are not in it."""
    from app.engine import clipcfg
    out: Dict[str, List[Dict]] = {}
    for u in User.find_all(status="active"):
        uid = str(u["_id"])
        mode = clipcfg.pref(uid, "spike_mode", "off")
        if mode not in ("alert", "auto"):
            continue
        for g in Game.list_for(uid):
            cat = str(g.get("twitch_category") or "").split("\n")[0].strip()
            if g.get("enabled", True) and cat:
                out.setdefault(cat, []).append({"user_id": uid, "game_id": g["id"], "mode": mode})
    return out


def _fetch(category: str) -> List[Dict]:
    from app.engine import discovery
    return discovery._twitch_candidates_one(category, 6, 20, 5, 60)


def look(category: str, rows: List[Dict], t_now: float, min_of: callable) -> List[Dict]:
    """Write down the views of these clips and return those taking off (each with its 'spike' = detect()'s answer). `min_of(None)` is the smallest views any watcher wants."""
    found = []
    for r in rows:
        prev = ClipSnap.objects(clip_id=r["clip_id"], t__lte=t_now - MIN_GAP).order_by("-t").first()
        sp = detect(r, {"views": prev.views, "t": prev.t} if prev else None, t_now, min_of(None))
        ClipSnap(clip_id=r["clip_id"], category=category, views=int(r.get("views") or 0), t=t_now).save()
        if sp:
            found.append({**r, "spike": sp})
    ClipSnap.objects(t__lt=t_now - KEEP_SNAPS).delete()
    return found


def _auto_today(uid: str) -> int:
    return SpikeAlert.objects(user_id=uid, status__in=["making", "made"], created_at__gte=now() - timedelta(hours=24)).count()


def make_short(uid: str, game_id: str, clip: Dict) -> tuple:
    """Queue a Short for this member that prefers this clip (Trending mode ranks it first). Returns (job id, error)."""
    from app.controllers.job_controller import default_audio
    from app.services import diy_service
    from app.services.queue_service import enqueue
    user = User.find_one(id=__import__("app.models", fromlist=["oid"]).oid(uid))
    if not user:
        return None, "That account is gone."
    if not diy_service.trending_allowed(user.get("role") == "owner"):
        return None, "Trending mode is not switched on for you, and spike alerts use it. Ask the owner."
    params = {"audio_mode": default_audio(uid), "source": "twitch", "game_id": game_id, "hours": 6, "trending": True, "prefer_clip": str(clip["clip_id"])}
    return enqueue("auto-short", params, "spike", uid)


def handle(clip: Dict, category: str, ws: List[Dict]) -> int:
    """Tell every watching member about this clip (once), and make the Short for those who asked. Returns alerts made."""
    from app.engine import clipcfg
    from app.services import notification_service as notes
    made = 0
    for w in ws:
        uid = w["user_id"]
        if int(clip.get("views") or 0) < int(clipcfg.pref(uid, "spike_min_views", 300)):
            continue
        if SpikeAlert.objects(user_id=uid, clip_id=str(clip["clip_id"])).count():
            continue
        if SpikeAlert.objects(user_id=uid, created_at__gte=now() - timedelta(hours=1)).count() >= ALERTS_PER_HOUR:
            continue
        try:
            SpikeAlert(user_id=uid, clip_id=str(clip["clip_id"]), category=category, created_at=now(), status="new").save()
        except Exception:
            continue                                                  # another round told this member a moment ago
        made += 1
        sp = clip["spike"]
        what = f"'{str(clip.get('title') or '')[:60]}' by {clip.get('streamer')} gained {sp['jump']:,} views" + (f" ({sp['per_hour']:,} an hour)" if sp.get("per_hour") else "") + f" in {category}."
        line, status = "", "new"
        if w["mode"] == "auto":
            if _auto_today(uid) >= int(clipcfg.pref(uid, "spike_auto_per_day", 2)):
                line = " Your limit of Shorts made by themselves for today is used up, so it is yours to decide."
            else:
                jid, err = make_short(uid, w["game_id"], clip)
                if jid:
                    status, line = "making", " A Short is being made for you now."
                else:
                    line = f" It could not be made by itself: {err}"
        SpikeAlert.objects(user_id=uid, clip_id=str(clip["clip_id"])).update(set__status=status, set__title=str(clip.get("title") or "")[:120], set__streamer=str(clip.get("streamer") or ""),
                                                                           set__url=str(clip.get("url") or ""), set__views=int(clip.get("views") or 0), set__game_id=w["game_id"], set__per_hour=sp.get("per_hour"))
        notes.notify(uid, "spike", "A clip is taking off", what + line, "#/settings", "success" if status == "making" else "info", key=f"spike-{clip['clip_id']}")
    return made


def round_once(fetch=None, t_now: Optional[float] = None) -> Dict:
    """One look at every watched game. Returns what happened, in numbers."""
    fetch = fetch or _fetch
    t_now = t_now or time.time()
    ws = watchers()
    stats = {"games": 0, "clips": 0, "spikes": 0, "alerts": 0}
    from app.engine import clipcfg
    for cat in list(ws)[:MAX_CATEGORIES]:
        try:
            rows = fetch(cat)
        except Exception as e:
            print(f"[studio] spike look at '{cat}' failed: {type(e).__name__}: {str(e)[:100]}")
            continue
        stats["games"] += 1
        stats["clips"] += len(rows)
        smallest = min(int(clipcfg.pref(w["user_id"], "spike_min_views", 300)) for w in ws[cat])
        for clip in look(cat, rows, t_now, lambda _: smallest):
            stats["spikes"] += 1
            stats["alerts"] += handle(clip, cat, ws[cat])
    return stats


def recent(uid, limit: int = 20) -> List[Dict]:
    out = []
    for a in SpikeAlert.find_all(user_id=str(uid), order=("-created_at",), limit=limit):
        out.append({"id": str(a["_id"]), "clip_id": a.get("clip_id"), "title": a.get("title"), "streamer": a.get("streamer"), "url": a.get("url"), "views": a.get("views"),
                    "per_hour": a.get("per_hour"), "category": a.get("category"), "status": a.get("status"), "created_at": a["created_at"].isoformat() if a.get("created_at") else None})
    return out


def make_now(uid, alert_id: str) -> Dict:
    """The member pressed 'Make a Short now' on an alert."""
    from app.models import oid
    a = SpikeAlert.find_one(id=oid(alert_id)) if len(alert_id) == 24 else None
    if not a or a.get("user_id") != str(uid):
        raise LookupError("not found")
    if a.get("status") in ("making", "made"):
        raise ValueError("A Short was already made or is being made for this clip.")
    jid, err = make_short(str(uid), a.get("game_id") or "auto", {"clip_id": a["clip_id"]})
    if not jid:
        raise ValueError(err)
    SpikeAlert.objects(id=a["_id"]).update(set__status="making")
    return {"job_id": jid}


def _loop() -> None:
    time.sleep(60)
    while True:
        try:
            if watchers():                                            # nobody asked for spike alerts: Twitch is not asked at all
                stats = round_once()
                if stats["spikes"]:
                    print(f"[studio] spike round: {stats}")
        except Exception as e:
            print(f"[studio] spike round failed: {type(e).__name__}: {str(e)[:120]}")
        time.sleep(INTERVAL)


def start() -> None:
    threading.Thread(target=_loop, daemon=True).start()
