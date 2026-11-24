"""Watch live streams for a few minutes and cut out the best moments (funny / hype / loud).

How it "watches":
  1. find streams that are live right now for the game (Twitch needs the Twitch keys; YouTube works without keys),
     only in the allowed regions/languages (see CLIP_COUNTRIES / CLIP_LANGUAGES),
  2. record several of them at the same time for LIVE_WATCH_MINUTES,
     while counting Twitch chat messages per second (anonymous read-only chat connection, no login needed),
  3. score every second: chat speed-up (laughs/hype emotes count extra) + audio loudness (shouting/laughing),
  4. cut ~38 s around the strongest moments, delete the recordings, and hand the clips to the normal pipeline
     (AI commentary + music, captions, thumbnail, upload Unlisted, email approval).
Credit to the streamer + channel link is kept like for every other clip.
"""
from app.models import Claim, Clip, Game, now
import random
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import numpy as np
import requests

from app.engine import audience, clipcfg
from app.engine import discovery as D
from app.config import FFMPEG_BIN, INPUT_DIR, TEMP_DIR

LAUGH = re.compile(r"\b(lul|lulw|kekw|omegalul|lmao|lmfao|haha+|pog+|poggers|pogchamp|wtf|omg|holy|clip(?: ?it)?|"
                   r"no ?way|insane|crazy|dead|dying|wow|w+)\b|[😂🤣😭🔥💀]", re.I)
CLIP_BEFORE, CLIP_AFTER = 28, 10      # seconds kept before / after the detected peak
CHAT_LAG = 4                          # chat reacts a few seconds after the moment happens
MIN_CHAT_EVENTS = 30                  # fewer chat messages than this = ignore chat, use audio only


def _log(msg: str) -> None:
    print(f"[Live] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)   # titles may hold emoji; consoles can be cp1252


# ------------------------------------------------------------------ finding live streams
def twitch_live_streams(game: Dict, limit: int = 20) -> List[Dict]:
    cats = D.split_terms(game.get("twitch_category", ""))
    if not cats:
        raise RuntimeError("this game has no Twitch category")
    hdr = D._twitch_headers()
    out, seen = [], set()
    for cat in cats[:4]:
        gid = D.twitch_category_id(cat, hdr)
        if not gid:
            continue
        params = [("game_id", gid), ("first", "40"), ("type", "live")] + [("language", l) for l in sorted(audience.languages() or [])[:20]]     # this person's stream languages; none = no language filter (they chose All)
        r = requests.get(f"{D.HELIX}/streams", headers=hdr, params=params, timeout=30)
        r.raise_for_status()
        for s in r.json().get("data", []):
            if s["user_login"] in seen or not D._region_ok(s["user_name"], s["title"]) or s.get("is_mature"):
                continue
            seen.add(s["user_login"])
            out.append({"platform": "twitch", "login": s["user_login"], "name": s["user_name"], "title": s["title"],
                        "viewers": s["viewer_count"], "url": f"https://www.twitch.tv/{s['user_login']}",
                        "channel_url": f"https://www.twitch.tv/{s['user_login']}"})
    if not out:
        raise RuntimeError("no live Twitch streams found for this game's categories")
    return sorted(out, key=lambda x: -x["viewers"])[:limit]


def youtube_live_streams(query: str, limit: int = 20) -> List[Dict]:
    """YouTube search restricted to 'Live right now' (no API key needed)."""
    queries = D.split_terms(query)
    if not queries:
        raise RuntimeError("this game has no YouTube search terms")
    import json
    res, seen_ids = [], set()
    entries = []
    for q in queries[:3]:
        try:
            url = f"https://www.youtube.com/results?search_query={quote_plus(q)}&sp=EgJAAQ%253D%253D"
            entries += json.loads(D._ytdlp("--flat-playlist", "-J", "--playlist-end", "25", url, capture=True)).get("entries", [])
        except Exception:
            continue
    for e in entries:
        if not e or not e.get("id") or e["id"] in seen_ids:
            continue
        seen_ids.add(e["id"])
        name = e.get("channel") or e.get("uploader") or "YouTube"
        title = e.get("title") or "live stream"
        if name.lower().strip() in D.OFFICIAL_CHANNELS or not D._region_ok(name, title):
            continue
        res.append({"platform": "youtube", "login": e["id"], "name": name, "title": title,
                    "viewers": int(e.get("view_count") or 0), "url": f"https://www.youtube.com/watch?v={e['id']}",
                    "channel_url": e.get("channel_url") or e.get("uploader_url")})
    return res[:limit]


def _recently_scanned(stream: Dict, hours: int = 3) -> bool:
    try:
        since = now() - timedelta(hours=hours)
        return Clip.total(id__regex=f"^live_{re.escape(stream['login'])}_", created_at__gt=since) > 0
    except Exception:
        return False


# ------------------------------------------------------------------ recording + chat
class ChatCounter(threading.Thread):
    """Anonymous, read-only Twitch chat listener: remembers when messages arrived (and how 'hype' they are)."""

    def __init__(self, login: str):
        super().__init__(daemon=True)
        self.login, self.events, self.stop_flag = login.lower(), [], threading.Event()

    def run(self):
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=15)
            s.settimeout(5)
            s.sendall(f"NICK justinfan{random.randint(10000, 99999)}\r\nJOIN #{self.login}\r\n".encode())
            buf = ""
            while not self.stop_flag.is_set():
                try:
                    chunk = s.recv(4096).decode("utf-8", "ignore")
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split("\r\n")
                for line in lines:
                    if line.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                    elif " PRIVMSG " in line:
                        text = line.split(" PRIVMSG ", 1)[1].split(" :", 1)[-1]
                        self.events.append((time.monotonic(), 1 + (2 if LAUGH.search(text) else 0)))
            s.close()
        except Exception as e:
            _log(f"chat for {self.login} unavailable ({type(e).__name__})")


