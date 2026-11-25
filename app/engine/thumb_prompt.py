"""The prompt writer: a new image prompt for every thumbnail, written from what is really in the video.

The image models (the free service for Better, FLUX for Best) draw whatever they are told, so the words matter most. Instead of one fixed template,
a text AI (DeepSeek first, Gemini as the backup, the same ones that write titles) reads the facts of THIS video - the game, the kind of video, the title,
what happens, and for Best what Gemini saw in the frames (subject, action, setting, mood) - and writes a prompt made for this scene: the subject and
action, the camera angle, the lighting, the colour palette, where the headline goes and how it should look.

Nothing it writes is trusted: it is cleaned (no web addresses, no names, a length limit), the headline is checked to be in the prompt exactly when FLUX is to
draw it, and a safe tail ("no watermark, no logo, no real people") is always added. If the AI is off, out of tokens or answers badly, None is returned
and the caller uses the built-in template instead. THUMB_PROMPT_AI=off switches the writer off (saves a few AI tokens per thumbnail).
"""
import json
import os
import re
from typing import Dict, Optional

LIMIT = {"better": 760, "best": 1800}        # characters: the free service takes the prompt in a web address, FLUX takes up to 2,048
TAIL = "No watermark, no logo, no real people, no extra text."
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)

GUIDE = """You write the image prompt for FLUX, an AI image model that draws a YouTube thumbnail. Write ONE prompt made for THIS video, not a generic one.

Rules for a prompt that works:
- Start with the main subject doing the main action, in plain concrete words (who or what, doing what, where). Name the game's real look: its vehicles, characters, weapons, world.
- Then the camera and composition (for example low angle close-up, over-the-shoulder, wide establishing shot), what is in the foreground and what is behind.
- Then the light and the colours. Choose them to fit this moment's mood: funny = bright playful colours; scary = dark teal shadows and cold light; epic = golden rim light and haze;
  rage or chaos = hot reds and oranges with sparks; news or trailers = clean cinematic blue and white. Add one or two accent colours that pop.
- One strong focal point, large and clear even at small size, high contrast, vivid, cinematic. Leave calm space where the headline goes.
- Never use real people's names, streamer names, brands, logos or web addresses. Do not describe user interface, health bars or subtitles.
- {text_rule}
- {shape_rule}
- About {words} words. One paragraph, no lists, no quotation marks except around the exact headline.

Return only JSON: {{"prompt": "the finished prompt"}}"""


def enabled() -> bool:
    return (os.environ.get("THUMB_PROMPT_AI") or "on").strip().lower() not in ("off", "0", "no", "false")


def _facts(ctx: Dict, analysis: Optional[Dict], headline: str) -> str:
    rows = [f"Game: {ctx.get('game') or 'a video game'}", f"Kind of video: {ctx.get('content_type') or 'gaming moment'}"]
    if ctx.get("title"):
        rows.append(f"Video title: {str(ctx['title'])[:120]}")
    what = str(ctx.get("hook") or ctx.get("topic") or "")[:260]
    if what:
        rows.append(f"What happens in the clip: {what}")
    if ctx.get("scene"):
        rows.append(f"A first idea for the scene: {str(ctx['scene'])[:220]}")
    for k, label in (("subject", "Main subject seen in the frames"), ("action", "Action seen in the frames"), ("setting", "Setting seen in the frames"), ("mood", "Mood")):
        if analysis and analysis.get(k):
            rows.append(f"{label}: {str(analysis[k])[:140]}")
    if ctx.get("recipe_hint"):
        rows.append(f"What works for this kind of video (measured from popular thumbnails): {ctx['recipe_hint']}")
    if headline:
        rows.append(f"Headline for the thumbnail: {headline}")
    return "\n".join(rows)


def _ask(prompt: str) -> str:
    """One text AI call (DeepSeek first, then Gemini). Its tokens are recorded as real usage for the bill."""
    from app.engine import llm
    return llm.generate("thumb-prompt", prompt, json_mode=True, timeout=45)


def clean(text: str, headline: str, with_text: bool, tier: str, avoid=()) -> Optional[str]:
    """Make the AI's prompt safe and the right size, or None when it is not usable."""
    t = _URL.sub("", str(text or ""))
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", t)
    for name in avoid:
        if name and len(name) > 2:
            t = re.sub(re.escape(name), "the player", t, flags=re.I)
    t = " ".join(t.split())
    if len(t) < 80:
        return None
    limit = LIMIT.get(tier, LIMIT["better"])
    room = limit - len(TAIL) - 1
    if not with_text:
        t = re.sub(r"[^.]*\b(text|headline|caption|letters?)\b[^.]*\.\s*", "", t, flags=re.I).strip()      # no sentence about writing when the studio writes the headline
        t = re.sub(r"\.(?=\S)", ". ", t)
        if len(t) < 80:
            return None
    need = ""
    if with_text and headline and f'"{headline}"' not in t:
        need = f' The thumbnail shows the headline text exactly "{headline}" in huge, thick, perfectly spelled letters with a heavy outline.'
    body_room = room - len(need) - 1          # one more for the full stop
    if len(t) > body_room:
        cut = t[:body_room]
        t = cut[: cut.rfind(". ") + 1] if cut.rfind(". ") > body_room * 0.6 else cut.rsplit(" ", 1)[0].rstrip(" ,;") + "."
    t = t + need
    if not t.endswith("."):
        t += "."
    return f"{t} {TAIL}"


def write(ctx: Dict, mode: str, headline: str = "", with_text: bool = False, tier: str = "better", analysis: Optional[Dict] = None) -> Optional[str]:
    """The prompt for this thumbnail, written for this video, or None (the caller uses the built-in template)."""
    if not enabled():
        return None
    vertical = mode == "9:16"
    text_rule = (f'The headline "{headline}" is part of the picture: write it into the prompt in quotes, say it is huge, thick, perfectly spelled, high contrast with an outline, '
                 "and where it sits (top third or bottom third, never over the face or the action)." if with_text and headline
                 else "Do NOT ask for any text, letters, numbers or logos in the picture: the headline is added afterwards.")
    shape_rule = ("It is a tall vertical thumbnail: keep the subject and any text inside the middle column." if vertical
                  else "It is a wide 16:9 thumbnail: keep the subject and any text inside the middle band.")
    words = "110 to 150" if tier == "best" else "55 to 85"
    prompt = GUIDE.format(text_rule=text_rule, shape_rule=shape_rule, words=words) + "\n\nFacts about this video:\n" + _facts(ctx, analysis, headline)
    try:
        raw = _ask(prompt)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        a, b = raw.find("{"), raw.rfind("}")
        text = json.loads(raw[a:b + 1]).get("prompt") if 0 <= a < b else raw
    except Exception as e:
        print(f"[Thumbnail] prompt writer unavailable ({str(e)[:100]}) - using the built-in template", flush=True)
        return None
    out = clean(text, headline, with_text, tier, avoid=ctx.get("avoid") or ())
    print(f"[Thumbnail] prompt written for this video ({len(out) if out else 0} characters)" if out else "[Thumbnail] the written prompt was not usable - using the built-in template", flush=True)
    return out
