"""Step 1: find the best recent clips for a game on Twitch and/or YouTube and download them.

The game (Twitch category + YouTube search terms) comes from the Games tab / `games` collection.
Twitch   needs TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET (free: dev.twitch.tv/console)
YouTube  works with no key (yt-dlp search). Add YOUTUBE_API_KEY (free, Google Cloud) for better
         results: real view counts, date filter and ordering.
Long YouTube videos are cut to the most-replayed 45s (or the first 45s if no replay data).
Every clip keeps its creator + channel link + original video link so videos can credit them.
Downloaded clips are stored in MongoDB (clips collection) so reruns never repeat.
"""
from app.models import Claim, Clip, Game, now
from app.engine import yt_access
import argparse
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, quote_plus

import requests

from app.config import (
    FFMPEG_BIN, INPUT_DIR, LIVE_STREAMS, LIVE_WATCH_MINUTES, TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, YOUTUBE_API_KEY,
)

HELIX = "https://api.twitch.tv/helix"
CLIP_SECONDS = 45          # length cut from long YouTube videos
YT_MAX_SOURCE = 14400      # long videos / past streams up to 4 h (only used when YouTube has "most replayed" data)
YT_NO_HEATMAP_MAX = 1800   # without replay data, longer videos are skipped (the first 45 s would be a boring intro)
# twitch/youtube/both = existing clips and videos | live = watch live streams now | all = both of the above
SOURCES = ("twitch", "youtube", "both", "live", "all")
# official publishers actively enforce copyright on their trailers - never re-upload them
OFFICIAL_CHANNELS = {"rockstar games", "playstation", "xbox", "take-two interactive", "ign", "gamespot",
                     "nintendo", "ubisoft", "ea", "electronic arts", "activision", "bethesda", "valve"}


# Region filter. Neither Twitch nor YouTube search tells us a creator's country for sure, so we combine: the
# stream language (Twitch), the channel country (YouTube, needs YOUTUBE_API_KEY) and a block on Asian/Middle-East
# scripts in the channel name or title. Best effort, not a guarantee.
NON_TARGET_SCRIPTS = re.compile("[؀-ݿऀ-෿฀-໿က-႟ក-៿"
                                "぀-ヿ㐀-䶿一-鿿가-힯]")


def _region_ok(name: str, title: str) -> bool:
    from app.engine import audience
    if audience.countries() is None:                 # this person chose All countries: no creator is blocked because of where they are
        return True
    return not NON_TARGET_SCRIPTS.search(f"{name} {title}")


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")[:80] or "clip"


def _ytdlp(*args: str, capture: bool = False, timeout: Optional[int] = 180) -> str:
    cmd = [sys.executable, "-m", "yt_dlp", "--ffmpeg-location", str(Path(FFMPEG_BIN).parent), "--js-runtimes", "node", *args]   # YouTube needs a JS runtime (node comes with n8n)
    from app.engine import yt_access
    from app.utils.proc_util import NEW_GROUP, kill_tree
    import contextlib
    # YouTube often refuses a cloud server ("Sign in to confirm you're not a bot"): the owner's proxy (Settings -> YouTube access) is used for YouTube only
    with (yt_access.ytdlp_args() if yt_access.uses_youtube(args) else contextlib.nullcontext([])) as extra:
        cmd[3:3] = extra
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **NEW_GROUP)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(p)   # yt-dlp and the ffmpeg it started
            p.communicate()
            raise RuntimeError(f"timed out after {timeout}s")
    if p.returncode != 0:
        if yt_access.looks_blocked(err):
            yt_access.note_block(err.strip().splitlines()[-1] if err.strip() else "")
            raise yt_access.YouTubeBlocked(yt_access.OWNER_MESSAGE)
        lines = [l for l in (err or "").strip().splitlines() if l.strip()]
        errs = [l for l in lines if l.startswith("ERROR")]    # the last two lines are often only warnings: show the real error first
        raise RuntimeError("yt-dlp: " + " ".join((errs[-1:] + [l for l in lines[-2:] if l not in errs[-1:]]) if errs else lines[-2:])[:400])
    return out if capture else ""


# ------------------------------------------------------------------ Twitch
def _twitch_headers() -> Dict:
    if not (TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET):
        raise RuntimeError("Twitch keys missing: set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in Settings.")
    r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30,
                      params={"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET,
                              "grant_type": "client_credentials"})
    r.raise_for_status()
    return {"Client-Id": TWITCH_CLIENT_ID, "Authorization": f"Bearer {r.json()['access_token']}"}