def _stream_urls(stream: Dict) -> List[str]:
    """1 URL (video+audio together, Twitch) or 2 URLs (video, audio - YouTube live)."""
    extra = ["--js-runtimes", "node"] if stream["platform"] == "youtube" else []   # YouTube needs a JS runtime (node is installed for n8n)
    out = D._ytdlp(*extra, "-g", "-f", "bv*[height<=720]+ba/b[height<=720]/b", "--no-playlist", stream["url"], capture=True)
    urls = [u for u in out.strip().splitlines() if u.startswith("http")]
    if not urls:
        raise RuntimeError("no stream URL")
    return urls[:2]


def _watch(stream: Dict, seconds: int, out: Path) -> None:
    """Record `seconds` of the stream into out; fills stream['t0'], stream['chat']. Never raises."""
    chat = ChatCounter(stream["login"]) if stream["platform"] == "twitch" else None
    try:
        urls = _stream_urls(stream)
    except Exception as e:
        _log(f"{stream['name']}: cannot open stream ({str(e)[:90]})")
        return
    if chat:
        chat.start()
    stream["t0"] = time.monotonic()
    stream["wall0"] = time.time()
    try:
        cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y"]
        if stream["platform"] == "youtube":
            from app.engine import yt_access
            cmd += yt_access.ffmpeg_proxy_args()          # the link is only valid for the address that asked for it (the proxy, when there is one)
        for u in urls:
            cmd += ["-i", u]
        if len(urls) == 2:
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        subprocess.run(cmd + ["-t", str(seconds), "-c", "copy", "-f", "mpegts", str(out)], capture_output=True, timeout=seconds + 45)
    except Exception as e:
        _log(f"{stream['name']}: recording stopped ({type(e).__name__})")
    if chat:
        chat.stop_flag.set()
        stream["chat"] = list(chat.events)
    stream["rec"] = out if out.exists() and out.stat().st_size > 200_000 else None


# ------------------------------------------------------------------ finding the moments
def _audio_db(rec: Path) -> np.ndarray:
    p = subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-i", str(rec), "-vn", "-ac", "1",
                        "-ar", "8000", "-f", "s16le", "-"], capture_output=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32)
    n = len(x) // 8000
    if n < 40:
        return np.zeros(0)
    rms = np.sqrt((x[:n * 8000].reshape(n, 8000) ** 2).mean(axis=1))
    return 20 * np.log10(rms + 1)


def _z(x: np.ndarray) -> np.ndarray:
    med = np.median(x)
    spread = np.median(np.abs(x - med)) * 1.4826 or x.std() or 1.0
    return (x - med) / spread


