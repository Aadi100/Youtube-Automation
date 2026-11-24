"""The clip finder's engine: look at a stream / replay / video, find its best moments, and cut small previews of them.

No AI and no tokens: the moments come from what a video already tells us for free
  * YouTube's "most replayed" curve (no download at all),
  * the sound: shouting, laughing and sudden loud moments in the audio,
and everything is cut with FFmpeg. The studio's normal safety checks still run later on whatever the member picks.

Live streams: a stream that is still going is read back from its own recording so far.
  * Twitch keeps the whole broadcast so far as a replay (found through the streamer's latest past stream),
  * YouTube and Kick keep only a recent window of a live stream, and we read whatever they keep.
"""
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

from app.config import FFMPEG_BIN
from app.engine import clipcfg
from app.engine import discovery as D
from app.engine import live_scanner as L

CHANNEL_RE = re.compile(r"^https://(?:www\.)?(?:twitch\.tv/[A-Za-z0-9_]{3,25}|kick\.com/[\w\-]{2,40})/?$")
MAX_LIVE_SECONDS = 5400          # at most 90 minutes of a live stream are read back


def platform_of(url: str) -> str:
    return "twitch" if "twitch.tv" in url else "kick" if "kick.com" in url else "youtube"


def is_channel_url(url: str) -> bool:
    return bool(CHANNEL_RE.match(url)) and not re.search(r"/(videos|clip|clips|video)\b", url)


# ---------------------------------------------------------------- looking at the source
def probe_url(url: str) -> Dict:
    """Title, creator, length and whether it is live right now. Raises ValueError with a plain message."""
    try:
        info = json.loads(D._ytdlp("-J", "--no-playlist", url, capture=True, timeout=120))
    except RuntimeError as e:
        low = str(e).lower()
        if "offline" in low or "not currently live" in low or "is not live" in low:
            raise ValueError("That streamer is not live right now. Open one of their past streams instead.")
        if "private" in low or "sign in" in low or "members-only" in low:
            raise ValueError("That video is private or needs a sign-in, so it cannot be used.")
        raise ValueError("Could not read that link: " + str(e)[-150:])
    live = bool(info.get("is_live")) or info.get("live_status") == "is_live"
    return {"id": str(info.get("id") or ""), "title": info.get("title") or "Stream", "creator": info.get("channel") or info.get("uploader") or "Creator",
            "channel_url": info.get("channel_url") or info.get("uploader_url"), "duration": float(info.get("duration") or 0), "live": live,
            "heatmap": info.get("heatmap") or [], "age_limit": int(info.get("age_limit") or 0), "url": info.get("webpage_url") or url,
            "platform": platform_of(url), "view_count": int(info.get("view_count") or 0)}


def twitch_current_vod(login: str) -> Optional[str]:
    """The replay of the broadcast that is happening right now (Twitch keeps it from the first minute), or None when the streamer has replays off."""
    try:                                              # with the Twitch keys: the replay that belongs to the running stream
        hdr = D._twitch_headers()
        u = D._twitch_user(login, hdr)
        st = requests.get(f"{D.HELIX}/streams", headers=hdr, params={"user_id": u["id"]}, timeout=30).json().get("data") or []
        vids = requests.get(f"{D.HELIX}/videos", headers=hdr, params={"user_id": u["id"], "type": "archive", "first": 5}, timeout=30).json().get("data") or []
        if st:
            for v in vids:
                if v.get("stream_id") == st[0].get("id"):
                    return v["url"]
        return vids[0]["url"] if vids and st else None
    except Exception:
        pass
    try:                                              # no keys: the streamer's newest past stream (yt-dlp lists it without a login)
        out = json.loads(D._ytdlp("--flat-playlist", "-J", "--playlist-end", "1", f"https://www.twitch.tv/{login}/videos?filter=archives&sort=time", capture=True, timeout=90))
        e = (out.get("entries") or [None])[0]
        return (e or {}).get("url") or (e or {}).get("webpage_url")
    except Exception:
        return None


# ---------------------------------------------------------------- reading back a live stream
def _stream_urls(url: str) -> List[str]:
    out = D._ytdlp("-g", "-f", "bv*[height<=480]+ba/b[height<=480]/b", "--no-playlist", url, capture=True, timeout=120)
    urls = [u for u in out.strip().splitlines() if u.startswith("http")]
    if not urls:
        raise ValueError("Could not open that live stream.")
    return urls[:2]


