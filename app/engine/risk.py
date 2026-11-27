"""Reused-content risk: how likely is it that YouTube treats a video as "reused content" (made mostly from other people's footage with little of your own added)?

Plain rules, no AI, no cost. The score is 0 (safe) to 100 (very risky); the reasons say WHY in simple words and what to do about it. It is advice, not a verdict:
YouTube makes the real decision, and the member always has the last word.

What raises the risk:   the original sound is kept untouched, there is no commentary or other work of your own on top, the whole video is one other person's clip,
                        the source clip is very popular (a big creator's work is watched and claimed more).
What lowers it:         your own commentary, captions, text, music, zoom, speed changes, pictures on top, several different clips, and above all a creator's
                        written permission (the Permission tracker).
"""
from typing import Dict, List, Optional

LOW, MEDIUM = 30, 60                      # below LOW: low risk, below MEDIUM: medium, otherwise high
POPULAR, VERY_POPULAR = 100_000, 500_000  # views of the source clip


def level_of(score: int) -> str:
    return "low" if score < LOW else "medium" if score < MEDIUM else "high"


def edit_summary(data: Dict) -> Dict:
    """What the member added on top of the footage in an editor project (counts only; nothing private)."""
    clips = data.get("clips") or []
    return {"clips": len(clips), "sources": len({c.get("source") for c in clips}),
            "texts": sum(len(c.get("texts") or []) for c in clips), "captions": any(c.get("captions") for c in clips),
            "overlays": sum(len(c.get("overlays") or []) for c in clips), "pip": sum(1 for c in clips if c.get("pip")),
            "speed": any(abs(float(c.get("speed", 1)) - 1) > 0.01 for c in clips), "zoom": any(c.get("zoom") for c in clips),
            "look": any((c.get("look") or {}).get("preset", "none") != "none" for c in clips),
            "music": bool(((data.get("audio") or {}).get("music"))), "transitions": any((c.get("transition") or {}).get("type", "none") != "none" for c in clips[1:]),
            "quieter": any(float(c.get("volume", 1)) < 0.8 for c in clips)}


def _keys(credit: Dict) -> List[str]:
    from app.services import permission_service
    return permission_service.keys_for(credit.get("platform"), credit.get("creator"), credit.get("channel_url"))


def assess(video: Dict, permitted: Optional[Dict] = None) -> Dict:
    """{"score", "level", "reasons": [{"code", "points", "text", "fix"}], "good": [text, ...]} for one video record.
    `permitted` = {creator key: permission} of the member (see permission_service.allowed_map); None means "nobody has given permission"."""
    permitted = permitted or {}
    credits = [c for c in (video.get("credits") or []) if c and (c.get("creator") or c.get("video_url"))]
    reasons: List[Dict] = []
    good: List[str] = []

    def bad(code, points, text, fix):
        reasons.append({"code": code, "points": points, "text": text, "fix": fix})

    if not credits:                                                   # nothing from anybody else: it is the member's own footage
        return {"score": 5, "level": "low", "reasons": [], "good": ["It does not use anyone else's footage."]}

    edited, es = bool(video.get("edited")), video.get("edit_summary") or {}
    mode = video.get("audio_mode") or "replace"
    score = 20                                                        # any video made from other people's footage starts here
    if edited:
        work = [n for n, k in (("text", es.get("texts")), ("captions", es.get("captions")), ("pictures on top", es.get("overlays")), ("picture-in-picture", es.get("pip")),
                               ("speed changes", es.get("speed")), ("zoom", es.get("zoom")), ("a colour look", es.get("look")), ("music", es.get("music")),
                               ("transitions", es.get("transitions"))) if k]
        if not (es.get("texts") or es.get("captions") or es.get("music") or es.get("pip")):
            bad("no_own_work", 30, "Nothing of your own is added on top of the footage (no text, captions, music or reaction).", "Add text or captions, a music track, or a reaction picture-in-picture.")
        elif len(work) <= 1:
            bad("little_own_work", 12, "Very little of your own is added on top of the footage.", "Add more of your own: commentary text, captions or a reaction.")
        else:
            good.append("You added your own work on top: " + ", ".join(work[:5]) + ".")
        if es.get("sources", 0) >= 3 or es.get("clips", 0) >= 4:
            score -= 8
            good.append("It mixes several different clips.")
    else:
        if mode == "original":
            bad("original_audio", 35, "The original sound is kept untouched and nothing of yours is added.", "Remake it with 'AI commentary + music' or 'Original audio under music'.")
        elif mode == "bed":
            bad("sound_under_music", 8, "The original sound is still in the video (under the music).", "Use 'AI commentary + music' so the video has your own commentary.")
        else:
            good.append("It has your own commentary (the original sound is replaced).")
        if video.get("context_card"):
            score -= 5
            good.append("A context card tells viewers who and what they are seeing.")
        if video.get("kind") == "short" and len(credits) == 1 and mode != "replace":
            bad("one_clip", 10, "The whole video is one other person's clip.", "Add commentary, or make a compilation of several clips.")
        elif video.get("kind") == "compilation" and len({c.get("creator") for c in credits}) >= 5:
            score -= 8
            good.append("It mixes clips from many different creators.")

    top = max((int(c.get("views") or 0) for c in credits), default=0)
    if top >= VERY_POPULAR:
        bad("very_popular", 20, f"The source clip is very popular ({top:,} views). Big creators' clips are watched and claimed more often.", "Prefer smaller clips, or get the creator's permission and write it in the Permission tracker.")
    elif top >= POPULAR:
        bad("popular", 10, f"The source clip is popular ({top:,} views).", "Add more of your own on top, or ask the creator for permission.")

    allowed = [c for c in credits if any(k in permitted for k in _keys(c))]
    if allowed and len(allowed) == len(credits):
        score -= 30
        good.append("You have written permission from " + ", ".join(sorted({str(c.get('creator')) for c in allowed})[:3]) + ".")
    elif allowed:
        score -= 12
        good.append("You have permission from some of the creators (" + ", ".join(sorted({str(c.get('creator')) for c in allowed})[:3]) + ").")

    score = max(0, min(100, score + sum(r["points"] for r in reasons)))
    return {"score": score, "level": level_of(score), "reasons": sorted(reasons, key=lambda r: -r["points"]), "good": good}
