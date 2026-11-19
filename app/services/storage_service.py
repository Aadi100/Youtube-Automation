"""Disk housekeeping, so a busy server never runs out of space.

  * each member's files are limited (MEMBER_STORAGE_MB, default 3000 MB); a member over the limit cannot start new videos
  * old files are removed on a schedule; the video's record stays (title, link, status), only the heavy files go:
        public videos            local copy removed after RETENTION_PUBLIC_DAYS   (default 7)
        declined / failed ones   removed after RETENTION_DROPPED_DAYS             (default 2)
        waiting for a decision   removed after RETENTION_PENDING_DAYS             (default 30, then marked discarded)
        source clips and leftovers, temp folders and job result files after a few days
"""
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path
from typing import Dict, Optional

from app.config import BASE_DIR, OUTPUT_DIR
from app.models import Clip, Video, now


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def cap_mb() -> int:
    return _int("MEMBER_STORAGE_MB", 3000)


def dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def member_usage_mb(uid: str) -> float:
    n = sum(dir_size(d / str(uid)) for d in (OUTPUT_DIR / "shorts", OUTPUT_DIR / "compilations", BASE_DIR / "inputs"))
    return round(n / 1e6, 1)


def over_cap(uid: str) -> Optional[str]:
    """None if the member may start a video, else the message to show them."""
    used, cap = member_usage_mb(uid), cap_mb()
    if used >= cap:
        return f"Your storage is full ({used:.0f} of {cap} MB). Delete old videos on the Videos page, then try again."
    return None


def disk() -> Dict:
    u = shutil.disk_usage(BASE_DIR)
    return {"total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1), "free_pct": round(100 * u.free / u.total, 1)}


def _remove(p: Optional[str]) -> int:
    """Delete one file that lives inside outputs/. Returns bytes freed."""
    if not p:
        return 0
    try:
        f = Path(p).resolve()
        f.relative_to(OUTPUT_DIR.resolve())
        if f.is_file():
            n = f.stat().st_size
            f.unlink()
            side = f.with_suffix(".json")
            if side.is_file():
                side.unlink()
            return n
    except (ValueError, OSError):
        pass
    return 0


def cleanup() -> Dict:
    current = now()
    freed = removed_videos = 0
    plans = ((["public"], _int("RETENTION_PUBLIC_DAYS", 7)), (["declined", "failed", "discarded"], _int("RETENTION_DROPPED_DAYS", 2)),
             (["rendered", "uploaded"], _int("RETENTION_PENDING_DAYS", 30)))
    for statuses, days in plans:
        cutoff = current - timedelta(days=days)
        for v in Video.find_all(status__in=statuses, file_removed__ne=True, created_at__lt=cutoff, upload_status__nin=["queued", "uploading"], limit=2000):
            n = _remove(v.get("video_path")) + _remove(v.get("thumbnail_path"))
            freed += n
            removed_videos += 1
            upd = {"file_removed": True}
            if "rendered" in statuses and v["status"] == "rendered":
                upd["status"] = "discarded"   # never decided on: stop keeping the heavy files
            Video.update_where(id=v["_id"], fields=upd)
    removed_inputs = 0
    cutoff_ts = time.time() - 3 * 86400
    inputs = BASE_DIR / "inputs"
    for root, _d, files in os.walk(inputs):
        for f in files:
            p = Path(root) / f
            try:
                if p.stat().st_mtime < cutoff_ts and not Clip.find_one(path=str(p), status="banked"):
                    freed += p.stat().st_size
                    p.unlink()
                    removed_inputs += 1
            except OSError:
                pass
    removed_temp = 0
    old = time.time() - 86400
    temp = BASE_DIR / "temp"
    if temp.exists():
        for p in temp.iterdir():
            try:
                if p.stat().st_mtime < old:
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
                    removed_temp += 1
            except OSError:
                pass
    runs = OUTPUT_DIR / "runs"
    if runs.exists():
        for p in runs.glob("*.json"):
            try:
                if p.stat().st_mtime < time.time() - 3 * 86400:
                    p.unlink()
            except OSError:
                pass
    return {"videos_cleaned": removed_videos, "inputs_removed": removed_inputs, "temp_removed": removed_temp, "freed_mb": round(freed / 1e6, 1)}
