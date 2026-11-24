"""Content-safety gate: sexual / nude / suggestive material must never be clipped or posted.

Three layers (all on by default, SAFE_MODE=off disables them):
  1. Cheap text gate - titles, channel names and transcripts are checked for adult wording.
  2. Platform flags - YouTube age-restricted videos and Twitch "mature" streams are skipped.
  3. Visual + transcript review by Gemini - 8 frames from the clip plus the spoken words are checked for
     nudity, sexual content and suggestive material (strip clubs, lingerie, sexualised dancing, ...).
Layer 3 has two parts: an offline nudity detector (NudeNet, runs on this PC) and Gemini (frames + spoken words).
A clip is blocked if ANY layer flags it. If both reviews cannot run, the clip is blocked. If only Gemini is down,
the clip continues marked "partial" and stays Unlisted until you approve it.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

import requests

from app.config import FFMPEG_BIN, FFPROBE_BIN

ADULT = re.compile(
    r"\b(nude|nudes|nudity|naked|topless|porn\w*|nsfw|18\+|xxx|onlyfans|hentai|erotic\w*|sexy|sex|sexual\w*|sext\w*|"
    r"strip ?club|strippers?|stripping|lap ?dance|lingerie|bikini haul|boobs?|tits|nipples?|cleavage|thong|"
    r"orgasm\w*|horny|fetish|bdsm|milf|escort|hooker|prostitut\w*|brothel|adult content|only fans|"
    r"twerk\w*|thirst ?trap|nude mod|nude patch|uncensored)\b", re.I)


def enabled() -> bool:
    return (os.environ.get("SAFE_MODE") or "on").strip().lower() not in ("off", "0", "no", "false")


def _log(msg: str) -> None:
    print(f"[Safety] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)


def text_flag(*texts: Optional[str]) -> Optional[str]:
    """Adult wording in titles / names / transcript -> short reason, else None."""
    for t in texts:
        m = ADULT.search(t or "")
        if m:
            return f"adult wording ('{m.group(0).lower()}')"
    return None


def _frame_files(video: Path, td: Path, n: int, width: int) -> list:
    """n JPEG frames spread over the clip, written into td. Returns the file paths."""
    dur = 0.0
    try:
        p = subprocess.run([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
                           capture_output=True, text=True)
        dur = float((p.stdout or "0").strip() or 0)
    except Exception:
        pass
    if dur <= 0:
        dur = 30.0
    files = []
    for i in range(n):
        f = td / f"f{i}.jpg"
        subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{dur * (i + 0.5) / n:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(f)], capture_output=True)
        if f.exists():
            files.append(f)
    return files


EXPOSED = {"FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "BUTTOCKS_EXPOSED", "ANUS_EXPOSED"}
_detector = None


def review_locally(video: Path):
    """Offline nudity detector (NudeNet) on 12 frames -> (verdict, reason).
    verdict: False = blocked (score >= 60%), "unsure" = weak signal (40-60%, needs the AI review to confirm), True = clear,
    None = the detector could not run."""
    global _detector
    try:
        if _detector is None:
            from nudenet import NudeDetector
            _detector = NudeDetector()
        best, label = 0.0, ""
        with tempfile.TemporaryDirectory() as td:
            for f in _frame_files(Path(video), Path(td), 12, 640):
                for d in _detector.detect(str(f)):
                    if d.get("class") in EXPOSED and float(d.get("score", 0)) > best:
                        best, label = float(d["score"]), str(d["class"]).replace("_", " ").lower()
        from app.models import UsageEvent
        UsageEvent.record("safety_local", provider="nudenet", task="safety", units=1)
        if best >= 0.60:
            return False, f"local detector: {label} ({best:.0%})"
        if best >= 0.40:
            return "unsure", f"local detector weak signal: {label} ({best:.0%})"
        return True, "clear"
    except Exception as e:
        return None, f"local detector unavailable ({type(e).__name__})"


PROMPT = ("You are a strict content-safety reviewer for a YouTube Shorts channel that must NEVER post sexual content. "
          "Below are {n} frames from one video clip{tr}. Decide, being cautious: "
          "nudity (any exposed genitals, breasts or buttocks, including in games or animation), "
          "sexual_content (sex acts, sexual poses, strip clubs, lap dances, fetish content), "
          "suggestive (lingerie / revealing outfits shown in a sexualised way, sexualised dancing, sexual gestures or innuendo), "
          "sexual_language (sexual talk in the transcript). Ordinary violence or swearing is NOT a reason. "
          'Reply with JSON only: {{"nudity": bool, "sexual_content": bool, "suggestive": bool, "sexual_language": bool, "reason": "max 12 words"}}')


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name) or default)))
    except ValueError:
        return default


def review_with_gemini(video: Path, transcript: str = "") -> Tuple[Optional[bool], str]:
    """(True/False, reason) or (None, why) when Gemini is unreachable / busy / has no key.
    Cost control: a few small frames (SAFETY_AI_FRAMES, default 6, at SAFETY_AI_WIDTH, default 384 px) instead of many large ones."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None, "no Gemini key"
    models = [m for m in (os.environ.get("GEMINI_MODEL") or "gemini-flash-latest", "gemini-flash-lite-latest") if m]
    from app.engine import ai_saver
    ckey = None
    try:                                              # the same clip file (even from another member) is reviewed once
        ckey = ai_saver.key_of("safety", ai_saver.fingerprint(Path(video)), hashlib.sha256((transcript or "")[:1200].encode()).hexdigest(), _int_env("SAFETY_AI_FRAMES", 6, 3, 12), ai_saver.media_resolution())
        hit = ai_saver.cache_get("safety", ckey)
        if hit:
            return bool(hit[0]), hit[1]
    except Exception:
        ckey = None
    with tempfile.TemporaryDirectory() as td:
        files = _frame_files(Path(video), Path(td), _int_env("SAFETY_AI_FRAMES", 6, 3, 12), _int_env("SAFETY_AI_WIDTH", 384, 256, 768))
        frames = [base64.b64encode(f.read_bytes()).decode() for f in files]
    if not frames:
        return None, "could not read frames"
    tr = f" and its transcript: \"{transcript[:1200]}\"" if transcript.strip() else ""
    parts = [{"text": PROMPT.format(n=len(frames), tr=tr)}] + [{"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames]
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    if ai_saver.media_resolution():                   # the same answer for about a quarter of the tokens (measured: 6,628 -> 1,612 for 6 frames)
        body["generationConfig"]["mediaResolution"] = ai_saver.media_resolution()
    last = ""
    for model in dict.fromkeys(models):
        for attempt in range(2):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=30)
                if r.status_code == 200:
                    from app.engine import gemini_util
                    from app.models import UsageEvent
                    tin, tout = gemini_util.usage_of(r.json())
                    UsageEvent.record("llm", provider="gemini", task="safety", tokens_in=tin, tokens_out=tout)
                    ai_saver.spend(tin + tout)
                    if "mediaResolution" in body["generationConfig"]:
                        ai_saver.saved("safety", "lowres", int(tin * ai_saver.LOW_RES_RATIO))
                    cand = r.json()["candidates"][0]
                    if cand.get("finishReason") == "SAFETY":   # the reviewer itself refused to look: treat as unsafe
                        return False, "blocked by the reviewer's own safety filter"
                    data = json.loads(cand["content"]["parts"][0]["text"])
                    bad = [k for k in ("nudity", "sexual_content", "suggestive", "sexual_language") if data.get(k)]
                    verdict = (False, f"{', '.join(bad)}: {str(data.get('reason', ''))[:80]}") if bad else (True, "clear")
                    if ckey:
                        ai_saver.cache_put("safety", ckey, list(verdict), tin + tout)
                    return verdict
                last = f"HTTP {r.status_code}"
            except Exception as e:
                last = type(e).__name__
            time.sleep(2)
    return None, f"Gemini unavailable ({last})"


def check_clip(video: Path, title: str = "", channel: str = "", transcript: str = "", age_limit: int = 0,
               mature: bool = False) -> Tuple[bool, str]:
    """Full gate -> (ok, reason). A clip is blocked by ANY layer that flags it. If the AI review cannot run but the
    local detector passed, the clip goes ahead marked 'partial' (it is still Unlisted until you approve it)."""
    if not enabled():
        return True, "safe mode off"
    if age_limit and int(age_limit) >= 18:
        return False, "age-restricted on the platform"
    if mature:
        return False, "marked mature by the platform"
    why = text_flag(title, channel, transcript)
    if why:
        return False, why
    local, lwhy = review_locally(Path(video))
    if local is False:
        return False, lwhy
    ai, awhy = review_with_gemini(Path(video), transcript)
    if ai is False:
        return False, awhy
    if local == "unsure":   # weak local signal: only the AI review can clear it
        if ai is True:
            return True, "clear (AI review cleared a weak local flag)"
        return False, f"{lwhy}; AI review could not confirm it is safe"
    if ai is True and local is True:
        return True, "clear (local detector + AI review)"
    if ai is True:
        return True, "clear (AI review; local detector unavailable)"
    if local is True:
        return True, f"partial: local detector clear, AI review unavailable ({awhy})"
    return False, f"could not review at all ({lwhy}; {awhy})"


def check_final_video(video: Path, title: str = "", description: str = "") -> Tuple[bool, str]:
    """Last gate on the finished video before it can be uploaded.
    The clips in it were already reviewed by Gemini, so by default the final video gets the free checks only (adult wording in the title
    and description + the local nudity detector); Gemini looks again only if the local detector is unsure or cannot run.
    SAFETY_FINAL_AI=on restores the full second Gemini review."""
    if (os.environ.get("SAFETY_FINAL_AI") or "off").strip().lower() in ("on", "1", "yes", "true"):
        return check_clip(video, title=title, channel="", transcript=description[:600])
    if not enabled():
        return True, "safe mode off"
    why = text_flag(title, description)
    if why:
        return False, why
    local, lwhy = review_locally(Path(video))
    if local is False:
        return False, lwhy
    if local is True:
        return True, "clear (the clips were reviewed before; local detector + text check on the final video)"
    return check_clip(video, title=title, channel="", transcript=description[:600])   # unsure or detector unavailable: the full review decides
