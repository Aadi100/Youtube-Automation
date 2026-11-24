"""Controller (the C of MVC): schedule endpoints."""
from flask import Blueprint

from app.http import register
from app.models import Game, Job, Setting, Video, oid
from app.services import creator_service
from app.services.schedule_service import _clean_times, _tzinfo, get_schedule, schedule_claim, schedule_next
from app.views.serializers import _job_view


def h_schedule(h):
    s = get_schedule(h.uid)
    from datetime import datetime
    s["next"] = {k: schedule_next(s, k) for k in ("shorts", "compilation")}
    s["now"] = datetime.now(_tzinfo(s["timezone"])).isoformat(timespec="minutes")
    h.send_json(200, s)


def h_schedule_put(h):
    d = h.body_json()
    upd = {}
    tzname = str(d.get("timezone") or "").strip()
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tzname)
        except Exception:
            if tzname != "Asia/Karachi":
                return h.send_json(400, {"error": f"Unknown time zone '{tzname}' (example: Asia/Karachi, Europe/London)."})
        upd["timezone"] = tzname
    for k in ("shorts", "compilation"):
        if isinstance(d.get(k), dict):
            times = _clean_times(d[k].get("times", []))
            if d[k].get("enabled", True) and not times:
                return h.send_json(400, {"error": f"{k.title()}: enter at least one time like 06:30, or turn it off."})
            ids = creator_service.clean_ids(h.uid, d[k].get("creators") or [])
            if ids and not creator_service.allowed(h.is_owner()):
                return h.send_json(403, {"error": "The owner has switched off: choosing a creator."})
            upd[k] = {"enabled": bool(d[k].get("enabled", True)), "times": times, "creators": ids}
    if upd:
        Setting.set_fields(f"schedule:{h.uid}", upd, upsert=True)
    h_schedule(h)


def h_schedule_overview(h):
    """Everything the Schedule tab shows: what is running, what comes next (with the game), what happened."""
    from datetime import datetime
    s = get_schedule(h.uid)
    games = Game.list_for(h.uid)
    games_by_id = {g["id"]: g for g in games}
    # the next runs use the game that was used longest ago, so simulate the round-robin slot by slot
    queue = sorted((g for g in games if g.get("enabled", True)), key=lambda g: g.get("last_used_at") or "")
    slots = sorted((iso, k) for k in ("shorts", "compilation") for iso in schedule_next(s, k, 8))
    upcoming = []
    turn = {}
    for iso, k in slots[:10]:
        ids = s[k].get("creators") or []
        if ids and creator_service.allowed(h.is_owner()):       # this kind takes its clips from saved creators in turn
            doc = Setting.find_one(id=f"schedule:{h.uid}") or {}
            order = creator_service.rotation(h.uid, k, ids, int((doc.get("cidx") or {}).get(k, 0) or 0) + turn.get(k, 0))
            turn[k] = turn.get(k, 0) + 1
            if order:
                upcoming.append({"at": iso, "kind": k, "game": None, "creator": order[0]["label"]})
                continue
        g = queue.pop(0) if queue else None
        if g:
            queue.append(g)
        upcoming.append({"at": iso, "kind": k, "game": g["name"] if g else None})
    jobs = Job.find_all(user_id=h.uid, order=("-created_at",), limit=15)
    vids = {str(v["_id"]): v for v in Video.find_all(id__in=[oid(str(j["video_id"])) for j in jobs if j.get("video_id")])}
    views = [_job_view(j, games_by_id, vids, h.is_owner()) for j in jobs]
    last = {k: (datetime.fromtimestamp(float(v)).astimezone().isoformat() if v else None) for k, v in s.get("last", {}).items()}
    h.send_json(200, {"timezone": s["timezone"], "now": datetime.now(_tzinfo(s["timezone"])).isoformat(),
                      "enabled": {k: s[k]["enabled"] for k in ("shorts", "compilation")},
                      "running": next((v for v in views if v["status"] == "running"), None),
                      "upcoming": upcoming, "history": [v for v in views if v["status"] != "running"][:12],
                      "last_trigger": last, "games": [{"name": g["name"], "enabled": g.get("enabled", True)} for g in games]})


def h_schedule_claim(h, kind):
    h.send_json(200, schedule_claim(kind, h.uid))


ROUTES = [
    (r"/api/schedule", "GET", h_schedule),
    (r"/api/schedule/overview", "GET", h_schedule_overview),
    (r"/api/schedule", "PUT", h_schedule_put),
    (r"/api/schedule/claim/(shorts|compilation)", "POST", h_schedule_claim),
]
bp = Blueprint("schedule", __name__)
register(bp, ROUTES)
