"""YouTube results: what happened to each video after it went up, read from YouTube Analytics (with the member's permission) and kept on the video.

For every uploaded video: views, average view duration, average percentage watched, likes, comments, shares, and "stayed to watch" = views that went past the first
moments divided by all views (YouTube Studio calls the opposite "swiped away"; the Analytics API does not give the swipe-away number itself, so this is the closest
thing it does give). The Learning Lab uses them, so it learns from how long people really watched and not only from how many views a video got.

Needs the member's OK for ONE extra permission (read-only Analytics), asked for separately from the upload permission. Every member's numbers are read with
that member's own login and kept on that member's own videos.
"""
import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

from app.models import Video, YtAccount, now
from app.services import youtube_service as yt

REPORT_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
METRICS = ["views", "engagedViews", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes", "comments", "shares"]
MIN_AGE_DAYS = 1                 # a video needs a day before its numbers mean anything
MAX_AGE_DAYS = 60
REFRESH_HOURS = 6
MAX_PER_RUN = 10                 # videos read per member per run (keeps every member's share small)
_manual: Dict[str, float] = {}   # member -> when they last pressed "Refresh now"


def granted(user_id) -> bool:
    return yt.has_analytics(user_id)


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse(report: Dict) -> Optional[Dict]:
    """One row of a YouTube Analytics answer as plain numbers; None when YouTube has no row for the video yet."""
    rows = report.get("rows") or []
    if not rows:
        return None
    names = [h.get("name") for h in report.get("columnHeaders") or []]
    r = dict(zip(names, rows[0]))
    views = _num(r.get("views"))
    engaged = r.get("engagedViews")
    return {"views": int(views), "engaged": int(_num(engaged)) if engaged is not None else None,
            "stayed": round(min(1.0, max(0.0, _num(engaged) / views)), 3) if (engaged is not None and views > 0) else None,
            "minutes": round(_num(r.get("estimatedMinutesWatched")), 1), "avd": round(_num(r.get("averageViewDuration")), 1),
            "avp": round(_num(r.get("averageViewPercentage")), 1), "likes": int(_num(r.get("likes"))), "comments": int(_num(r.get("comments"))), "shares": int(_num(r.get("shares")))}


class NeedsPermission(Exception):
    pass


def _query(token: str, video_id: str, start: str, end: str, metrics: List[str]) -> Dict:
    r = requests.get(REPORT_URL, params={"ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": ",".join(metrics), "filters": f"video=={video_id}"},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if r.status_code in (401, 403):
        raise NeedsPermission(r.text[:150])
    if r.status_code == 400 and "engagedViews" in metrics:          # a channel or account that does not have that number yet: ask again without it
        return _query(token, video_id, start, end, [m for m in metrics if m != "engagedViews"])
    if r.status_code != 200:
        raise RuntimeError(f"YouTube Analytics said {r.status_code}")
    return r.json()


def fetch_video(user_id, doc: Dict) -> Optional[Dict]:
    """The numbers of one video, or None (YouTube has none yet). Raises NeedsPermission when the member has not allowed Analytics."""
    token = yt.access_token(user_id)
    created = doc.get("uploaded_at") or doc.get("created_at") or now()
    start = (created.date() if hasattr(created, "date") else date.today()) - timedelta(days=1)
    return parse(_query(token, doc["youtube_id"], start.isoformat(), date.today().isoformat(), METRICS))


def sync_user(user_id, limit: int = MAX_PER_RUN, force: bool = False) -> Dict:
    """Read the numbers of this member's recent videos that are due. Returns what happened, in words."""
    uid = str(user_id)
    if not yt.get_account(uid):
        return {"ok": False, "message": "Connect your YouTube channel first (Settings -> YouTube).", "updated": 0}
    if not granted(uid):
        return {"ok": False, "needs_permission": True, "message": "Allow YouTube Analytics first (Settings -> Protection and growth).", "updated": 0}
    cutoff = time.time() - (0 if force else REFRESH_HOURS * 3600)
    lo, hi = now() - timedelta(days=MAX_AGE_DAYS), now() - timedelta(days=MIN_AGE_DAYS)
    due = [v for v in Video.find_all(user_id=uid, status__in=["uploaded", "public"], order=("-created_at",), limit=80)
           if v.get("youtube_id") and lo <= (v.get("created_at") or lo) <= hi and float((v.get("analytics") or {}).get("fetched_at") or 0) < cutoff][:max(1, limit)]
    got = none = 0
    for v in due:
        try:
            data = fetch_video(uid, v)
        except NeedsPermission:
            YtAccount.objects(user_id=uid).update(set__scopes=(yt.get_account(uid) or {}).get("scopes", "").replace(yt.ANALYTICS_SCOPE, "").strip())
            try:
                from app.services import notification_service as notes
                notes.notify(uid, "youtube", "Allow YouTube Analytics again", "YouTube refused to share your results. Allow Analytics again in Settings -> Protection and growth.", "#/settings", "warn", key="analytics-perm")
            except Exception:
                pass
            return {"ok": False, "needs_permission": True, "message": "YouTube refused to share the results. Allow Analytics again.", "updated": got}
        except Exception as e:
            return {"ok": False, "message": f"YouTube did not answer ({type(e).__name__}). Try again later.", "updated": got}
        if data is None:
            none += 1
            Video.update_where(id=v["_id"], fields={"analytics": {**(v.get("analytics") or {}), "fetched_at": time.time(), "empty": True}})
            continue
        Video.update_where(id=v["_id"], fields={"analytics": {**data, "fetched_at": time.time()}})
        got += 1
    return {"ok": True, "updated": got, "empty": none, "checked": len(due),
            "message": f"Updated the results of {got} video(s)." + (f" {none} have no numbers yet." if none else "") if due else "Nothing is due yet: videos need a day on YouTube, and are read again every few hours."}


def manual_sync(user_id) -> Dict:
    """The member pressed 'Refresh now': at most once a minute."""
    uid = str(user_id)
    if time.time() - _manual.get(uid, 0) < 60:
        return {"ok": False, "message": "Wait a minute before refreshing again.", "updated": 0}
    _manual[uid] = time.time()
    return sync_user(uid, force=True)


def sync_all(max_users: int = 5) -> int:
    """The background run: every member who allowed Analytics (and did not switch the learning off) gets their recent videos read. Returns videos updated."""
    from app.engine import clipcfg
    total = 0
    done = 0
    for a in YtAccount.objects(scopes__contains=yt.ANALYTICS_SCOPE):
        uid = str(a.user_id)
        if not clipcfg.pref(uid, "analytics_on", True):
            continue
        try:
            total += int(sync_user(uid).get("updated") or 0)
        except Exception as e:
            print(f"[studio] analytics for a member failed: {type(e).__name__}")
        done += 1
        if done >= max_users:
            break
    return total


def view(v: Dict) -> Optional[Dict]:
    a = v.get("analytics") or {}
    if not a or a.get("empty") or "views" not in a:
        return None
    return {**{k: a.get(k) for k in ("views", "engaged", "stayed", "minutes", "avd", "avp", "likes", "comments", "shares")}, "fetched_at": a.get("fetched_at")}


def results_for(user_id, limit: int = 15) -> Dict:
    vids = [v for v in Video.find_all(user_id=str(user_id), status__in=["uploaded", "public"], order=("-created_at",), limit=80) if v.get("youtube_id")]
    rows = []
    for v in vids:
        a = view(v)
        if a:
            rows.append({"id": str(v["_id"]), "title": v.get("title"), **a})
    n = len(rows)
    avg = (lambda k: round(sum(float(r[k]) for r in rows if r.get(k) is not None) / max(1, sum(1 for r in rows if r.get(k) is not None)), 1)) if rows else None
    return {"granted": granted(user_id), "connected": bool(yt.get_account(user_id)), "videos": rows[:limit], "count": n,
            "average": {"views": avg("views"), "avp": avg("avp"), "stayed": round(float(avg("stayed") or 0) * 100, 1) if any(r.get("stayed") is not None for r in rows) else None} if rows else None}


def perf(v: Dict, age_days: float) -> float:
    """One number for 'how well did this video do', used by the Learning Lab: the log of views per day, moved up by how long people watched and how many stayed.
    Without Analytics it is just the log of views per day (so a mix of videos with and without results still compares)."""
    base = math.log1p(float(v.get("lab_views") or (v.get("analytics") or {}).get("views") or 0) / max(age_days, 2.0))
    a = v.get("analytics") or {}
    if a and not a.get("empty") and a.get("avp") is not None:
        base += 1.2 * (min(1.2, float(a["avp"]) / 100.0) - 0.5)
        if a.get("stayed") is not None:
            base += 0.8 * (float(a["stayed"]) - 0.5)
    return base