def find_moments(stream: Dict, want: int = 2, min_score: Optional[float] = None) -> List[tuple]:
    """[(second_in_recording, score)] strongest first."""
    audio = _audio_db(stream["rec"])
    n = len(audio)
    if n < 60:
        return []
    chat = np.zeros(n)
    for t, w in stream.get("chat", []):
        i = int(t - stream["t0"] - CHAT_LAG)
        if 0 <= i < n:
            chat[i] += w
    have_chat = chat.sum() >= MIN_CHAT_EVENTS
    smooth = lambda a, k: np.convolve(a, np.ones(k) / k, mode="same")
    score = 0.6 * _z(smooth(audio, 4))
    if have_chat:
        score = score + _z(smooth(chat, 8))
    before, after = clipcfg.span()
    thr = min_score if min_score is not None else (3.5 if have_chat else 1.8) * clipcfg.live_factor()
    best_seen = float(score[before:max(before + 1, n - after - 2)].max()) if n > before + after + 5 else 0.0
    score[:before] = -1e9
    score[n - after - 2:] = -1e9
    picks = []
    while len(picks) < want:
        i = int(score.argmax())
        if score[i] < thr:
            break
        picks.append((i, float(score[i])))
        score[max(0, i - 60): i + 60] = -1e9
    _log(f"{stream['name']}: {'chat+audio' if have_chat else 'audio only'}, {len(picks)} moment(s)"
         + (f", best score {picks[0][1]:.1f}" if picks else f" (highest seen {best_seen:.1f}, needs {thr})"))
    return picks


def _cut(rec: Path, peak: int, out: Path) -> None:
    before, after = clipcfg.span()
    start = max(0, peak - before)
    subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(rec),
                    "-t", str(before + after), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True, capture_output=True)