def twitch_category_id(category: str, hdr: Optional[Dict] = None) -> Optional[str]:
    hdr = hdr or _twitch_headers()
    g = requests.get(f"{HELIX}/games", params={"name": category}, headers=hdr, timeout=30)
    g.raise_for_status()
    data = g.json().get("data", [])
    return data[0]["id"] if data else None


def twitch_check(category: str) -> Tuple[bool, str]:
    """For the Games tab 'Test' button."""
    cats = split_terms(category)
    if not cats:
        return False, "No Twitch category set for this game (Twitch skipped)."
    try:
        hdr = _twitch_headers()
        missing = [c for c in cats if not twitch_category_id(c, hdr)]
        if missing:
            return False, f"Twitch has no category named {', '.join(repr(m) for m in missing)}. Check the exact spelling on twitch.tv/directory."
        return True, f"{len(cats)} categor{'y' if len(cats) == 1 else 'ies'} found on Twitch."
    except Exception as e:
        return False, str(e)[:200]


def split_terms(text: str, limit: int = 8) -> List[str]:
    """A game can have several searches / categories: one per line (or separated by | or ;)."""
    out: List[str] = []
    for part in re.split(r"[\n|;]+", text or ""):
        part = part.strip()
        if part and part.lower() not in [o.lower() for o in out]:
            out.append(part)
    return out[:limit]


def twitch_candidates(category: str, hours: int, min_views: int, min_s: int, max_s: int) -> List[Dict]:
    cats = split_terms(category)
    if not cats:
        raise RuntimeError("this game has no Twitch category")
    out, seen, errs = [], set(), []
    for c in cats:
        try:
            rows = _twitch_candidates_one(c, hours, min_views, min_s, max_s)
        except Exception as e:
            errs.append(str(e)[:150])
            continue
        for r in rows:
            if r["clip_id"] not in seen:
                seen.add(r["clip_id"])
                out.append(r)
    if not out and errs:
        raise RuntimeError(errs[0])
    return out


def _twitch_candidates_one(category: str, hours: int, min_views: int, min_s: int, max_s: int) -> List[Dict]:
    if not category:
        raise RuntimeError("this game has no Twitch category")
    hdr = _twitch_headers()
    gid = twitch_category_id(category, hdr)
    if not gid:
        raise RuntimeError(f"Twitch has no category named '{category}'. Fix it on the Games tab.")
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(f"{HELIX}/clips", headers=hdr, timeout=30,
                     params={"game_id": gid, "started_at": since, "first": 100})
    r.raise_for_status()
    from app.engine import audience
    clips = [c for c in r.json().get("data", []) if c["view_count"] >= min_views and min_s <= c["duration"] <= max_s
             and audience.language_ok(c.get("language"))                    # this person's stream languages (All = every language, even when Twitch lists none)
             and _region_ok(c["broadcaster_name"], c["title"])]
    logins: Dict[str, str] = {}
    ids = list({c["broadcaster_id"] for c in clips})[:100]
    if ids:
        u = requests.get(f"{HELIX}/users", headers=hdr, timeout=30, params=[("id", i) for i in ids])
        if u.ok:
            logins = {x["id"]: x["login"] for x in u.json().get("data", [])}
    return [{"clip_id": c["id"], "source": "twitch", "streamer": c["broadcaster_name"], "title": c["title"],
             "views": c["view_count"], "duration": c["duration"], "url": c["url"],
             "channel_url": f"https://www.twitch.tv/{logins[c['broadcaster_id']]}" if c["broadcaster_id"] in logins else None}
            for c in clips]


# ----------------------------------------------------------------- YouTube
def _iso_seconds(d: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return dd * 86400 + h * 3600 + mi * 60 + s


def _youtube_api(query: str, hours: int) -> List[Dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=30, params={
        "part": "snippet", "type": "video", "q": query, "order": "viewCount", "maxResults": 40,
        "publishedAfter": since, "key": YOUTUBE_API_KEY, "videoEmbeddable": "any",
        "regionCode": "US", "relevanceLanguage": "en"})
    s.raise_for_status()
    ids = [i["id"]["videoId"] for i in s.json().get("items", [])]
    if not ids:
        return []
    v = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={
        "part": "contentDetails,statistics,snippet", "id": ",".join(ids), "key": YOUTUBE_API_KEY})
    v.raise_for_status()
    items = v.json().get("items", [])
    countries: Dict[str, str] = {}
    cids = list({i["snippet"]["channelId"] for i in items})[:50]
    if cids:  # channel country (only set when the creator filled it in)
        ch = requests.get("https://www.googleapis.com/youtube/v3/channels", timeout=30,
                          params={"part": "snippet", "id": ",".join(cids), "key": YOUTUBE_API_KEY})
        if ch.ok:
            countries = {c["id"]: (c["snippet"].get("country") or "").upper() for c in ch.json().get("items", [])}
    out = []
    for i in items:
        sn = i["snippet"]
        country = countries.get(sn["channelId"], "")
        lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower().split("-")[0]
        from app.engine import audience
        if (country and not audience.country_ok(country)) or (lang and not audience.language_ok(lang)):
            continue
        out.append({"vid": i["id"], "title": sn["title"], "channel": sn["channelTitle"],
                    "channel_url": f"https://www.youtube.com/channel/{sn['channelId']}",
                    "views": int(i["statistics"].get("viewCount", 0)),
                    "duration": _iso_seconds(i["contentDetails"]["duration"])})
    return out


