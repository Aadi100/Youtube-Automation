"""Controller (the C of MVC): job endpoints."""
import json
import re
import time

from flask import Blueprint

from app.config import OUTPUT_DIR
from app.http import register
from app.models import Game, Job, UserPrefs, clean, oid
from app.runtime import AUDIO, MODES
from app.services.queue_service import cancel_job, enqueue, queue_position
from app.utils.envfile import read_env


def h_jobs(h):
    docs = Job.find_all(user_id=h.uid, order=("-created_at",), limit=60, slice_={"log": -3})
    h.send_json(200, [clean(x) | ({"position": queue_position(str(x["_id"]))} if x.get("status") == "queued" else {}) for x in docs])


def h_job(h, jid):
    doc = Job.find_one(id=oid(jid))
    if doc and doc.get("user_id") != h.uid and not h.is_owner():
        doc = None
    h.send_json(200 if doc else 404, clean(doc) if doc else {"error": "not found"})


def default_audio(uid=None) -> str:
    """The member's audio choice (Settings -> My preferences), else the server default: replace | bed | original."""
    v = (UserPrefs.of(uid).get("default_audio") or read_env().get("DEFAULT_AUDIO_MODE") or "replace").strip().lower()
    return v if v in AUDIO else "replace"


def _check_params(d: dict, uid=None) -> tuple:
    mode, audio = d.get("mode"), d.get("audio_mode")
    if audio in (None, "", "default"):
        audio = default_audio(uid)
    if mode not in MODES or audio not in AUDIO:
        raise ValueError(f"mode must be one of {sorted(MODES)}, audio_mode one of {sorted(AUDIO)}")
    source = d.get("source", "both")
    if source not in ("twitch", "youtube", "both", "live", "all"):
        raise ValueError("source must be twitch, youtube, both, live or all")
    game_id = str(d.get("game_id") or "auto")
    if not re.fullmatch(r"[a-z0-9-]{1,40}", game_id):
        raise ValueError("bad game_id")
    if game_id != "auto" and uid and not Game.get_for(game_id, uid):
        raise ValueError("That game is not in your list.")
    params = {"audio_mode": audio, "source": source, "game_id": game_id}
    if d.get("voice") and d["voice"] != "default":
        if not re.fullmatch(r"(random|en-[A-Za-z]{2}-\w+Neural)", str(d["voice"])):
            raise ValueError("bad voice")
        params["voice"] = d["voice"]
    for k, cast, lo, hi in (("hours", int, 1, 168), ("count", int, 1, 40), ("target_minutes", float, 0.1, 30)):
        if k in d:
            v = cast(d[k])
            if not lo <= v <= hi:
                raise ValueError(f"{k} must be {lo}-{hi}")
            params[k] = v
    if d.get("title"):
        params["title"] = str(d["title"])[:120]
    if d.get("layout") in ("blur", "split"):
        params["layout"] = d["layout"]
    return mode, params


def h_job_start(h):
    mode, params = _check_params(h.body_json(), h.uid)
    jid, err = enqueue(mode, params, "dashboard", h.uid)
    if jid is None:
        return h.send_json(429, {"error": err})
    h.send_json(202, {"job_id": jid, "position": queue_position(jid)})


def h_job_cancel(h, jid):
    j = Job.find_one(id=oid(jid))
    if not j or (j.get("user_id") != h.uid and not h.is_owner()):
        return h.send_json(404, {"error": "not found"})
    h.send_json(200, {"cancelled": cancel_job(jid)})


def h_run_sync(h):  # n8n (owner's scheduled runs): waits in the queue, blocks until the render is finished, returns the manifest
    mode, params = _check_params(h.body_json(), h.uid)
    params["audio_mode"] = default_audio(h.uid)   # scheduled runs follow the owner's choice
    jid, err = enqueue(mode, params, "n8n", h.uid)
    if jid is None:
        return h.send_json(429, {"error": err})
    deadline = time.time() + 6 * 3600
    while time.time() < deadline:
        job = Job.find_one(id=oid(jid))
        if job["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(3)
    if job["status"] != "done":
        return h.send_json(500, {"error": "pipeline failed", "detail": "\n".join(job.get("log", [])[-15:])})
    m = json.loads((OUTPUT_DIR / "runs" / f"{jid}.json").read_text(encoding="utf-8"))
    h.send_json(200, m)


ROUTES = [
    (r"/api/jobs", "GET", h_jobs),
    (r"/api/jobs", "POST", h_job_start),
    (r"/api/jobs/([0-9a-f]{24})", "GET", h_job),
    (r"/api/jobs/([0-9a-f]{24})/cancel", "POST", h_job_cancel),
    (r"/run", "POST", h_run_sync),
]
bp = Blueprint("job", __name__)
register(bp, ROUTES)
