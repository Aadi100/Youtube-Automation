"""Trending mode: look at the game first, then clip from what is trending right now.

For a video made in Trending mode the studio
  1. looks further back (two days instead of one) so that growth can be measured,
  2. ranks every candidate from Twitch and YouTube by how fast it is growing - views per hour since it was published, not just its total views - so a clip that is
     taking off beats an old clip that simply collected views,
  3. optionally asks an AI (Settings -> AI models -> "Trending theme") what is hot for this game right now, from the titles of the fastest risers, and gives
     candidates about that theme a boost,
  4. takes the best live stream too (the live scan already watches the biggest streams of the game).
Everything after that is the normal pipeline: the safety check, moment picking, credits, captions, the thumbnail.

It costs the member a small fee per video (TREND prices in Settings -> Pricing: 2 tokens for a Short, 8 for a compilation), charged only when the video is made.
The fee is recorded as usage by pipeline.py only when this module really ranked something (see used()).
"""
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

WINDOW_HOURS = 48                      # how far back trending mode looks (the normal search looks 24 hours)
_state = {"used": False, "theme": None}


def on() -> bool:
    """Is this run in Trending mode? (queue_service sets CLIPSTUDIO_TRENDING for the pipeline process.)"""
    return (os.environ.get("CLIPSTUDIO_TRENDING") or "").strip().lower() in ("1", "true", "yes", "on")


def used() -> bool:
    """Did trending mode really rank candidates in this run? (Only then is the trending fee charged.)"""
    return bool(_state["used"])


def window(hours: int) -> int:
    return max(int(hours or 24), WINDOW_HOURS) if on() else int(hours or 24)


def _age_hours(published, now: Optional[datetime] = None) -> float:
    """Hours since a candidate was published (an ISO time or a unix time); 24 when it is not known."""
    try:
        if isinstance(published, (int, float)):
            t = datetime.fromtimestamp(float(published), tz=timezone.utc)
        else:
            t = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        return max(1.0, ((now or datetime.now(timezone.utc)) - t).total_seconds() / 3600.0)
    except Exception:
        return 24.0


def growth(c: Dict, now: Optional[datetime] = None) -> float:
    """Views per hour since it was published."""
    return float(c.get("views") or 0) / _age_hours(c.get("published"), now)


def rank(cands: List[Dict], keywords: Optional[List[str]] = None, now: Optional[datetime] = None) -> List[Dict]:
    """The candidates, fastest growing first. A title that mentions a trending keyword gets a 25% boost. Each candidate gets 'trend' = {vph, boost}."""
    kw = [k.lower() for k in (keywords or []) if k and len(k) > 2]
    out = []
    for c in cands:
        vph = growth(c, now)
        hit = any(k in (c.get("title") or "").lower() for k in kw)
        out.append({**c, "trend": {"vph": round(vph, 1), "boost": hit}, "_score": vph * (1.25 if hit else 1.0)})
    out.sort(key=lambda c: -c["_score"])
    for c in out:
        c.pop("_score", None)
    _state["used"] = bool(out) or _state["used"]
    return out


def theme(game_name: str, top: List[Dict]) -> Optional[Dict]:
    """What is hot for this game right now, from the titles of the fastest risers: {"theme": one sentence, "keywords": [..]} or None (no AI, or it failed).
    Which AI does this is chosen in Settings -> AI models (job: Trending theme)."""
    if not top:
        return None
    titles = "\n".join(f"- {str(c.get('title') or '')[:110]} ({int(c.get('views') or 0)} views, {c.get('trend', {}).get('vph', 0)} per hour)" for c in top[:12])
    prompt = (f"These are the fastest growing clips and videos about the game {game_name} right now:\n{titles}\n\n"
              'What is trending about this game at the moment? Return JSON: {"theme": "one short sentence", "keywords": ["3 to 6 single words or short phrases that appear in what is trending"]}')
    try:
        from app.engine import llm
        raw = llm.generate("trending-theme", prompt, json_mode=True, timeout=45).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        a, b = raw.find("{"), raw.rfind("}")
        d = json.loads(raw[a:b + 1])
    except Exception as e:
        print(f"[Trending] no AI theme this time ({str(e)[:80]})", flush=True)
        return None
    th = re.sub(r"\s+", " ", str(d.get("theme") or "")).strip()[:160]
    kws = [re.sub(r"[^\w\s'\-]", "", str(k)).strip()[:30] for k in (d.get("keywords") or []) if str(k).strip()][:6]
    if not th and not kws:
        return None
    return {"theme": th, "keywords": [k for k in kws if k]}


def prepare(game: Dict, per_source: List[List[Dict]]) -> List[List[Dict]]:
    """Re-rank each source's candidates by growth (with the optional AI theme as a boost). Prints what it found, so the job log shows it."""
    flat = [c for lst in per_source for c in lst]
    first = rank(flat)
    th = theme(game.get("name", ""), first)
    kws = (th or {}).get("keywords") or []
    _state["theme"] = th
    out = [rank(lst, kws) for lst in per_source]
    top = max((lst[0] for lst in out if lst), key=lambda c: c["trend"]["vph"], default=None)
    if th:
        print(f"[Trending] {game.get('name')}: {th['theme']} (keywords: {', '.join(th['keywords'])})", flush=True)
    if top:
        print(f"[Trending] fastest rising: {top.get('source')} '{str(top.get('title'))[:60]}' by {top.get('streamer')} - {top['trend']['vph']} views per hour", flush=True)
    return out