def _youtube_ytdlp(query: str, hours: int) -> List[Dict]:
    """Key-free search: YouTube results page, filtered by upload date and sorted by view count."""
    day = 2 if hours <= 24 else 3 if hours <= 168 else 4   # today / this week / this month
    sp = quote(base64.b64encode(bytes([0x08, 0x03, 0x12, 0x04, 0x08, day, 0x10, 0x01])).decode(), safe="")
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={quote(sp, safe='')}"
    out = _ytdlp("--flat-playlist", "-J", "--playlist-end", "40", url, capture=True)
    return [{"vid": e["id"], "title": e.get("title") or "video", "channel": e.get("channel") or e.get("uploader") or "YouTube",
             "channel_url": e.get("channel_url") or e.get("uploader_url"),
             "views": int(e.get("view_count") or 0), "duration": int(e.get("duration") or 0)}
            for e in json.loads(out).get("entries", []) if e and e.get("id")]


def youtube_candidates(query: str, hours: int, min_views: int, min_s: int) -> List[Dict]:
    queries = split_terms(query)
    if not queries:
        raise RuntimeError("this game has no YouTube search terms")
    out, seen, errs = [], set(), []
    for q in queries:
        try:
            rows = _youtube_candidates_one(q, hours, min_views, min_s)
        except Exception as e:
            errs.append(str(e)[:150])
            continue
        for r in rows:
            if r["clip_id"] not in seen:
                seen.add(r["clip_id"])
                out.append(r)
    if not out and errs:
        raise RuntimeError(errs[0])
    print(f"[Discovery] YouTube: {len(queries)} search(es) -> {len(out)} candidate(s)")
    return out


def _youtube_candidates_one(query: str, hours: int, min_views: int, min_s: int) -> List[Dict]:
    if not query:
        raise RuntimeError("this game has no YouTube search terms")
    raw = _youtube_api(query, hours) if YOUTUBE_API_KEY else _youtube_ytdlp(query, hours)
    if not raw:   # YouTube sometimes answers with an empty page: try once more
        import time as _t
        _t.sleep(4)
        raw = _youtube_api(query, hours) if YOUTUBE_API_KEY else _youtube_ytdlp(query, hours)
    rows = [{"clip_id": f"yt_{r['vid']}", "source": "youtube", "streamer": r["channel"], "title": r["title"],
             "views": r["views"], "duration": r["duration"], "channel_url": r.get("channel_url"),
             "url": f"https://www.youtube.com/watch?v={r['vid']}"}
            for r in raw if (r["views"] >= min_views or r["views"] == 0) and min_s <= r["duration"] <= YT_MAX_SOURCE
            and r["channel"].lower().strip() not in OFFICIAL_CHANNELS and _region_ok(r["channel"], r["title"])]
    print(f"[Discovery] YouTube search '{query[:40]}' ({hours} h): {len(raw)} results, {len(rows)} usable")
    return rows


def youtube_check(query: str) -> Tuple[bool, str]:
    """For the Games tab 'Test' button."""
    try:
        c = youtube_candidates(query, 168, 0, 10)
        return (True, f"{len(c)} recent videos found (top: {c[0]['title'][:60]}).") if c else (
            False, "No recent videos found. Try different search terms.")
    except Exception as e:
        return False, str(e)[:200]

# ------------------------------------------------------------ a creator chosen by name (instead of searching by game)
TWITCH_LOGIN = re.compile(r"^[A-Za-z0-9_]{3,25}$")
YT_CHANNEL = re.compile(r"^https://(?:www\.|m\.)?youtube\.com/(@[\w.\-]{3,60}|channel/UC[\w\-]{20,24}|c/[\w.\-]{2,60}|user/[\w.\-]{2,60})(?:[/?#].*)?$")


