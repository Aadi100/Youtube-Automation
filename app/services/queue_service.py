"""Job runner and queue: start a pipeline run for a member, fair scheduling between members, cancel, heartbeat."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from app.config import BASE_DIR, OUTPUT_DIR
from app.models import Job, User, UserPrefs, now, oid
from app.runtime import KEEP_LOG, MAX_JOBS, RUNNING, SETTINGS, USER_ACTIVE_LIMIT, WAKE, WORKER_ID
from app.services import notify_service as notify
from app.services import storage_service as storage
from app.services import token_service as tokens
from app.services.upload_service import auto_upload
from app.utils.proc_util import NEW_GROUP
from app.utils.proc_util import kill_tree as _kill_tree


def busy() -> bool:
    """True when the whole studio (all workers together) is at capacity."""
    return Job.total(status="running") >= int(os.environ.get("CLUSTER_MAX_JOBS") or MAX_JOBS)


def _mail_failure(source: str, mode: str, err: str, log: list) -> None:
    """Scheduled (n8n) runs have nobody watching: email the failure. Dashboard runs show it on screen."""
    if source != "n8n" or not notify.configured():
        return
    threading.Thread(target=notify.failed_email, daemon=True,
                     args=(f"{mode} job", f"{err}\n\nLast log lines:\n" + "\n".join(log[-8:]))).start()


def _watch(job_id: str, proc, stop: threading.Event) -> None:
    """While a job runs: prove this worker is alive (heartbeat) and stop the job if someone cancelled it from the website."""
    while not stop.wait(2):
        try:
            j = Job.find_one(id=oid(job_id))
            if j and j.get("status") == "cancelled":
                _kill_tree(proc)
                return
            Job.set_fields(oid(job_id), heartbeat=time.time())
        except Exception:
            pass


def run_job(mode: str, params: dict, source: str, job_id: str, uid: str = None) -> str:
    """Run the pipeline (app/engine/pipeline.py) for one member to completion (blocking). The job row already exists (queued -> running)."""
    cmd = [sys.executable, "-u", "-m", "app.engine.pipeline", "--mode", mode,
           "--game", params.get("game_id", "auto"),
           "--audio-mode", params.get("audio_mode", "replace"),
           "--source", params.get("source", "both"),
           *(["--voice", params["voice"]] if params.get("voice") else []),
           "--hours", str(int(params.get("hours", 24))), "--count", str(int(params.get("count", 14))),
           "--target-minutes", str(float(params.get("target_minutes", 8)))]
    if params.get("title"):
        cmd += ["--title", str(params["title"])[:120]]
    if params.get("layout") in ("blur", "split"):
        cmd += ["--layout", params["layout"]]
    prefs = UserPrefs.of(uid)
    if not params.get("voice") and prefs.get("tts_voice"):
        cmd += ["--voice", prefs["tts_voice"]]
    # child must re-read .env itself (dotenv won't override variables inherited from us)
    env = {k: v for k, v in os.environ.items() if k not in SETTINGS}
    manifest = OUTPUT_DIR / "runs" / f"{job_id}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    env.update(GTA6_JOB_ID=job_id, GTA6_USER_ID=str(uid or ""), GTA6_MANIFEST=str(manifest), PYTHONIOENCODING="utf-8")
    if not uid:
        env.pop("GTA6_USER_ID", None)
    log, last_flush = [], 0.0
    stop = threading.Event()
    try:
        proc = subprocess.Popen(cmd, cwd=BASE_DIR, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **NEW_GROUP)
        RUNNING[job_id] = proc
        threading.Thread(target=_watch, args=(job_id, proc, stop), daemon=True).start()
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log.append(line[:400])
                log = log[-KEEP_LOG:]
            if time.time() - last_flush > 1:
                Job.update_fields(job_id, log=log)
                last_flush = time.time()
        rc = proc.wait()
        stop.set()
        cancelled = (Job.find_one(id=oid(job_id)) or {}).get("status") == "cancelled"
        if cancelled:
            Job.update_fields(job_id, log=log, finished_at=now())
        elif rc == 0 and manifest.exists():
            m = json.loads(manifest.read_text(encoding="utf-8"))
            Job.update_fields(job_id, status="done", log=log, video_id=m.get("video_id"), finished_at=now())
        else:
            err = log[-1] if log else f"exit code {rc}"
            Job.update_fields(job_id, status="failed", log=log, finished_at=now(), error=err)
            _mail_failure(source, mode, err, log)
    except Exception as e:
        Job.update_fields(job_id, status="failed", log=log, error=str(e)[:300], finished_at=now())
        _mail_failure(source, mode, str(e)[:300], log)
    finally:
        stop.set()
        shutil.rmtree(BASE_DIR / "temp" / job_id, ignore_errors=True)
    return job_id


def enqueue(mode: str, params: dict, source: str, uid: str):
    """Put a job in the queue. Returns (job id, error). A member can have at most USER_ACTIVE_LIMIT jobs waiting or running."""
    n = Job.total(user_id=str(uid), status__in=["queued", "running"])
    if n >= USER_ACTIVE_LIMIT:
        return None, f"You already have {n} jobs waiting or running. Wait for one to finish."
    user = User.find_one(id=oid(str(uid))) if uid else None
    if user and user.get("role") != "owner":
        full = storage.over_cap(str(uid))
        if full:
            return None, full
    jid = Job.create(mode, params, source, uid=uid, status="queued")
    if user:
        charged, err = tokens.charge_job(user, mode, params.get("source", "both"), jid)
        if err:
            Job.remove_where(id=oid(jid))
            return None, err
        if charged:
            Job.update_fields(jid, tokens=charged)
    WAKE.set()
    return jid, None


def queue_position(jid: str) -> int:
    j = Job.find_one(id=oid(jid))
    if not j or j.get("status") != "queued":
        return 0
    return Job.total(status="queued", created_at__lt=j["created_at"]) + 1


def _pick_next():
    """Fair order: the member with the fewest running jobs goes first, then the oldest request."""
    from collections import Counter
    queued = Job.find_all(status="queued", order=("created_at",), limit=300)
    if not queued:
        return None
    running = Counter(j.get("user_id") for j in Job.find_all(status="running", only=("user_id",)))
    queued.sort(key=lambda j: (running.get(j.get("user_id"), 0), j["created_at"]))
    for j in queued:
        if Job.update_where(id=j["_id"], status="queued", fields={"status": "running", "started_at": now(), "worker": WORKER_ID, "heartbeat": time.time()}):
            return j
    return None


def _execute(j: dict) -> None:
    jid = str(j["_id"])
    try:
        run_job(j["mode"], j["params"], j.get("source", "dashboard"), jid, uid=j.get("user_id"))
        done = Job.find_one(id=j["_id"]) or {}
        # runs started from the dashboard or by a member's schedule upload by themselves (the owner's n8n runs are uploaded by n8n)
        if done.get("status") == "done" and done.get("video_id") and j.get("source") in ("dashboard", "scheduled"):
            auto_upload(str(done["video_id"]))
        if done.get("status") != "done":
            tokens.refund_job(jid)
    except Exception as e:
        print(f"[studio] job {jid} crashed: {e}")
    finally:
        RUNNING.pop(jid, None)
        WAKE.set()


def dispatcher() -> None:
    while True:
        WAKE.wait(5)
        WAKE.clear()
        try:
            while len(RUNNING) < MAX_JOBS:
                j = _pick_next()
                if not j:
                    break
                RUNNING[str(j["_id"])] = None
                threading.Thread(target=_execute, args=(j,), daemon=True).start()
        except Exception as e:
            print(f"[studio] dispatcher error: {e}")
            time.sleep(3)


def cancel_job(jid: str) -> bool:
    j = Job.find_one(id=oid(jid))
    if not j or j.get("status") not in ("queued", "running"):
        return False
    Job.update_fields(jid, status="cancelled", error="cancelled by user", finished_at=now())
    if j["status"] == "running":
        _kill_tree(RUNNING.get(jid))   # same process; another worker's watcher notices the 'cancelled' status within 2 seconds
    else:
        tokens.refund_job(jid)   # it never started: full refund
    return True
