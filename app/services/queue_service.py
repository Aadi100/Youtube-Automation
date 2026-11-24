"""Job runner and queue: start a pipeline run for a member, fair scheduling between members, cancel, heartbeat."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from app.config import BASE_DIR, OUTPUT_DIR
from app.models import Video, Job, User, UserPrefs, now, oid
from app.runtime import KEEP_LOG, MAX_JOBS, RUNNING, SETTINGS, USER_ACTIVE_LIMIT, WAKE, WORKER_ID
from app.services import notification_service as notes
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
    if params.get("video_id"):             # "make it again with different audio": which video
        cmd += ["--video-id", str(params["video_id"])]
    diy = params.get("diy") or {}          # the member's do-it-yourself choices (already checked against the owner's switches)
    if diy.get("own_url"):
        cmd += ["--url", diy["own_url"], "--start", str(float(diy["own_start"])), "--end", str(float(diy["own_end"]))]
    if diy.get("creator"):                 # only clips from this creator (Twitch name or YouTube channel)
        cmd += ["--creator", str(diy["creator"]["name"]), "--creator-platform", str(diy["creator"]["platform"])]
    diy_env = {}
    if diy.get("own_file"):                # a moment the member chose in the clip finder (the file is made by the server, never sent by the browser)
        cmd += ["--clip-file", str(diy["own_file"])]
        diy_env["CLIP_META"] = json.dumps(diy.get("own_meta") or {})
    if params.get("want"):                  # what this video should be about; the run's AI prompts and search follow it (see engine/clipcfg.py)
        from app.engine import clipcfg
        w = clipcfg.clean_want(params["want"])
        if w:
            diy_env["CLIP_WANT"] = json.dumps(w)
    if diy.get("ai_text") in ("budget", "balanced", "quality"):
        diy_env["LLM_SPLIT"] = {"budget": "deepseek", "balanced": "balanced", "quality": "gemini"}[diy["ai_text"]]
    elif diy.get("ai_text") == "off":
        diy_env["LLM_DISABLED"] = "1"
    for key, var in (("own_title", "DIY_TITLE"), ("own_description", "DIY_DESCRIPTION"), ("own_tags", "DIY_TAGS"), ("own_commentary", "DIY_COMMENTARY")):
        if diy.get(key):
            diy_env[var] = str(diy[key])
    if diy.get("thumbnail") == "frame":
        diy_env["AI_THUMBNAILS"] = "off"
    if params.get("thumb_pictures") in (1, 3):
        diy_env["THUMB_PICTURES"] = str(params["thumb_pictures"])
    try:                                    # the thumbnail level, never above what the member may use right now (the owner may have changed the rules since they chose)
        from app.services import thumbnail_service
        u = User.find_one(id=oid(str(uid))) if uid else None
        diy_env["THUMB_TIER"] = thumbnail_service.effective_tier(params.get("thumb_tier"), uid, bool(u and u.get("role") == "owner") or not uid) if uid else "free"
    except Exception:
        diy_env["THUMB_TIER"] = "free"
    # child must re-read .env itself (dotenv won't override variables inherited from us)
    env = {k: v for k, v in os.environ.items() if k not in SETTINGS}
    manifest = OUTPUT_DIR / "runs" / f"{job_id}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    env.update(CLIPSTUDIO_JOB_ID=job_id, CLIPSTUDIO_USER_ID=str(uid or ""), CLIPSTUDIO_MANIFEST=str(manifest), PYTHONIOENCODING="utf-8", **diy_env)
    if not uid:
        env.pop("CLIPSTUDIO_USER_ID", None)
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


def _notify_job(j: dict, done: dict) -> None:
    """Tell the member in the bell that their video is ready, or why it could not be made."""
    try:
        uid = j.get("user_id")
        if done.get("status") == "done" and done.get("video_id"):
            v = Video.find_one(id=oid(str(done["video_id"]))) or {}
            holding = v.get("upload_status") == "hold"
            notes.notify(uid, "video_ready", "Your video is ready", f"{v.get('title') or 'A new video'}" + (" is waiting for you to check it." if holding else " is being uploaded to YouTube as Unlisted."),
                         "#/videos", "success")
        elif done.get("status") == "failed":
            from app.views.progress import friendly_error
            notes.notify(uid, "video_failed", "A video could not be made", friendly_error(done.get("error")) or "Something went wrong. Nothing was charged.", "#/create", "error")
    except Exception as e:
        print(f"[studio] could not notify: {e}")


def _execute(j: dict) -> None:
    jid = str(j["_id"])
    try:
        run_job(j["mode"], j["params"], j.get("source", "dashboard"), jid, uid=j.get("user_id"))
        done = Job.find_one(id=j["_id"]) or {}
        if done.get("status") == "done":
            tokens.settle_job(jid)      # the member pays exactly what the video used; the unused part of the reserve goes back
        else:
            tokens.refund_job(jid)      # failed or cancelled: nothing is charged
        # runs started from the dashboard or by a member's schedule upload by themselves (the owner's n8n runs are uploaded by n8n),
        # unless the member asked to check the video first (then they choose the audio and upload it themselves)
        if done.get("status") == "done" and done.get("video_id") and j.get("source") in ("dashboard", "scheduled"):
            after = (j.get("params") or {}).get("after") or ("hold" if UserPrefs.of(j.get("user_id")).get("hold_uploads") else "auto")
            if after == "hold":
                Video.update_where(id=oid(str(done["video_id"])), fields={"upload_status": "hold"})
            else:
                auto_upload(str(done["video_id"]))
        elif done.get("status") == "done" and done.get("video_id") and j.get("source") not in ("n8n", "remix"):
            Video.update_where(id=oid(str(done["video_id"])), fields={"upload_status": "hold"})   # a test or command-line run: never uploaded by itself
        _notify_job(j, done)
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
