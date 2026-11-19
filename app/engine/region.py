"""Audience-region gate: only creators from the allowed countries (CLIP_COUNTRIES, default Europe + US + Canada).

YouTube shows a channel's country on its About page, so for every YouTube stream/video we look it up (cached):
  country found + allowed      -> ok
  country found + not allowed  -> rejected (e.g. India)
  country not listed           -> accepted unless the title/name clearly points to another region
Twitch's API does not expose a creator's country, so Twitch clips are limited by stream language only.
"""
import re
import time
from typing import Dict, Optional, Tuple

import requests

from app.config import CLIP_COUNTRIES

NAMES = {"US": ["United States"], "CA": ["Canada"], "GB": ["United Kingdom"], "IE": ["Ireland"], "DE": ["Germany"], "FR": ["France"],
         "ES": ["Spain"], "IT": ["Italy"], "NL": ["Netherlands"], "BE": ["Belgium"], "SE": ["Sweden"], "NO": ["Norway"],
         "DK": ["Denmark"], "FI": ["Finland"], "PL": ["Poland"], "PT": ["Portugal"], "AT": ["Austria"], "CH": ["Switzerland"],
         "CZ": ["Czechia", "Czech Republic"], "RO": ["Romania"], "GR": ["Greece"], "HU": ["Hungary"], "IS": ["Iceland"], "LU": ["Luxembourg"]}
ALLOWED_NAMES = {n.lower() for code in CLIP_COUNTRIES for n in NAMES.get(code, [])}
# wording that clearly points to a region we do not target (used only when the channel lists no country)
OFF_REGION = re.compile(r"\b(hindi|hinglish|india|indian|desi|urdu|pakistan\w*|bangla\w*|bengali|tamil|telugu|punjabi|marathi|"
                        r"malayalam|kannada|nepali|sinhala|filipino|tagalog|indonesia\w*|vietnam\w*|thai|arabic)\b", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+1; SOCS=CAI"}
_cache: Dict[str, Tuple[Optional[str], float]] = {}


def _log(msg: str) -> None:
    print(f"[Region] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)


def _get(url: str) -> str:
    return requests.get(url, headers=HEADERS, timeout=20).text


def channel_country(channel_id: str) -> Optional[str]:
    """Country name from the channel's About page, or None if it lists none. Cached 30 days in memory and MongoDB."""
    now = time.time()
    if channel_id in _cache and now - _cache[channel_id][1] < 86400:
        return _cache[channel_id][0]
    try:
        from app.models import ChannelRegion
        doc = ChannelRegion.find_one(id=channel_id)
        if doc and now - doc.get("t", 0) < 30 * 86400:
            _cache[channel_id] = (doc.get("country"), now)
            return doc.get("country")
    except Exception:
        pass
    country = None
    try:
        m = re.search(r'"country":"([^"]+)"', _get(f"https://www.youtube.com/channel/{channel_id}/about"))
        country = m.group(1) if m else None
    except Exception:
        return None   # could not look it up this time: do not cache
    _cache[channel_id] = (country, now)
    try:
        from app.models import ChannelRegion
        ChannelRegion.set_fields(channel_id, country=country, t=now, upsert=True)
    except Exception:
        pass
    return country


def _ids_from_watch_page(video_url: str) -> Tuple[Optional[str], Optional[str]]:
    html = _get(video_url)
    m = re.search(r'"channelId":"(UC[\w-]{20,})"', html) or re.search(r'"externalChannelId":"(UC[\w-]{20,})"', html)
    n = re.search(r'"ownerChannelName":"([^"]+)"', html) or re.search(r'"author":"([^"]+)"', html)
    return (m.group(1) if m else None), (n.group(1).encode().decode("unicode_escape", "ignore") if n else None)


def check_video(video_url: str, channel_url: Optional[str] = None, title: str = "", name: str = "") -> Tuple[bool, str, Optional[str], Optional[str]]:
    """(ok, reason, channel_name, channel_url) for a YouTube video or live stream."""
    cid = None
    m = re.search(r"/channel/(UC[\w-]{20,})", channel_url or "")
    if m:
        cid = m.group(1)
    try:
        if not cid or not name or name == "YouTube":
            cid2, name2 = _ids_from_watch_page(video_url)
            cid, name = cid or cid2, (name2 or name)
    except Exception as e:
        return True, f"channel lookup failed ({type(e).__name__}) - not blocked", name or None, channel_url
    curl = f"https://www.youtube.com/channel/{cid}" if cid else channel_url
    country = channel_country(cid) if cid else None
    if country:
        if country.lower() in ALLOWED_NAMES:
            return True, f"channel is in {country}", name, curl
        return False, f"channel is in {country}", name, curl
    if OFF_REGION.search(f"{title} {name or ''}"):
        return False, "no country listed, but the title/name points to another region", name, curl
    return True, "no country listed", name, curl


def check_stream(stream: Dict) -> Tuple[bool, str]:
    """Live-scanner helper: also fills in the real channel name and link on the stream dict."""
    ok, why, name, curl = check_video(stream["url"], stream.get("channel_url"), stream.get("title", ""), stream.get("name", ""))
    if name:
        stream["name"] = name
    if curl:
        stream["channel_url"] = curl
    return ok, why
