"""Cleaner cuts: a clip should not start or stop in the middle of a word, and a cut should not click.

A section cut out of a YouTube video starts and ends where the caption times say, and those are only roughly right: a clip can begin on
the last half of a word or stop right after the first letter of the next one. This module listens to the clip itself and moves each edge
(by at most one second) to the nearest quiet moment, so the cut falls between words.

  * quiet moment  = at least 100 ms where the sound is well below the speech of this clip (measured against the clip's own loud and quiet levels)
  * an edge that is already in a quiet moment, or has none nearby (music, constant noise), is left as it is
  * a clip is never made shorter than `min_keep` seconds, and never loses more than `max_shift` seconds at either end

And a 30 ms fade at the start and end of every audio track (fade_filter) so a hard cut never makes a click, in a Short or at a join in a
compilation. Everything fails soft: on any problem the clip is left exactly as it was.
"""
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

SR = 16000
STEP = 0.02                 # seconds per energy value (20 ms)
FADE_S = 0.03               # the fade at every cut
QUIET_RUN = 5               # this many quiet steps in a row (100 ms) make a pause between words
MAX_SHIFT = 1.0             # the most that is taken off either end
MIN_KEEP = 12.0             # a clip is never made shorter than this
MIN_CHANGE = 0.12           # a trim smaller than this (in total) is not worth a re-encode


def enabled() -> bool:
    return (os.environ.get("CLEAN_CUTS") or "on").strip().lower() not in ("off", "0", "no", "false")


def fade_filter(duration: float, fade: float = FADE_S) -> str:
    """ffmpeg audio filter: a short fade in at the start and out at the end. Empty when the duration is unknown or too short."""
    if not duration or duration < 4 * fade:
        return ""
    return f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={duration - fade:.3f}:d={fade:.3f}"


def energy_db(media: Path, ffmpeg: str = "ffmpeg") -> np.ndarray:
    """Loudness in dB for every 20 ms of the clip's sound. Empty when there is no usable sound."""
    p = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                       capture_output=True, timeout=300)
    if p.returncode != 0 or not p.stdout:
        return np.zeros(0, dtype=np.float32)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = x.size // int(SR * STEP)
    if n < 50:
        return np.zeros(0, dtype=np.float32)
    frames = x[: n * int(SR * STEP)].reshape(n, int(SR * STEP))
    return (20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)).astype(np.float32)


def quiet_threshold(db: np.ndarray) -> Optional[float]:
    """The level below which this clip is 'between words'. None when the clip has no speech-like contrast (silence, steady music)."""
    if db.size < 50:
        return None
    floor, speech = float(np.percentile(db, 10)), float(np.percentile(db, 90))
    if speech - floor < 12:                   # too even: there are no pauses to cut in
        return None
    return floor + 0.28 * (speech - floor)


def _quiet_runs(db: np.ndarray, thr: float):
    """[(first_step, last_step)] of every stretch of at least QUIET_RUN steps below the threshold."""
    runs, start = [], None
    for i, v in enumerate(db):
        if v < thr:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= QUIET_RUN:
                runs.append((start, i - 1))
            start = None
    if start is not None and len(db) - start >= QUIET_RUN:
        runs.append((start, len(db) - 1))
    return runs


def find_edges(db: np.ndarray, max_shift: float = MAX_SHIFT, min_keep: float = MIN_KEEP) -> Tuple[float, float]:
    """(start, end) in seconds of the clip, moved to the nearest pause at each side. Pure function: the same sound always gives the same cut."""
    dur = db.size * STEP
    thr = quiet_threshold(db)
    if thr is None or dur < min_keep + 2 * STEP:
        return 0.0, dur
    runs = _quiet_runs(db, thr)
    if not runs:
        return 0.0, dur
    ms = int(max_shift / STEP)
    t0, t1 = 0.0, dur
    # start: already in a pause (the clip opens quietly)? keep. Otherwise the first pause inside the first max_shift seconds: cut in its middle
    if not (db[:QUIET_RUN] < thr).all():
        for a, b in runs:
            if a > ms:
                break
            mid = (a + b) / 2 * STEP
            if a >= 1:                         # a pause that starts at 0 is "already quiet"
                t0 = mid
                break
    # end: already quiet? keep. Otherwise the last pause inside the last max_shift seconds
    n = db.size
    if not (db[n - QUIET_RUN:] < thr).all():
        for a, b in reversed(runs):
            if b < n - 1 - ms:
                break
            if b < n - 1:
                t1 = (a + b) / 2 * STEP + STEP
                break
    if t1 - t0 < min_keep or (t0 + (dur - t1)) < MIN_CHANGE:
        return 0.0, dur
    return round(t0, 2), round(min(t1, dur), 2)


def snap_file(path: Path, ffmpeg: str = "ffmpeg") -> Optional[Tuple[float, float]]:
    """Trim a downloaded section in place so it starts and stops in a pause. Returns (start, end) when the file was trimmed, else None.
    The clip is encoded once more (a few seconds, no visible loss). On any error the original file is kept untouched."""
    if not enabled():
        return None
    try:
        db = energy_db(path, ffmpeg)
        if db.size == 0:
            return None
        t0, t1 = find_edges(db)
        dur = db.size * STEP
        if t0 <= 0.0 and t1 >= dur - 0.02:
            return None
        tmp = path.with_name(path.stem + ".trim" + path.suffix)
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-ss", f"{t0:.2f}", "-t", f"{t1 - t0:.2f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "aac", "-b:a", "192k", str(tmp)]
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        if r.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 10_000:
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(path)
        return t0, t1
    except Exception:
        return None
