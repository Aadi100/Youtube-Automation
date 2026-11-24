"""Views (the V of MVC): how a running or finished job is shown to people.

Members never see the raw log (it has server details and technical errors). They get a plain-language progress summary
built from it: the steps, a percentage, what is happening now, what has been done so far, and a friendly error.
The owner gets the same summary plus the raw log.
"""
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.models import Job, clean

# (key, label shown to people, regex that proves the step has started)
STEPS_MAKE = [("find", "Finding a clip", r"\[Discovery\]|\[Live\]|\[Own clip\]"),
              ("safety", "Safety check", r"\[Safety\]"),
              ("edit", "Editing, voice and captions", r"PIPELINE|\[Subtitles\]|\[Audio|\[Shorts\]|\[Compil|\[AI\] commentary"),
              ("meta", "Title and description", r"\[AI\] metadata|\[AI Metadata\]"),
              ("thumb", "Thumbnail", r"\[Thumbnail\]|\[AI art\]"),
              ("ready", "Ready", r"MANIFEST")]
STEPS_REMIX = [("prep", "Getting your clips ready", r"\[Remix\]"),
               ("audio", "Preparing the new audio", r"PIPELINE|\[Subtitles\]|\[Audio|\[AI\] commentary"),
               ("edit", "Editing and rendering", r"\[Shorts\] Rendering|\[Compil|Rendering"),
               ("safety", "Final safety check", r"\[Safety\] final"),
               ("ready", "Ready", r"MANIFEST")]
BASE = {"make": [6, 24, 38, 80, 90, 100], "remix": [6, 20, 45, 92, 100]}
NOW = {"find": "Looking for the best clip for you",
       "safety": "Making sure the clip is safe to post",
       "edit": "Editing your video, recording the voice-over and adding captions",
       "meta": "Writing the title and description",
       "thumb": "Designing the thumbnail",
       "ready": "Your video is ready",
       "prep": "Getting your clips ready",
       "audio": "Preparing the new audio"}
NOW_REMIX = {"edit": "Rendering your video with the new audio", "safety": "Running the final safety check"}
TYPICAL = {"short": 300, "compilation": 2400, "remix": 240}


def friendly_error(err: Optional[str]) -> Optional[str]:
    """A technical error in plain words. Raw errors stay with the owner."""
    e = (err or "").strip()
    if not e:
        return None
    low = e.lower()
    if re.match(r"^(Choose a part|That video|That creator|Another member|Could not read|Your own commentary|The original clip)", e):
        return e[:200]                       # these were written for the member in the first place
    if "blocking this server" in low:
        return "We could not get a clip from YouTube right now. Nothing was charged. Please try again later."
    if "no source available" in low or "no new clips" in low or "nothing usable" in low:
        return "We could not find a new clip this time. Nothing was charged. Please try again in a few minutes."
    if "content-safety" in low or "safety check" in low or "blocked by" in low:
        return "The clip did not pass the safety check, so it was not used. Nothing was charged."
    if "worker restarted" in low or "worker lost" in low:
        return "The server restarted while your video was being made. Nothing was charged. Please try again."
    if "cancelled" in low:
        return "You cancelled this run. Nothing was charged."
    return "Something went wrong while making this video. Nothing was charged. Please try again, and tell the owner if it keeps happening."


def _typical(kind: str) -> int:
    """How long a finished video of this kind usually takes (seconds), from the last finished ones."""
    mode = {"remix": "remix", "compilation": "auto-compilation"}.get(kind, "auto-short")
    ds = []
    for j in Job.find_all(status="done", mode=mode, order=("-finished_at",), limit=10, only=("started_at", "finished_at")):
        if j.get("started_at") and j.get("finished_at"):
            ds.append((j["finished_at"] - j["started_at"]).total_seconds())
    return int(sum(ds) / len(ds)) if ds else TYPICAL[kind]


