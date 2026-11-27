"""Story videos: what is trending right now, so the studio makes the kind of story people are watching this week.

For each genre of short story video the studio asks YouTube for the most viewed Shorts of the last 7 days, measures how fast they are growing (views per hour since
they were published) and ranks the genres. One look is shared by every member and kept for 12 hours, so the YouTube allowance is used once for everybody.
The titles that are doing best are only read to see WHAT is working (the theme, the kind of hook): the story ideas that come out are original, never a copy.

Without a YouTube key (or when the allowance is used up) the genres are listed without numbers and the page says so.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

GENRES = [  # id, name shown, what YouTube is asked, what the genre is
    ("scary", "Scary stories", "scary story", "A short horror or creepy story with a twist."),
    ("what_if", "What if...", "what if scenario", "An imagined 'what if' that plays out in a surprising way."),
    ("mystery", "Mysteries", "mystery story unsolved", "A strange case where the answer is revealed at the end."),
    ("funny", "Funny stories", "funny animated story", "A short comedy with a punchline."),
    ("motivation", "Motivation", "motivational story", "A small story with a lesson that sticks."),
    ("history", "Untold history", "untold history story", "A true-sounding history tale told like a story."),
]
CACHE_HOURS = 12
SEARCH_COST = 100                       # YouTube quota units of one search
LIST_COST = 1


def genre_ids() -> List[str]:
    return [g[0] for g in GENRES]


def genre(gid: str) -> Optional[tuple]:
    return next((g for g in GENRES if g[0] == gid), None)


def _store():
    from app.models import System
    return System


def cached(max_age_hours: float = CACHE_HOURS) -> Optional[Dict]:
    from app.models import raw
    d = raw(_store().objects(id="story_trends").first())
    if d and d.get("t") and time.time() - float(d["t"]) < max_age_hours * 3600:
        return d.get("data")
    return None


def _save(data: Dict) -> None:
    _store().objects(id="story_trends").update_one(upsert=True, set__t=time.time(), set__data=data)


def _age_hours(published: str) -> float:
    try:
        t = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        return max(1.0, (datetime.now(timezone.utc) - t).total_seconds() / 3600.0)
    except Exception:
        return 24.0


def _search(key: str, query: str) -> List[Dict]:
    import requests
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=30, params={"part": "snippet", "type": "video", "q": query, "order": "viewCount", "maxResults": 15,
                                                                                         "publishedAfter": since, "videoDuration": "short", "key": key})
    s.raise_for_status()
    items = [(i["id"]["videoId"], i["snippet"]) for i in s.json().get("items", []) if i.get("id", {}).get("videoId")]
    if not items:
        return []
    v = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={"part": "statistics", "id": ",".join(i for i, _ in items), "key": key})
    v.raise_for_status()
    stats = {x["id"]: x.get("statistics") or {} for x in v.json().get("items", [])}
    return [{"id": vid, "title": sn.get("title") or "", "channel": sn.get("channelTitle") or "", "views": int((stats.get(vid) or {}).get("viewCount") or 0), "published": sn.get("publishedAt")} for vid, sn in items]


def rank_genre(rows: List[Dict]) -> Dict:
    """How well this genre is doing: the middle value of the views per hour of its best Shorts (the middle value, so one lucky video does not decide), and the best titles."""
    for r in rows:
        r["vph"] = round(r["views"] / _age_hours(r.get("published")), 1)
    top = sorted(rows, key=lambda r: -r["vph"])[:10]
    vphs = sorted(r["vph"] for r in top)
    mid = vphs[len(vphs) // 2] if vphs else 0.0
    return {"score": round(mid, 1), "videos": len(rows), "titles": [{"title": r["title"], "views": r["views"], "vph": r["vph"]} for r in top[:6]]}


def trends(force: bool = False, key: Optional[str] = None, search=None) -> Dict:
    """{"live": bool, "message", "genres": [{id, name, about, score, videos, titles}] best first}. One look for every member (kept for 12 hours)."""
    if not force:
        c = cached()
        if c:
            return c
    key = key if key is not None else _key()
    out = {"live": False, "message": "", "genres": [{"id": g[0], "name": g[1], "about": g[3], "score": 0.0, "videos": 0, "titles": []} for g in GENRES], "at": time.time()}
    if not key:
        out["message"] = "No YouTube Data API key is saved, so the trend numbers are not available. Add the key in Settings -> Accounts & keys. You can still choose a genre yourself."
        return out
    search = search or _search
    from app.services import youtube_service as yt
    need = len(GENRES) * (SEARCH_COST + LIST_COST)
    try:
        if yt.quota_left() < need + 500:
            out["message"] = "YouTube's daily allowance is nearly used up, so the trend numbers are not refreshed today. You can still choose a genre yourself."
            return out
    except Exception:
        pass
    got = 0
    for g in out["genres"]:
        gd = genre(g["id"])
        try:
            rows = search(key, gd[2])
            try:
                yt.quota_use(SEARCH_COST + LIST_COST)
            except Exception:
                pass
        except Exception as e:
            print(f"[Stories] trend look for '{g['id']}' failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
            continue
        g.update(rank_genre(rows))
        got += 1
    out["genres"].sort(key=lambda g: -g["score"])
    out["live"] = got > 0
    out["message"] = (f"Looked at the most viewed Shorts of the last 7 days in {got} genres." if got else "YouTube did not answer, so the trend numbers are not available right now.")
    if got:
        _save(out)
    return out


def _key() -> str:
    import os
    from app.utils.envfile import read_env
    return (os.environ.get("YOUTUBE_API_KEY") or read_env().get("YOUTUBE_API_KEY") or "").strip()


def _clean_ideas(raw, n: int = 5) -> List[Dict]:
    out = []
    for i in (raw if isinstance(raw, list) else []):
        if not isinstance(i, dict):
            continue
        t, p = re.sub(r"\s+", " ", str(i.get("title") or "")).strip()[:90], re.sub(r"\s+", " ", str(i.get("premise") or "")).strip()[:400]
        if t and p:
            out.append({"title": t, "premise": p, "hook": re.sub(r"\s+", " ", str(i.get("hook") or "")).strip()[:160]})
    return out[:n]


FALLBACK = {
    "scary": [("The Voice From the Basement", "A boy keeps hearing his own voice call from the basement, and one night it says something only he should know.")],
    "what_if": [("What If Gravity Switched Off For 10 Seconds", "Follow one street as everything not nailed down starts to float, then falls back.")],
    "mystery": [("The Lighthouse Keeper's Last Log", "A new keeper reads the old logbook and finds an entry dated tomorrow.")],
    "funny": [("The Cat Who Applied For A Job", "A cat is accidentally hired as a night guard and takes the job far too seriously.")],
    "motivation": [("The Last Seed", "A farmer plants his last seed in a dry field and learns what patience grows.")],
    "history": [("The Night The Clocks Disagreed", "In an old town every clock showed a different time on one winter night, and the reason changed a harbour forever.")],
}


def ideas(gid: str, titles: Optional[List[str]] = None) -> List[Dict]:
    """Five ORIGINAL story ideas for the genre, shaped by what is working now. An AI writes them; without an AI a built-in idea is returned."""
    gd = genre(gid)
    if not gd:
        raise ValueError("Choose one of the listed genres.")
    seen = "\n".join(f"- {str(t)[:100]}" for t in (titles or [])[:8])
    prompt = (f"You are a story editor for short vertical story videos (30 to 55 seconds). Genre: {gd[1]} - {gd[3]}\n" +
              (f"These titles are doing best right now (only learn what makes people click; NEVER copy or retell them):\n{seen}\n\n" if seen else "") +
              "Write 5 ORIGINAL story ideas. Rules: invented characters and places only (no real people, no real tragedies, no brands, no celebrities), safe for a general audience, "
              "each with a strong first line that makes people stay. Return only JSON: a list of 5 objects {\"title\": \"...\", \"premise\": \"2 sentences\", \"hook\": \"the first spoken line\"}.")
    try:
        from app.engine import llm
        raw = llm.generate("story-ideas", prompt, json_mode=True, timeout=60).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        a, b = raw.find("["), raw.rfind("]")
        res = _clean_ideas(json.loads(raw[a:b + 1]) if a >= 0 else json.loads(raw))
        if res:
            return res
    except Exception as e:
        print(f"[Stories] no AI story ideas this time ({str(e)[:100]})", flush=True)
    return [{"title": t, "premise": p, "hook": ""} for t, p in FALLBACK.get(gid, [])]