# ------------------------------------------------------------------ public entry point
def scan_live(game: Dict, want: int = 1, watch_minutes: float = 8, max_streams: int = 4,
              min_score: Optional[float] = None) -> List[Dict]:
    """Returns clip dicts like discovery.download_candidate results: {path, streamer, title, views, clip_id, url,
    channel_url, source, game_id}. Empty list when nothing worth clipping happened."""
    lists, errors = [], []
    for name, fn in (("twitch", lambda: twitch_live_streams(game)), ("youtube", lambda: youtube_live_streams(game.get("youtube_query", "")))):
        try:
            found = [s for s in fn() if not _recently_scanned(s)]
            _log(f"{game['name']} / {name}: {len(found)} live stream(s) available")
            lists.append(found)
        except Exception as e:
            errors.append(f"{name}: {e}")
            _log(f"{name} live search unavailable - {e}")
    from app.engine import region
    streams = []
    for s in D._interleave(lists)[:max(16, max_streams * 3)]:
        if len(streams) >= max_streams:
            break
        if s["platform"] == "youtube":
            ok, why = region.check_stream(s)
            if not ok:
                _log(f"skipped {s['name']}: {why}")
                continue
        streams.append(s)
    if not streams:
        raise RuntimeError("No live streams found. " + " | ".join(errors))

    seconds = int(watch_minutes * 60)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    _log(f"watching {len(streams)} stream(s) for {watch_minutes:g} min: " + ", ".join(s["name"] for s in streams))
    threads = []
    for i, s in enumerate(streams):
        t = threading.Thread(target=_watch, args=(s, seconds, TEMP_DIR / f"live_{stamp}_{i}.ts"), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(seconds + 180)

    moments = []
    try:
        for s in streams:
            if s.get("rec"):
                moments += [(score, s, peak) for peak, score in find_moments(s, want=2, min_score=min_score)]
        moments.sort(key=lambda m: m[0], reverse=True)
        pool, per_stream = [], {}
        for score, s, peak in moments:
            if len(pool) >= 8:   # keep every decent moment: the extras go into the clip bank
                break
            if per_stream.get(s["login"], 0) >= 2:
                continue
            if s["platform"] == "youtube" and not s.get("channel_url"):   # search results don't say whose stream it is
                try:
                    name, curl = D._ytdlp("--js-runtimes", "node", "--skip-download", "--no-playlist", "--print",
                                          "%(channel)s|||%(channel_url)s", s["url"], capture=True).strip().splitlines()[-1].split("|||")
                    if name and name != "NA" and curl.startswith("http"):
                        s["name"], s["channel_url"] = name, curl
                except Exception:
                    pass
                if not s.get("channel_url") or not D._region_ok(s["name"], s["title"]) or s["name"].lower() in D.OFFICIAL_CHANNELS:
                    _log(f"skipping a YouTube stream: could not identify its channel to credit")
                    continue
            before, after = clipcfg.span()
            try:   # a moment of a live stream can go to one member only
                abs_t = s.get("wall0", time.time()) + peak
                if not Claim.window(f"live:{s['platform']}:{s['login']}", abs_t - before, abs_t + after):
                    _log(f"skipped a moment of {s['name']}: another member already has it")
                    continue
            except Exception:
                pass
            title = re.sub(r"\s+", " ", s["title"]).strip()
            out = INPUT_DIR / f"{D._safe(s['name'])} - {D._safe(title)[:60]} (live {datetime.now().strftime('%H%M')}-{peak}).mp4"
            try:
                _cut(s["rec"], peak, out)
            except Exception as e:
                _log(f"cut failed for {s['name']}: {e}")
                continue
            from app.engine import safety
            ok, why = safety.check_clip(out, s["title"], s["name"])
            if not ok:
                _log(f"skipped a clip from {s['name']}: {why}")
                out.unlink(missing_ok=True)
                continue
            _log(f"safety: {why}")
            per_stream[s["login"]] = per_stream.get(s["login"], 0) + 1
            item = {"clip_id": f"live_{s['login']}_{int(time.time())}_{peak}", "source": s["platform"], "streamer": s["name"],
                    "title": title, "views": s["viewers"], "duration": sum(clipcfg.span()), "url": s["url"],
                    "channel_url": s["channel_url"], "path": str(out), "game_id": game.get("id"), "live": True}
            item["_sig"] = score
            pool.append(item)
            _log(f"candidate: {s['name']} @ {peak}s (signal {score:.1f})")
        # AI second opinion: transcribe each candidate and let Gemini score it (hook / humour / payoff); blend with the signal
        scores = {}
        try:
            from app.engine import moment_ai
            from app.engine.subtitles import transcribe_audio_to_words
            rows = []
            for it in pool:
                words = transcribe_audio_to_words(Path(it["path"]), TEMP_DIR)
                rows.append((it["clip_id"], it["title"], " ".join(w["word"].strip() for w in words)))
            scores = moment_ai.score_clips(rows, game["name"])
        except Exception as e:
            _log(f"AI scoring skipped: {e}")
        for it in pool:
            ai = scores.get(it["clip_id"])
            it["ai_score"] = ai["score"] if ai else None
            it["_final"] = 0.5 * min(it["_sig"] / 8, 1) * 100 + 0.5 * (ai["score"] if ai else 50)
            if ai:
                it["hook"] = ai["hook"]
                _log(f"AI: {it['streamer']} -> {ai['score']}/100 \"{ai['hook']}\" ({ai['reason']})")
        drop_below = max(30, clipcfg.load()["min_score"] - 20)
        results = []
        for it in sorted(pool, key=lambda x: -x["_final"]):
            ai = scores.get(it["clip_id"])
            if len(results) < want and not (ai and (not ai["safe"] or ai["score"] < drop_below)):
                results.append(it)
            elif ai and (not ai["safe"] or ai["score"] < drop_below):
                Path(it["path"]).unlink(missing_ok=True)   # unsafe or weak: not worth keeping
            else:
                try:   # good but not needed right now: keep it for a later video
                    Clip.bank({**it, "score": it["_final"], "hook": it.get("hook", ""), "reason": ""})
                    _log(f"banked for later: {it['streamer']} (score {it['_final']:.0f})")
                except Exception as e:
                    _log(f"could not bank a moment: {e}")
        for it in results:
            _log(f"clip: {it['streamer']} (final {it['_final']:.0f}) -> {Path(it['path']).name}")
        return results
    finally:
        for s in streams:
            if s.get("rec"):
                try:
                    Path(s["rec"]).unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Watch live streams for a game and cut the best moments")
    ap.add_argument("--game", default="auto")
    ap.add_argument("--clips", type=int, default=1)
    ap.add_argument("--minutes", type=float, default=8)
    ap.add_argument("--streams", type=int, default=4)
    ap.add_argument("--min-score", type=float, default=None)
    a = ap.parse_args()
    print(json.dumps(scan_live(Game.resolve(a.game), a.clips, a.minutes, a.streams, a.min_score), indent=2))
