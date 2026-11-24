"""AI-generated artwork for thumbnails.

Provider "free"   (default): the keyless Pollinations image service. Only a generic art description
                              (game name + mood) is sent - never titles, streamer names or any personal details.
Provider "gemini": Google's image models with your Gemini key (needs billing enabled; the free tier has no image quota).
AI_THUMBNAILS=off turns it all off (thumbnails then use the video's own frame). Every failure falls back silently.
"""
import base64
import os
import random
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

MOODS = ["explosive action scene with bright orange and blue lighting", "chaotic funny moment in vivid candy colours",
         "epic showdown at golden sunset", "neon-lit chase in hot pink and cyan",
         "dramatic hero shot with glowing particles and bright rim light", "colourful over-the-top adventure under a bright sky"]
GEMINI_MODEL = "gemini-2.5-flash-image"
_gemini_blocked = False   # set after a quota error so we don't retry for every video
import threading  # noqa: E402
_gemini_image_usage = threading.local()
LAST_PROVIDER = {"name": None}     # which service really drew the last picture: "gemini" or "free"


def enabled() -> bool:
    return (os.environ.get("AI_THUMBNAILS") or "on").strip().lower() not in ("off", "0", "no", "false")


def build_prompt(game_name: str, mood: Optional[str] = None, scene: str = "") -> str:
    game = re.sub(r"[^\w\s\-:&'.]", "", game_name or "video game")[:60]
    scene = re.sub(r"[^\w\s,.\-']", "", scene or "")[:200].strip()
    if scene:
        return (f"dramatic cinematic YouTube thumbnail background art in the style of the video game {game}: {scene}. "
                "bold teal-and-orange colour grade with neon pink and cyan accents, extremely vivid saturated colours, high contrast, glowing epic lighting, strong depth, bold composition, high detail, "
                "no text, no letters, no logo, no watermark, no real people")
    return (f"dramatic cinematic YouTube thumbnail background art in the style of the video game {game}, {mood or random.choice(MOODS)}, "
            "bold teal-and-orange colour grade with neon pink and cyan accents, extremely vivid saturated colours, high contrast, glowing epic lighting, strong depth, bold composition, high detail, "
            "no text, no letters, no logo, no watermark, no real people")


def build_redraw_prompt(game_name: str, scene: str = "") -> str:
    game = re.sub(r"[^\w\s\-:&'.]", "", game_name or "video game")[:60]
    scene = re.sub(r"[^\w\s,.\-']", "", scene or "")[:200].strip()
    return (f"Redraw this video frame from the game {game} as a dramatic, eye-catching YouTube thumbnail background. Keep the same scene, characters and action so it still matches the video. "
            + (f"Mood and details: {scene}. " if scene else "")
            + "Exaggerate the colours and lighting: bold teal-and-orange grade with neon accents, strong depth and contrast, glowing rim light, high detail. "
              "Leave the middle and one side calm enough for a big headline. No text, no letters, no logo, no watermark.")


def _from_gemini(prompt: str, mode: str, out: Path, ref: Optional[Path] = None) -> Optional[Path]:
    global _gemini_blocked
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key or _gemini_blocked:
        return None
    parts = [{"text": prompt}]
    if ref and Path(ref).is_file():            # image-to-image: Gemini redraws the real frame (Medium and High)
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(Path(ref).read_bytes()).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16" if mode == "9:16" else "16:9"}}}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                      headers={"x-goog-api-key": key}, json=body, timeout=180)
    if r.status_code == 429:
        _gemini_blocked = True
        print("[AI art] Gemini image quota not available (enable billing in Google AI Studio) - using the free service")
        return None
    r.raise_for_status()
    try:
        from app.engine import gemini_util
        _gemini_image_usage.usage = gemini_util.usage_of(r.json())
    except Exception:
        _gemini_image_usage.usage = (0, 0)
    for part in r.json()["candidates"][0]["content"]["parts"]:
        d = part.get("inlineData") or part.get("inline_data")
        if d:
            out.write_bytes(base64.b64decode(d["data"]))
            return out
    return None


def _from_free(prompt: str, mode: str, out: Path) -> Optional[Path]:
    w, h = (720, 1280) if mode == "9:16" else (1280, 720)
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
    for attempt in range(4):
        wait = 8
        try:
            r = requests.get(url, params={"width": w, "height": h, "model": "flux", "nologo": "true", "seed": random.randint(1, 999999)}, timeout=150)
            if r.ok and r.headers.get("content-type", "").startswith("image") and len(r.content) > 5000:
                out.write_bytes(r.content)
                return out
            m = re.search(r"[Rr]etry after (\d+)s", r.text or "")   # the free tier allows one image every 45 s: wait as long as it asks
            if m:
                wait = min(int(m.group(1)) + 2, 60)
                print(f"[AI art] free service says wait {wait}s - waiting", flush=True)
        except requests.RequestException:
            pass
        time.sleep(wait)
    return None


def _record_image(provider: str) -> None:
    LAST_PROVIDER["name"] = provider
    from app.models import UsageEvent
    tin, tout = getattr(_gemini_image_usage, "usage", (0, 0)) if provider == "gemini" else (0, 0)
    UsageEvent.record("image", provider=provider, task="background", units=1, tokens_in=tin, tokens_out=tout)


def generate_background(game_name: str, mode: str, out: Path, scene: str = "", ref: Optional[Path] = None, tier: Optional[str] = None) -> Optional[Path]:
    """Returns the path of a generated background image (no text on it), or None.
    tier free: the free image service. tier medium / high: Gemini redraws the real frame `ref`; if that is not possible the free service is used."""
    LAST_PROVIDER["name"] = None
    if not enabled():
        return None
    tier = (tier or os.environ.get("THUMB_TIER") or "free").strip().lower()
    prompt = build_redraw_prompt(game_name, scene) if (ref and tier in ("medium", "high")) else build_prompt(game_name, scene=scene)
    provider = "gemini" if tier in ("medium", "high") else (os.environ.get("AI_IMAGE_PROVIDER") or "free").strip().lower()
    try:
        if provider == "gemini":
            p = _from_gemini(prompt, mode, out, ref if tier in ("medium", "high") else None)
            if p:
                print("[AI art] background from Gemini")
                _record_image("gemini")
                return p
        p = _from_free(prompt, mode, out)
        if p:
            print("[AI art] background generated")
            _record_image("free")
            return p
    except Exception as e:
        print(f"[AI art] failed ({type(e).__name__}: {str(e)[:120]}) - using the video frame instead")
    print("[AI art] no image this time - using the video frame instead")
    return None