def parse_creator(platform: str, text: str) -> Tuple[str, str]:
    """What the member typed -> ("twitch", login) or ("youtube", channel page URL). Raises ValueError with a plain message."""
    t = (text or "").strip()
    if not t or len(t) > 200:
        raise ValueError("Type the creator's name or paste a link to their channel.")
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]{3,25})(?:[/?#]|$)", t, re.I)
    if m:
        return "twitch", m.group(1).lower()
    plat = (platform or "").strip().lower()
    if re.search(r"(youtube\.com|youtu\.be)/", t, re.I):
        plat = "youtube"
    if plat not in ("twitch", "youtube"):
        raise ValueError("Choose Twitch or YouTube for the creator.")
    if plat == "twitch":
        login = t.lstrip("@").strip()
        if not TWITCH_LOGIN.match(login):
            raise ValueError("That is not a Twitch name. Use the name from twitch.tv/<name> (letters, numbers and _).")
        return "twitch", login.lower()
    if re.match(r"^https?://", t):
        m = YT_CHANNEL.match(t.replace("http://", "https://", 1))
        if not m:
            raise ValueError("Paste a YouTube channel link like https://www.youtube.com/@name (a video link is not a channel).")
        return "youtube", "https://www.youtube.com/" + m.group(1)
    handle = re.sub(r"[^\w.\-]", "", t.lstrip("@"))     # "Some Name" -> @SomeName
    if len(handle) < 3:
        raise ValueError("That channel name is too short. Use the @name from their channel page, or paste the link.")
    return "youtube", f"https://www.youtube.com/@{handle}"


def _twitch_user(login: str, hdr: Dict) -> Dict:
    u = requests.get(f"{HELIX}/users", headers=hdr, timeout=30, params={"login": login})
    u.raise_for_status()
    data = u.json().get("data", [])
    if not data:
        raise RuntimeError(f"Twitch has no streamer named '{login}'. Check the spelling on twitch.tv/{login}.")
    return data[0]


def _yt_channel_entries(base: str, tab: str, n: int) -> Dict:
    return json.loads(_ytdlp("--flat-playlist", "-J", "--playlist-end", str(n), f"{base}/{tab}", capture=True, timeout=90))


def resolve_creator(platform: str, text: str) -> Dict:
    """Find the creator and say who was matched (shown on the Create page before anything is made)."""
    plat, ident = parse_creator(platform, text)
    if plat == "twitch":
        u = _twitch_user(ident, _twitch_headers())
        return {"platform": "twitch", "name": u["display_name"], "url": f"https://www.twitch.tv/{u['login']}", "description": (u.get("description") or "")[:140]}
    try:
        info = _yt_channel_entries(ident, "videos", 1)
    except RuntimeError as e:
        raise RuntimeError(f"No YouTube channel found at {ident}. Paste the link from their channel page. ({str(e)[-120:]})")
    name = info.get("channel") or info.get("uploader") or (info.get("title") or "").replace(" - Videos", "")
    if not name:
        raise RuntimeError(f"No YouTube channel found at {ident}.")
    return {"platform": "youtube", "name": name, "url": info.get("channel_url") or info.get("uploader_url") or ident, "description": ""}


def creator_candidates(platform: str, text: str, hours: int, min_views: int, min_s: int, max_s: int) -> List[Dict]:
    """The creator's own recent Twitch clips, or recent videos / stream replays on their YouTube channel. No region or language filter:
    the member chose this creator on purpose."""
    plat, ident = parse_creator(platform, text)
    if plat == "twitch":
        hdr = _twitch_headers()
        u = _twitch_user(ident, hdr)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(f"{HELIX}/clips", headers=hdr, timeout=30, params={"broadcaster_id": u["id"], "started_at": since, "first": 100})
        r.raise_for_status()
        clips = [c for c in r.json().get("data", []) if c["view_count"] >= min_views and min_s <= c["duration"] <= max_s]
        games: Dict[str, str] = {}
        gids = list({c["game_id"] for c in clips if c.get("game_id")})[:100]
        if gids:
            g = requests.get(f"{HELIX}/games", headers=hdr, timeout=30, params=[("id", i) for i in gids])
            if g.ok:
                games = {x["id"]: x["name"] for x in g.json().get("data", [])}
        rows = [{"clip_id": c["id"], "source": "twitch", "streamer": c["broadcaster_name"], "title": c["title"], "views": c["view_count"],
                 "duration": c["duration"], "url": c["url"], "channel_url": f"https://www.twitch.tv/{u['login']}", "game_name": games.get(c.get("game_id"), "")}
                for c in clips]
        rows.sort(key=lambda r: -r["views"])
        print(f"[Creator] Twitch {u['display_name']} ({hours} h): {len(rows)} usable clip(s)", flush=True)
        return rows
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    rows, seen, last_err = [], set(), None
    for tab in ("videos", "streams"):
        try:
            info = _yt_channel_entries(ident, tab, 25)
        except RuntimeError as e:
            last_err = e
            continue
        cname = info.get("channel") or info.get("uploader") or "YouTube"
        for e in info.get("entries") or []:
            if not e or not e.get("id") or e["id"] in seen:
                continue
            ts = e.get("timestamp")
            dur = int(e.get("duration") or 0)
            if (ts and ts < cutoff) or not (min_s <= dur <= YT_MAX_SOURCE):
                continue
            seen.add(e["id"])
            rows.append({"clip_id": f"yt_{e['id']}", "source": "youtube", "streamer": e.get("channel") or cname, "title": e.get("title") or "video",
                         "views": int(e.get("view_count") or 0), "duration": dur, "url": f"https://www.youtube.com/watch?v={e['id']}",
                         "channel_url": info.get("channel_url") or ident})
    if not rows and last_err:
        raise RuntimeError(f"Could not read the YouTube channel {ident}: {str(last_err)[-150:]}")
    print(f"[Creator] YouTube {ident} ({hours} h): {len(rows)} usable video(s)", flush=True)
    return rows


def _best_window(info: Dict, length: int) -> Optional[tuple]:
    """Start/end (s) of the most-replayed `length` seconds, or the first `length` seconds."""
    dur = float(info.get("duration") or 0)
    if dur <= length + 15:
        return None  # short enough: take it all
    heat = info.get("heatmap") or []
    if heat:
        peak = max(heat, key=lambda h: h.get("value", 0))
        centre = (peak["start_time"] + peak["end_time"]) / 2
        start = min(max(0.0, centre - length / 2), dur - length)
    else:
        start = 0.0
    return round(start, 1), round(start + length, 1)


# ---------------------------------------------------------------- download
def _peak_windows(info: Dict, length: int, n: int = 3) -> List[tuple]:
    """The n most-replayed, non-overlapping windows of a video: [(start, end, score)]."""
    dur = float(info.get("duration") or 0)
    if dur <= length + 15:
        return []
    out: List[tuple] = []
    for h in sorted(info.get("heatmap") or [], key=lambda h: -h.get("value", 0)):
        centre = (h["start_time"] + h["end_time"]) / 2
        start = min(max(0.0, centre - length / 2), dur - length)
        if all(abs(start - w[0]) >= length for w in out):
            out.append((round(start, 1), round(start + length, 1), round(100 * h.get("value", 0))))
        if len(out) >= n:
            break
    return out


def _fetch(url: str, key: str, win: Optional[tuple], dur: float, out: Path) -> None:
    """Download `win` (start, end) of a YouTube video into `out` (the whole video when win is None)."""
    # downloading only the wanted part is much faster than the whole video (YouTube throttles full downloads)
    args = ["-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[ext=mp4]/b", "--merge-output-format", "mp4"]
    if win:
        args += ["--download-sections", f"*{win[0]}-{win[1]}", "--force-keyframes-at-cuts"]
    _ytdlp(*args, "--no-playlist", "--force-overwrites", "-o", str(out), url, timeout=300)
    if not out.exists():
        raise RuntimeError(f"yt-dlp finished but {out} is missing")


def download_candidate(c: Dict, out_dir: Path = INPUT_DIR, game_name: str = "", game_id: Optional[str] = None) -> Path:
    """Download to 'Streamer - Title.mp4' (the name format pipeline.py expects).
    A long video with several good moments is cut ONCE for this run; the other moments go into the clip bank for later videos."""
    import time as _t
    out = out_dir / f"{_safe(c['streamer'])} - {_safe(c['title'])}.mp4"
    print(f"[Discovery] downloading: {c['streamer']} - {c['title'][:55]} ({int(c.get('duration') or 0) // 60} min video)", flush=True)
    t_start = _t.time()
    if c["source"] == "youtube":
        info = json.loads(_ytdlp("-J", "--no-playlist", c["url"], capture=True, timeout=90))
        if int(info.get("age_limit") or 0) >= 18 and __import__("app.engine.safety", fromlist=["x"]).enabled():
            raise RuntimeError("age-restricted video - skipped")
        dur = float(info.get("duration") or 0)
        from app.engine import clipcfg
        cfg = clipcfg.load()
        L, per = cfg["clip_seconds"], cfg["moments_per_video"]
        wins: List[Optional[tuple]] = []   # (start, end, score, hook)
        if dur <= L + 15:
            wins = [None]
        elif info.get("heatmap"):
            wins = [(s_, e_, sc, "") for s_, e_, sc in _peak_windows(info, L, per)]
        else:
            try:
                from app.engine import moment_ai
                wins = [(m["start"], m["end"], m["score"], m["hook"]) for m in moment_ai.pick_windows(c["url"], dur, game_name or "the game", n=per)]
            except Exception as e:
                print(f"[Moments] AI pick skipped: {e}")
            if not wins and dur > YT_NO_HEATMAP_MAX:
                raise RuntimeError("long video without 'most replayed' data or usable captions - skipped")
            if not wins:
                wins = [(0.0, float(L), 40, "")]
        first = wins[0]
        _fetch(c["url"], c["clip_id"], None if first is None else (first[0], first[1]), dur, out)
        extra = 0
        for w in wins[1:]:
            try:
                Clip.bank({"clip_id": f"{c['clip_id']}_w{int(w[0])}", "source": "youtube", "streamer": c["streamer"], "title": c["title"],
                                "views": c.get("views", 0), "duration": int(w[1] - w[0]), "url": c["url"], "channel_url": c.get("channel_url"),
                                "game_id": game_id, "window": [w[0], w[1]], "src_duration": dur, "score": w[2], "hook": w[3], "path": None})
                extra += 1
            except Exception:
                pass
        if extra:
            print(f"[Bank] kept {extra} more moment(s) from this video for later videos", flush=True)
    else:
        _ytdlp("-f", "best[ext=mp4]/best", "--merge-output-format", "mp4", "--no-playlist", "--force-overwrites", "-o", str(out), c["url"], timeout=300)
        if not out.exists():
            raise RuntimeError(f"yt-dlp finished but {out} is missing")
    print(f"[Discovery] downloaded in {int(_t.time() - t_start)} s", flush=True)
    return out


def _from_bank(game: Dict, count: int) -> List[Dict]:
    """Use moments saved earlier (best score first) before searching for anything new."""
    from app.engine import safety
    try:
        dropped = Clip.expire_banked()
        if dropped:
            print(f"[Bank] dropped {dropped} moment(s) past their keep-time", flush=True)
    except Exception:
        pass
    found: List[Dict] = []
    for doc in Clip.banked_for(game.get("id"), limit=count * 3):
        if len(found) >= count:
            break
        cid, path = doc["_id"], None
        if doc.get("path") and Path(doc["path"]).is_file():
            path = Path(doc["path"])
        elif doc.get("window"):
            path = INPUT_DIR / f"{_safe(doc['streamer'])} - {_safe(doc['title'])[:60]} (bank {abs(hash(cid)) % 10000}).mp4"
            try:
                print(f"[Bank] fetching a saved moment: {doc['streamer']} ({int(doc['window'][0])}s-{int(doc['window'][1])}s, score {doc.get('score', 0):.0f})", flush=True)
                _fetch(doc["url"], f"b{abs(hash(cid)) % 100000}", tuple(doc["window"]), float(doc.get("src_duration") or 0), path)
            except yt_access.YouTubeBlocked:   # YouTube is refusing right now, the moment itself is fine: keep it for later
                print("[Bank] YouTube is refusing this server: saved moments kept for later", flush=True)
                break
            except Exception as e:
                print(f"[Bank] could not fetch {cid}: {str(e)[:100]}", flush=True)
                Clip.update_where(id=cid, fields={"status": "expired", "reject_reason": "download failed"})
                continue
        else:
            Clip.update_where(id=cid, fields={"status": "expired"})
            continue
        print(f"[Bank] using a saved moment (score {doc.get('score', 0):.0f}): {doc['streamer']} - {doc.get('hook') or doc['title'][:50]}", flush=True)
        print("[Safety] checking the clip (about a minute)...", flush=True)
        ok, why = safety.check_clip(path, doc.get("title", ""), doc.get("streamer", ""))
        if not ok:
            print(f"[Safety] skipped banked clip {cid}: {why}", flush=True)
            Clip.update_where(id=cid, fields={"status": "rejected", "reject_reason": why})
            path.unlink(missing_ok=True)
            continue
        print(f"[Safety] {cid}: {why}", flush=True)
        Clip.update_where(id=cid, fields={"status": "downloaded", "path": str(path)})
        found.append({"clip_id": cid, "source": doc.get("source", "youtube"), "streamer": doc["streamer"], "title": doc["title"], "views": doc.get("views", 0),
                      "duration": doc.get("duration") or 0, "url": doc.get("url"), "channel_url": doc.get("channel_url"), "path": str(path),
                      "game_id": doc.get("game_id"), "hook": doc.get("hook", "")})
    return found


def _interleave(lists: List[List[Dict]]) -> List[Dict]:
    out = []
    for i in range(max((len(l) for l in lists), default=0)):
        out += [l[i] for l in lists if i < len(l)]
    return out


def _last_clip_was_clip() -> bool:
    """For 'all' with one clip wanted: go live every other run (the last downloaded clip was not a live one)."""
    try:
        last = (Clip.find_all(order=("-created_at",), limit=1) or [None])[0]
        return not (last and str(last["_id"]).startswith("live_"))
    except Exception:
        return True


def _with_want(query: str) -> str:
    """When the member asked for a certain kind of moment ('fights', 'reactions' ...), search for that first: '<game search> fight', '<game search> brawl' ..."""
    from app.engine import clipcfg
    w = clipcfg.want()
    base = split_terms(query)
    if not w or not base:
        return query
    words = clipcfg.want_words(w)[:3]
    return "\n".join([f"{base[0]} {x}" for x in words] + base)


def _steer(cands: List[Dict], game: Dict) -> List[Dict]:
    """Put the candidates that look like the wanted kind of moment first. Titles only (a few hundred tokens): the AI rates how well each title fits,
    plus a bonus for the wanted words. 'Only this' also drops the ones the AI says do not fit (as long as at least three remain)."""
    from app.engine import clipcfg
    w = clipcfg.want()
    if not w or not cands:
        return cands
    words, pool = clipcfg.want_words(w), cands[:40]
    scores: Dict[str, int] = {}
    try:
        from app.engine import moment_ai
        scores = {k: v["score"] for k, v in moment_ai.score_clips([(c["clip_id"], c.get("title", ""), "") for c in pool], game.get("name") or "the game").items()}
    except Exception:
        scores = {}

    def rank(c):
        return scores.get(c["clip_id"], 50) + 15 * sum(1 for x in words if x in (c.get("title") or "").lower())
    ordered = sorted(pool, key=rank, reverse=True) + cands[40:]
    if w["strict"]:
        keep = [c for c in ordered if rank(c) >= 45]
        if len(keep) >= 3:
            ordered = keep
    print(f"[Want] {clipcfg.want_summary(w)}: {len(ordered)} of {len(cands)} candidates kept, best matches first", flush=True)
    return ordered


def discover_and_download(count: int = 6, hours: int = 24, source: str = "both", min_views: int = 0,
                          min_seconds: int = 10, max_seconds: int = 60, game: Optional[Dict] = None,
                          creator: Optional[Dict] = None) -> List[Dict]:
    """Download up to `count` new top clips for `game`.
    Returns [{path, streamer, title, views, clip_id, url, channel_url, source, game_id}]."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    game = game or Game.default_data()
    wanted = ["twitch", "youtube"] if source in ("both", "all") else ([] if source == "live" else [source])
    ranked, errors = [], []
    if creator:                              # a creator chosen by name: only their clips (not the game search, the bank or live streams)
        wanted = []
    from app.engine import clipcfg
    # Where this account wants its clips to come from (Settings -> Clip sources). Asking for a place the account switched off is refused
    # with a clear message, never quietly changed to another one.
    allowed = clipcfg.sources()
    if not creator:
        if source in ("twitch", "youtube") and source not in allowed:
            raise RuntimeError(f"{ {'twitch': 'Twitch', 'youtube': 'YouTube'}[source] } is switched off in your Settings -> Clip sources. Switch it on there, or choose another source.")
        wanted = [s for s in wanted if s in allowed]
    _w = clipcfg.want()
    if _w:
        print(f"[Want] this video: {clipcfg.want_summary(_w)} ({'only this' if _w['strict'] else 'prefer this'})", flush=True)
    results = [] if (creator or (_w and _w["strict"])) else _from_bank(game, count)      # saved moments were not picked for this request
    if len(results) >= count:
        return results
    live_n = 0
    if source in ("live", "all") and not creator:
        live_n = count if source == "live" else (max(1, count // 3) if count > 1 else (1 if _last_clip_was_clip() else 0))
    for s in wanted:
        try:
            cands = (twitch_candidates(game.get("twitch_category", ""), hours, min_views, min_seconds, max_seconds)
                     if s == "twitch" else youtube_candidates(_with_want(game.get("youtube_query", "")), hours, min_views, min_seconds))
            seen = Clip.known_ids([c["clip_id"] for c in cands])
            fresh = sorted((c for c in cands if c["clip_id"] not in seen), key=lambda c: (int(c.get("duration") or 0) > 2400, -c["views"]))
            fresh = _steer(fresh, game)
            print(f"[Discovery] {game['name']} / {s}: {len(fresh)} new candidate(s)")
            ranked.append(fresh)
        except Exception as e:
            errors.append(f"{s}: {e}")
            print(f"[Discovery] {s} unavailable - {e}")
    if creator:
        try:
            cands = creator_candidates(creator["platform"], creator["name"], hours, min_views, min_seconds, max_seconds)
            seen = Clip.known_ids([c["clip_id"] for c in cands])
            fresh = [c for c in cands if c["clip_id"] not in seen]
            if not fresh:
                raise RuntimeError(f"No new usable clips from {creator['name']} in the last {hours} h.")
            fresh = _steer(fresh, game)
            print(f"[Discovery] creator {creator['name']}: {len(fresh)} new candidate(s)", flush=True)
            ranked.append(fresh)
        except Exception as e:
            errors.append(str(e))
            print(f"[Discovery] creator unavailable - {e}", flush=True)
    if live_n:
        try:
            from app.engine import live_scanner
            for item in live_scanner.scan_live(game, live_n, LIVE_WATCH_MINUTES, LIVE_STREAMS, platforms=allowed):
                Clip.save_downloaded(item)
                results.append(item)
        except Exception as e:
            errors.append(f"live: {e}")
            print(f"[Discovery] live unavailable - {e}")
    if not ranked and not results:
        raise RuntimeError("No source available. " + " | ".join(errors))

    attempts = 0
    queue, yt_blocked = _interleave(ranked), False
    while queue:
        c = queue.pop(0)
        if len(results) >= count:
            break
        attempts += 1
        if attempts > 8:
            print("[Discovery] tried 8 candidates without success - stopping this round", flush=True)
            break
        print(f"[Discovery] candidate {attempts}", flush=True)
        if c.get("source") == "youtube" and not creator:
            from app.engine import region
            try:
                r_ok, r_why, r_name, r_url = region.check_video(c["url"], c.get("channel_url"), c.get("title", ""), c.get("streamer", ""))
            except yt_access.YouTubeBlocked:
                yt_blocked = True
                print("[Discovery] YouTube is refusing this server: stopping", flush=True)
                break
            if not r_ok:
                print(f"[Region] skipped {c['streamer']}: {r_why}", flush=True)
                try:
                    Clip.set_fields(c["clip_id"], status="rejected", reject_reason=r_why, title=c["title"], streamer=c["streamer"],
                                    source="youtube", created_at=now(), upsert=True)
                except Exception:
                    pass
                attempts -= 1   # a rejected region does not count as a failed attempt
                continue
            if r_name:
                c["streamer"] = r_name
            if r_url:
                c["channel_url"] = r_url
        try:
            if not Claim.source(c["clip_id"]):   # another member got this source first: every post must be unique
                print(f"[Claim] {c['clip_id']} already belongs to another member - skipped", flush=True)
                attempts -= 1
                continue
        except Exception:
            pass
        try:
            path = download_candidate(c, game_name=game.get("name", ""), game_id=game.get("id"))
        except yt_access.YouTubeBlocked:   # not this clip's fault, and every next one would fail the same way: stop here, say why
            yt_blocked = True
            print("[Discovery] YouTube is refusing this server: stopping", flush=True)
            try:
                Claim.release(c["clip_id"])
            except Exception:
                pass
            break
        except Exception as e:  # one bad clip must not kill the batch
            print(f"[Discovery] skip {c['clip_id']}: {e}")
            try:
                Claim.release(c["clip_id"])   # nothing was made from it, so it stays available
            except Exception:
                pass
            continue
        from app.engine import safety
        print("[Safety] checking the clip (about a minute)...", flush=True)
        ok, why = safety.check_clip(path, c.get("title", ""), c.get("streamer", ""))
        item = {**c, "path": str(path), "game_id": game.get("id")}
        Clip.save_downloaded(item)
        if not ok:
            print(f"[Safety] skipped {c['clip_id']}: {why}")
            try:
                Clip.set_fields(c["clip_id"], status="rejected", reject_reason=why)
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
            continue
        print(f"[Safety] {c['clip_id']}: {why}")
        results.append(item)
        print(f"[Discovery] {c['source']:<7} {c['views']:>8} views  {path.name}")
    if not results and yt_blocked:
        raise RuntimeError(yt_access.OWNER_MESSAGE)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Download top clips for a game from Twitch and/or YouTube")
    ap.add_argument("--game", default="auto", help="game id from the Games tab (default: auto)")
    ap.add_argument("--source", choices=SOURCES, default="both")
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--min-views", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(discover_and_download(a.count, a.hours, a.source, min_views=a.min_views,
                                           game=Game.resolve(a.game)), indent=2))