def _playlist_seconds(url: str, proxies=None) -> float:
    """How much past the stream's playlist still holds (the sum of its segment lengths)."""
    try:
        txt = requests.get(url, timeout=30, proxies=proxies).text
        return sum(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", txt))
    except Exception:
        return 0.0


def record_back(url: str, out: Path) -> float:
    """Save everything a live stream still keeps (its recent past) into `out`. Returns the seconds saved."""
    urls = _stream_urls(url)
    from app.engine import yt_access
    yt = "youtu" in url                   # a YouTube link only works from the address that asked for it: use the same proxy
    have = _playlist_seconds(urls[0], yt_access.requests_proxies() if yt else None)
    seconds = int(min(MAX_LIVE_SECONDS, have if have > 30 else 600))
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y"]
    if yt:
        cmd += yt_access.ffmpeg_proxy_args()
    for u in urls:
        cmd += ["-live_start_index", "0", "-i", u]
    if len(urls) == 2:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-t", str(seconds), "-c", "copy", "-f", "mpegts", str(out)]
    subprocess.run(cmd, capture_output=True, timeout=seconds + 240)
    if not out.is_file() or out.stat().st_size < 300_000:
        raise ValueError("That live stream does not let us read back its earlier part.")
    return float(seconds)


# ---------------------------------------------------------------- finding the moments
def download_audio(url: str, win: Tuple[float, float], out_stem: Path) -> Path:
    """Only the sound of one part of a video (small and fast)."""
    for old in out_stem.parent.glob(out_stem.name + ".*"):
        old.unlink(missing_ok=True)
    D._ytdlp("-f", "ba/worst", "--download-sections", f"*{win[0]:.1f}-{win[1]:.1f}", "--no-playlist", "--force-overwrites", "-o", f"{out_stem}.%(ext)s", url, timeout=900)
    got = [p for p in out_stem.parent.glob(out_stem.name + ".*") if p.suffix not in (".part", ".ytdl")]
    if not got:
        raise ValueError("Could not read the sound of that video.")
    return got[0]


def sound_moments(media: Path, want: int, offset: float = 0.0, min_gap: int = 60) -> List[Dict]:
    """The loudest, most exciting moments of a recording: [{start, end, score, reasons}] (times include `offset`)."""
    db = L._audio_db(media)
    n = len(db)
    before, after = clipcfg.span()
    if n < before + after + 10:
        return []
    smooth = lambda a, k: np.convolve(a, np.ones(k) / k, mode="same")
    z = L._z(smooth(db, 4))
    z[:before] = -1e9
    z[n - after - 2:] = -1e9
    out = []
    while len(out) < want:
        i = int(z.argmax())
        if z[i] < 0.8:
            break
        rise = float(db[i] - np.median(db[max(0, i - 25):max(1, i - 6)])) if i > 30 else 0.0
        reasons = ["Big loud moment"] if z[i] > 3 else ["Loud reaction"]
        if rise > 9:
            reasons.append("Sudden shout or jump")
        out.append({"start": round(offset + max(0, i - before), 1), "end": round(offset + i + after, 1), "score": int(max(5, min(99, 38 + 14 * float(z[i])))), "reasons": reasons})
        z[max(0, i - min_gap): i + min_gap] = -1e9
    return out


def heat_moments(info: Dict, want: int) -> List[Dict]:
    """YouTube's 'most replayed' peaks (no download needed)."""
    before, after = clipcfg.span()
    return [{"start": a, "end": b, "score": int(min(99, max(10, s))), "reasons": ["Most replayed by viewers"]}
            for a, b, s in D._peak_windows(info, before + after, want)]


def merge(found: List[Dict], limit: int) -> List[Dict]:
    """Best first; two moments that overlap become one (with both reasons and a better score)."""
    out: List[Dict] = []
    for c in sorted(found, key=lambda c: -c["score"]):
        twin = next((o for o in out if abs(o["start"] - c["start"]) < 25), None)
        if twin:
            twin["reasons"] = list(dict.fromkeys(twin["reasons"] + c["reasons"]))
            twin["score"] = min(99, twin["score"] + 8)
        else:
            out.append(dict(c))
    return sorted(out, key=lambda c: -c["score"])[:limit]


# ---------------------------------------------------------------- cutting
def cut_preview(src: Path, start: float, end: float, out: Path) -> Path:
    """A small, quick-to-play copy of a part of a local recording."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{end - start:.2f}", "-vf", "scale=-2:360",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)], check=True, capture_output=True, timeout=300)
    return out


def cut_full(src: Path, start: float, end: float, out: Path) -> Path:
    """The same part at the recording's own quality, for editing."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{end - start:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True, capture_output=True, timeout=600)
    return out


def download_preview(url: str, start: float, end: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    D._ytdlp("-f", "bv*[height<=360]+ba/b[height<=360]/worst", "--merge-output-format", "mp4", "--download-sections", f"*{start:.1f}-{end:.1f}", "--force-keyframes-at-cuts",
             "--no-playlist", "--force-overwrites", "-o", str(out), url, timeout=300)
    if not out.is_file():
        raise ValueError("Could not cut a preview.")
    return out


def thumbnail(video: Path, out: Path) -> Optional[Path]:
    r = subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", "8", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out)], capture_output=True, timeout=60)
    return out if out.is_file() else None
