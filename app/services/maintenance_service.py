"""Background upkeep: worker heartbeat, alerts to the owner, cleanup, and the start-up of the background threads."""
import os
import sys
import threading
import time
from datetime import timedelta

from app.models import Game, Job, System, User, UserPrefs, Video, create_indexes, migrate_legacy, now, ping
from app.runtime import MAX_JOBS, ROLE, RUNNING, WORKER_ID
from app.services import auth_service as auth
from app.services import notify_service as notify
from app.services import storage_service as storage
from app.services import token_service as tokens
from app.services.queue_service import dispatcher
from app.services.schedule_service import scheduler
from app.services.upload_service import _owners_video, auto_upload, requeue_stuck_uploads, uploader
from app.utils.envfile import setup_code, studio_secret


# ------------------------------------------------- maintenance (one worker at a time holds the lease)
def _alert(key: str, subject: str, text: str) -> None:
    d = System.find_one(id="alerts") or {}
    if time.time() - float((d.get("sent") or {}).get(key, 0)) < 6 * 3600:   # at most one email per problem every 6 hours
        return
    System.set_fields("alerts", {f"sent.{key}": time.time()}, upsert=True)
    print(f"[studio] ALERT {key}: {text}")
    from app.services import notification_service as notes
    notes.notify_owner("system", f"Problem: {subject}", text, "#/users", "warn", key=f"sys-{key}")
    owner = User.find_one(role="owner")
    if owner and notify.configured():
        cfg = notify.get_cfg()
        cfg["to"] = UserPrefs.of(owner["_id"]).get("notify_to") or cfg["to"] or owner["email"]
        notify.send_mail(f"Clip Studio problem: {subject}", text, None, None, cfg)


def _check_alerts() -> None:
    dsk = storage.disk()
    if dsk["free_pct"] < 10:
        _alert("disk", "disk almost full", f"Only {dsk['free_pct']}% of the disk is free ({dsk['free_gb']} GB). Old files are cleaned automatically, but you may need a bigger disk.")
    since = now() - timedelta(hours=1)
    failed = Job.total(status="failed", finished_at__gte=since)
    if failed >= 20:
        _alert("failures", "many failed videos", f"{failed} video jobs failed in the last hour. Check the server log and the API keys.")
    old = Job.find_one(status="queued", created_at__lt=now() - timedelta(minutes=10))
    alive = System.total(id__regex="^worker:", t__gt=time.time() - 60)
    if old and not alive:
        _alert("workers", "no worker is running", "Videos are waiting in the queue but no render worker has reported in for a while.")


def reap_stale_scans(hours: int = 3) -> int:
    """A clip-finder scan, reaction scan or research that has said 'running' for hours lost its process (a restart, a crash): mark it as stopped,
    so it does not block the next one forever ('A scan is already running')."""
    from app.models import ResearchRun, RxScan, Scan
    cutoff = now() - timedelta(hours=hours)
    n = 0
    for M in (Scan, RxScan, ResearchRun):
        n += M.objects(status="running", created_at__lt=cutoff).update(set__status="error", set__message="Stopped: the server restarted or this took too long. Start it again.")
    return n


def maintenance() -> None:
    last = {"clean": 0.0, "alert": 0.0, "scans": 0.0, "storage": 0.0}
    first = True
    while True:
        if not first:
            time.sleep(15)
        first = False   # report in right away at start-up, then every 15 seconds
        try:
            System.set_fields(f"worker:{WORKER_ID}", t=time.time(), running=len(RUNNING), max=MAX_JOBS, role=ROLE, upsert=True)
            if not System.acquire_lease("maintenance", WORKER_ID, 60):
                continue
            try:
                from app.services.upload_service import repush_due
                repush_due()
            except Exception as e:
                print(f"[studio] thumbnail check error: {e}")
            stuck = requeue_stuck_uploads()
            if stuck:
                print(f"[studio] {stuck} upload(s) were interrupted by a restart and are back in the queue")
            for jid in Job.reap_stale():
                tokens.refund_job(jid)
                print(f"[studio] job {jid} lost its worker: marked failed and refunded")
            if time.time() - last["scans"] > 300:
                last["scans"] = time.time()
                lost = reap_stale_scans()
                if lost:
                    print(f"[studio] {lost} scan(s) had lost their process: marked as stopped")
            if time.time() - last["clean"] > 1800:
                last["clean"] = time.time()
                st = storage.cleanup()
                if st["videos_cleaned"] or st["inputs_removed"] or st["temp_removed"]:
                    print(f"[studio] cleanup: {st}")
            if time.time() - last["alert"] > 300:
                last["alert"] = time.time()
                _check_alerts()
            if time.time() - last["storage"] > 3600:
                last["storage"] = time.time()
                billed = storage.bill_extra_storage()
                if billed:
                    print(f"[studio] extra storage charged to {billed} member(s)")
        except Exception as e:
            print(f"[studio] maintenance error: {e}")


def boot() -> None:
    p = ping()
    if not p["ok"]:
        sys.exit(f"MongoDB not reachable: {p['error']}\nStart MongoDB or set MONGODB_URI in .env")
    create_indexes()
    auth.ensure_indexes()
    Game.ensure_default()
    studio_secret()  # makes sure the n8n webhook secret exists in .env
    if auth.user_count():
        migrate_legacy(auth.owner_id())
    elif ROLE in ("web", "all"):
        print(f"[studio] No accounts yet. Open the dashboard and create the OWNER account. (From another computer you also need the setup code: {setup_code()})")
    if ROLE in ("worker", "all"):
        stale = Job.fail_stale(WORKER_ID)   # only this worker's own jobs from before the restart
        if stale:
            print(f"[studio] marked {stale} interrupted job(s) as failed")
        for j in Job.find_all(status="failed", error__in=["worker restarted", "worker lost"], tokens__gt=0, refunded__ne=True):
            tokens.refund_job(str(j["_id"]))
        for fn in (dispatcher, scheduler, maintenance):
            threading.Thread(target=fn, daemon=True).start()
        for _ in range(max(1, int(os.environ.get("UPLOAD_THREADS") or 2))):
            threading.Thread(target=uploader, daemon=True).start()

        def _upload_backlog():  # rendered videos that never reached YouTube (e.g. made while n8n was off) go up now
            time.sleep(25)
            for d in Video.find_all(status="rendered", youtube_id=None, upload_status__exists=False, order=("created_at",)):
                if _owners_video(d):   # members' videos wait until they connect their own YouTube
                    auto_upload(str(d["_id"]))
        threading.Thread(target=_upload_backlog, daemon=True).start()
        print(f"[studio] worker '{WORKER_ID}' ready: up to {MAX_JOBS} video(s) at a time")
    print(f"[studio] role: {ROLE}   (MongoDB {p['version']}, db '{p['database']}')")