def _highlights(log: List[str]) -> List[str]:
    """What has been done so far, in plain words, taken from the log (no provider names, no file paths)."""
    out = []
    for line in log:
        m = re.match(r"\[Discovery\] downloading: (.+?) - (.+?)(?: \(\d+ min video\))?$", line)
        if m:
            out.append(f"Found a clip: {m.group(2).strip()[:70]} by {m.group(1).strip()[:40]}")
        elif re.match(r"\[Own clip\] (.+?) - (.+?) \(", line):
            m2 = re.match(r"\[Own clip\] (.+?) - (.+?) \(", line)
            out.append(f"Your clip is ready: {m2.group(2).strip()[:70]} by {m2.group(1).strip()[:40]}")
        elif re.match(r"\[Safety\] \S+: clear", line) or re.match(r"\[Safety\] \S+: partial", line):
            out.append("The clip passed the safety check")
        elif re.match(r"\[AI\] commentary:", line):
            out.append("Voice-over script written")
        elif re.match(r"\[Safety\] final video: (clear|partial)", line):
            out.append("The finished video passed the safety check")
        elif re.match(r"\[AI\] metadata:", line):
            out.append("Title and description written")
        elif re.match(r"\[AI art\] background", line):
            out.append("Thumbnail background created")
        elif line.startswith("MANIFEST"):
            out.append("Video saved")
    seen, uniq = set(), []
    for h in out:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq[-8:]


def job_progress(j: Dict, position: int = 0) -> Dict:
    """Steps, percentage, friendly message and highlights for one job."""
    log = [str(x) for x in (j.get("log") or [])]
    mode = str(j.get("mode") or "")
    kind = "remix" if mode == "remix" else "compilation" if "compilation" in mode else "short"
    defs = STEPS_REMIX if kind == "remix" else STEPS_MAKE
    status = j.get("status")
    at = -1
    for i, (_, _, rx) in enumerate(defs):
        if any(re.search(rx, ln) for ln in log):
            at = max(at, i)
    done, failed = status == "done", status in ("failed", "cancelled")
    steps = []
    for i, (key, label, _) in enumerate(defs):
        state = "done" if done or i < at else "now" if i == at else "todo"
        if failed and i == at:
            state = "bad"
        steps.append({"key": key, "label": label, "state": state})
    started = j.get("started_at") or j.get("created_at")
    end = j.get("finished_at")
    elapsed = int(((end or datetime.now(timezone.utc)) - started).total_seconds()) if started else 0
    typical = _typical(kind)
    base = BASE["remix" if kind == "remix" else "make"]
    if done:
        pct = 100
    elif status == "queued" or at < 0:
        pct = 2 if status == "queued" else 5
    else:
        nxt = base[at + 1] - 1 if at + 1 < len(base) else 99
        pct = max(base[at], min(int(elapsed / max(60, typical) * 100), nxt, 95))
    if status == "queued":
        msg = f"Waiting for a free slot. You are number {position} in line." if position and position > 0 else "Waiting for a free slot."
    elif done:
        msg = "Your video is ready."
    elif failed:
        msg = friendly_error(j.get("error")) or "This run did not finish."
    elif at >= 0:
        key = defs[at][0]
        msg = (NOW_REMIX.get(key) if kind == "remix" else None) or NOW.get(key, "Working on it")
    else:
        msg = "Starting"
    game = next((m.group(1).strip() for m in (re.match(r"\[Game\]\s*(.+)", ln) for ln in log) if m), "")
    return {"kind": kind, "status": status, "steps": steps, "percent": pct, "message": msg, "highlights": _highlights(log), "game": game,
            "elapsed": elapsed, "typical": typical, "position": position or 0}


def public_job(j: Dict, owner: bool, position: int = 0, full: bool = True) -> Dict:
    """A job for the browser. The owner also gets the raw log and the technical error; a member gets plain words only."""
    out = clean(j)
    if full:
        out["progress"] = job_progress(j, position)
    if not owner:
        for k in ("log", "params", "worker", "heartbeat", "tokens", "refunded", "settled", "receipt", "cost_tokens", "started_at"):
            out.pop(k, None)
        if j.get("error"):
            out["error"] = friendly_error(j["error"])
    return out
