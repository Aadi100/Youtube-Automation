"""The automatic schedule: when each member's Shorts and compilations are due."""
import json
import re
import time
from datetime import timedelta

from mongoengine import Q

from app.controllers.job_controller import default_audio
from app.models import Game, Job, Setting, System, User, oid
from app.runtime import SCHED_CATCHUP_MIN, SCHED_DEFAULT, USER_ACTIVE_LIMIT, WORKER_ID
from app.services import auth_service as auth
from app.services import token_service as tokens
from app.services import youtube_service as youtube_api
from app.services.queue_service import busy, enqueue


def _tzinfo(name):
    from datetime import timezone as dtz
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return dtz(timedelta(hours=5), "PKT") if name == "Asia/Karachi" else dtz.utc


def _clean_times(raw):
    items = raw if isinstance(raw, list) else re.split(r"[,\s;]+", str(raw or ""))
    out = set()
    for t in items:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(t).strip())
        if m and int(m[1]) < 24 and int(m[2]) < 60:
            out.add(f"{int(m[1]):02d}:{m[2]}")
    return sorted(out)[:24]


def get_schedule(uid=None) -> dict:
    doc = Setting.find_one(id=f"schedule:{uid}" if uid else "schedule") or {}
    s = json.loads(json.dumps(SCHED_DEFAULT))
    if not doc and uid and uid != auth.owner_id():   # a new member starts with automation OFF until they choose their times
        s["shorts"]["enabled"] = s["compilation"]["enabled"] = False
    if doc.get("timezone"):
        s["timezone"] = doc["timezone"]
    for k in ("shorts", "compilation"):
        if isinstance(doc.get(k), dict):
            s[k]["enabled"] = bool(doc[k].get("enabled", True))
            s[k]["times"] = _clean_times(doc[k].get("times", s[k]["times"]))
    s["last"] = doc.get("last", {})
    return s


def _slot(day, hhmm, tz):
    from datetime import datetime
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=tz)


def schedule_next(sched, kind, n=3):
    from datetime import datetime
    tz = _tzinfo(sched["timezone"])
    now = datetime.now(tz)
    out = []
    for d in range(0, 4):
        day = (now + timedelta(days=d)).date()
        for t in sched[kind]["times"]:
            dt = _slot(day, t, tz)
            if dt > now:
                out.append(dt.isoformat(timespec="minutes"))
    return out[:n]


def schedule_due(kind, uid=None, offset_min: int = 0):
    """(schedule, slot) when a slot of this kind has arrived and was not run yet, else (schedule, None)."""
    from datetime import datetime
    sched = get_schedule(uid)
    cfg = sched[kind]
    if not cfg["enabled"] or not cfg["times"]:
        return sched, None
    tz = _tzinfo(sched["timezone"])
    now = datetime.now(tz)
    last = float(sched["last"].get(kind, 0) or 0)
    for d in (0, -1):
        day = (now + timedelta(days=d)).date()
        for t in cfg["times"]:
            dt = _slot(day, t, tz) + timedelta(minutes=offset_min)
            if dt <= now < dt + timedelta(minutes=SCHED_CATCHUP_MIN + offset_min) and last < dt.timestamp():
                return sched, dt
    return sched, None


def schedule_claim(kind, uid=None) -> dict:
    """n8n (the owner's legacy automation): True (once) when a slot has arrived and nothing is rendering."""
    if uid and youtube_api.get_account(uid):   # the owner connected their own YouTube: the server scheduler runs it now
        return {"run": False, "reason": "handled by the server scheduler"}
    sched, dt = schedule_due(kind, uid)
    if not dt:
        return {"run": False, "reason": "disabled" if not sched[kind]["enabled"] else "not due"}
    if busy():
        return {"run": False, "reason": "busy"}
    Setting.set_fields(f"schedule:{uid}" if uid else "schedule", {f"last.{kind}": time.time()}, upsert=True)
    return {"run": True, "slot": dt.isoformat(timespec="minutes")}


def _offset(uid: str) -> int:
    """Spread members over the first 20 minutes of every slot so thousands of members do not all start at the same second."""
    import hashlib
    return 0 if uid == auth.owner_id() else int(hashlib.md5(uid.encode()).hexdigest(), 16) % 20


def scheduler() -> None:
    while True:
        time.sleep(30)
        try:
            if not System.acquire_lease("scheduler", WORKER_ID, 90):   # several workers: only one schedules
                continue
            for doc in Setting.find_all(id__regex="^schedule:"):
                uid = doc["_id"].split(":", 1)[1]
                u = User.find_one(id=oid(uid))
                if not u or u.get("status") != "active" or not youtube_api.get_account(uid):
                    continue
                for kind in ("shorts", "compilation"):
                    sched, dt = schedule_due(kind, uid, _offset(uid))
                    if not dt:
                        continue
                    mode = "auto-short" if kind == "shorts" else "auto-compilation"
                    params = {"audio_mode": default_audio(uid), "source": "all", "game_id": "auto"}
                    if kind == "compilation":
                        params.update(count=14, target_minutes=8)
                    if not Game.list_for(uid) or not any(g.get("enabled", True) for g in Game.list_for(uid)):
                        continue
                    if u.get("role") != "owner" and tokens.balance(uid) < tokens.cost(mode, params["source"]):
                        continue   # not enough tokens: wait, the slot stays open for the catch-up window
                    if Job.total(user_id=uid, status__in=["queued", "running"]) >= USER_ACTIVE_LIMIT:
                        continue
                    claimed = Setting.update_where(Q(__raw__={"$or": [{f"last.{kind}": {"$exists": False}}, {f"last.{kind}": {"$lt": dt.timestamp()}}]}),
                                                   id=f"schedule:{uid}", fields={f"last.{kind}": time.time()})
                    if not claimed:   # another instance took this slot a moment ago
                        continue
                    jid, err = enqueue(mode, params, "scheduled", uid)
                    print(f"[studio] scheduled {kind} for {u['email']}: {'job ' + jid if jid else err}")
        except Exception as e:
            print(f"[studio] scheduler error: {e}")
