"""The Best thumbnail level: Gemini plans it, FLUX draws it.

  1. Gemini looks at up to three frames that code already picked (never twenty), the facts about the video and the recipe for that kind of video,
     and answers with a plan: which frame, a 2-4 word headline, the look, the colours and one sentence about the picture.
  2. The studio turns that plan into a prompt and FLUX.1 [schnell] (open weights, Apache 2.0: free to use commercially, no watermark) draws the thumbnail.
     It runs on Cloudflare Workers AI (the free allowance is 10,000 "neurons" a day, about 170 thumbnails; after that a fraction of a cent each).
     By default FLUX writes the headline into the picture. Setting THUMB_TEXT=code makes FLUX draw the picture only, and the studio adds the headline.
  3. Optional (THUMB_REVIEW=on): Gemini looks at the finished thumbnail once and, if the headline is misspelled or hard to read, FLUX draws it again once.

Everything Gemini says is checked before it is used. Every failure returns None and the caller uses the Better level instead (and bills it as Better).
"""
import base64
import io
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from app.config import FFMPEG_BIN
from app.engine import content_ai, gemini_util
from app.engine.thumb_styles import STYLE_IDS, valid_color

CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"
SYSTEM = ("You are the art director of a YouTube gaming channel. You design thumbnails that get clicked: one clear subject, a face or action in the "
          "middle of the picture, 2 to 4 punchy words, strong contrast, and never a promise the video does not keep.")
_usage = threading.local()          # Gemini tokens of the call this thread just made


# ------------------------------------------------------------------ what is switched on
def cloudflare_ready() -> bool:
    return bool((os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip() and (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip())


def gemini_ready() -> bool:
    return bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def ready() -> bool:
    return gemini_ready() and cloudflare_ready()


def text_by_code() -> bool:
    return (os.environ.get("THUMB_TEXT") or "flux").strip().lower() == "code"


def review_on() -> bool:
    return (os.environ.get("THUMB_REVIEW") or "off").strip().lower() in ("on", "1", "yes", "true")


# ------------------------------------------------------------------ the plan (Gemini)
def _frames(video: Path, td: Path, n: int = 3) -> List[Dict]:
    out = []
    for i, f in enumerate(content_ai.best_frames(Path(video), n)):
        p = td / f"f{i + 1}.jpg"
        subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{f['t']:.2f}", "-i", str(video), "-vf", "scale=512:-2", "-frames:v", "1", "-q:v", "4", str(p)],
                       capture_output=True)
        if p.is_file():
            out.append({"t": f["t"], "path": p})
    return out


def clean_headline(h: str) -> str:
    h = re.sub(r"[^\w\s!?'\-]", "", str(h or "")).strip().upper()
    return " ".join(h.split()[:4])[:22]


def check(plan: Dict, frames: int) -> Dict:
    """Keep only what is valid: a frame number in range, a short headline, a known style, real colours, a plain one-sentence scene."""
    out: Dict = {}
    try:
        k = int(plan.get("frame"))
        if 1 <= k <= frames:
            out["frame"] = k
    except (TypeError, ValueError):
        pass
    h = clean_headline(plan.get("headline"))
    if h:
        out["headline"] = h
    if isinstance(plan.get("style"), str) and plan.get("style") in STYLE_IDS:
        out["style"] = plan["style"]
    for k in ("text_color", "accent"):
        v = valid_color(str(plan.get(k) or ""), "")
        if v:
            out[k] = v.upper()
    scene = re.sub(r"[^\w\s,.\-']", "", str(plan.get("scene") or plan.get("art_prompt") or ""))[:260].strip()
    if scene:
        out["scene"] = scene
    out["why"] = str(plan.get("why") or "")[:100]
    return out


def _gemini_json(parts: List[Dict], task: str, timeout: int = 90) -> Dict:
    """One Gemini call with pictures that must answer with JSON. Tries the backup models like the text calls do. Records the AI tokens it used."""
    import json
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("no Gemini key")
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7}}
    if (os.environ.get("AI_GEMINI_THINKING") or "off").strip().lower() in ("off", "0", "no"):
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    last = "no model answered"
    for m in gemini_util.models():
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=timeout)
        except requests.RequestException as e:
            last = f"{m}: {type(e).__name__}"
            continue
        if r.status_code != 200:
            last = f"{m}: HTTP {r.status_code}"
            continue
        try:
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            tin, tout = gemini_util.usage_of(data)
            try:
                from app.models import UsageEvent
                UsageEvent.record("llm", provider="gemini", task=task, tokens_in=tin, tokens_out=tout)
            except Exception:
                pass
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            a, b = text.find("{"), text.rfind("}")
            return json.loads(text[a:b + 1])
        except Exception as e:
            last = f"{m}: unreadable answer ({type(e).__name__})"
    raise RuntimeError(last)


def _image_part(path: Path) -> Dict:
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(Path(path).read_bytes()).decode()}}


def plan(video: Path, ctx: Dict, recipe: Optional[Dict] = None) -> Optional[Dict]:
    """The plan for one thumbnail, or None when Gemini is unavailable (the caller then uses the Better level)."""
    if not gemini_ready():
        return None
    with tempfile.TemporaryDirectory() as td:
        fr = _frames(video, Path(td))
        if not fr:
            return None
        facts = (f"Game: {ctx.get('game') or 'gaming'}. Video title: {ctx.get('title') or '-'}. What happens: {(ctx.get('hook') or ctx.get('topic') or '-')[:200]}. "
                 f"Kind of video: {ctx.get('content_type') or 'funny'}.")
        if recipe:
            facts += (f" What works for this kind of video (measured from popular thumbnails): headline {recipe.get('text_pos', 'top')}, text colour {recipe.get('text_color')}, "
                      f"accent {recipe.get('accent')}, at most {recipe.get('max_words', 3)} words, good looks: {', '.join(recipe.get('styles', []))}.")
        parts: List[Dict] = [{"text": SYSTEM}]
        for i, f in enumerate(fr):
            parts += [{"text": f"Frame {i + 1}:"}, _image_part(f["path"])]
        parts.append({"text": facts + f' Pick the best of the {len(fr)} frames. Return JSON: {{"frame": 1-{len(fr)}, "headline": "2-4 words, ALL CAPS, max 20 characters, easy to spell, '
                                       f'not the same as the title", "style": one of {STYLE_IDS}, "text_color": "#RRGGBB", "accent": "#RRGGBB", "scene": "one sentence that describes the thumbnail '
                                       f'picture: the same game, characters and action as the best frame, made more vivid and dramatic; no text, no real people", "why": "max 12 words"}}'})
        try:
            raw = _gemini_json(parts, "thumb-plan")
        except Exception as e:
            print(f"[Thumbnail] Gemini plan unavailable ({str(e)[:100]})", flush=True)
            return None
        p = check(raw, len(fr))
        if not p.get("scene"):
            return None
        if "frame" in p:
            p["t"] = fr[p["frame"] - 1]["t"]
        print(f"[Thumbnail] Gemini plan: frame {p.get('frame')}, '{p.get('headline')}', {p.get('style')} ({p.get('why')})", flush=True)
        return p


def review(thumb: Path, headline: str, ctx: Dict) -> Optional[str]:
    """Gemini looks at the finished thumbnail once. Returns a better (easy to spell) headline when the printed one is wrong or hard to read, else None."""
    if not gemini_ready():
        return None
    try:
        raw = _gemini_json([{"text": SYSTEM}, _image_part(Path(thumb)),
                            {"text": f'This is the finished thumbnail for "{ctx.get("title") or ""}". The headline on it should read exactly "{headline}". '
                                     'Is that exact text printed, spelled correctly and easy to read? Return JSON: {"ok": true or false, "score": 1-10, '
                                     '"headline": "a different, even easier 2-4 word ALL CAPS headline if it is not ok, else the same one"}'}], "thumb-review", 60)
        ok = bool(raw.get("ok")) and int(raw.get("score") or 0) >= 6
        new = clean_headline(raw.get("headline"))
        print(f"[Thumbnail] Gemini review: {'good' if ok else 'not good'} ({raw.get('score')}/10)", flush=True)
        return None if ok else (new if new and new != headline.upper() else headline)
    except Exception as e:
        print(f"[Thumbnail] Gemini review skipped ({str(e)[:100]})", flush=True)
        return None


# ------------------------------------------------------------------ the picture (FLUX)
def build_prompt(game: str, scene: str, headline: str, mode: str, with_text: bool) -> str:
    game = re.sub(r"[^\w\s\-:&'.]", "", game or "video game")[:60]
    scene = re.sub(r"[^\w\s,.\-']", "", scene or "")[:260].strip()
    shape = ("tall vertical composition, keep the subject and every word in the middle column" if mode == "9:16"
             else "wide landscape composition, keep the subject and every word in the middle band")
    base = (f"Dramatic cinematic YouTube gaming thumbnail in the style of the video game {game}: {scene}. {shape}. "
            "Bold teal-and-orange colour grade with neon pink and cyan accents, extremely vivid saturated colours, high contrast, glowing epic lighting, strong depth, high detail.")
    if with_text and headline:
        return (base + f' Huge, thick, perfectly spelled headline text that reads exactly "{headline}", white letters with a heavy black outline and a soft glow, '
                       "easy to read at a small size. No other text, no watermark, no logo, no real people.")
    return base + " No text, no letters, no logo, no watermark, no real people."


def _fit(raw: bytes, mode: str, out: Path) -> Path:
    """Whatever size FLUX answered with, cover-crop it to the thumbnail size (1280x720 or 1080x1920) and save it as a JPEG."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    W, H = (1280, 720) if mode != "9:16" else (1080, 1920)
    s = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * s)), max(H, round(im.height * s))), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im.crop((l, t, l + W, t + H)).save(out, "JPEG", quality=94)
    return out


def _why(status: int, body) -> str:
    """What a Cloudflare refusal means, in plain words."""
    msg = ""
    try:
        errs = (body or {}).get("errors") or []
        msg = "; ".join(str(e.get("message") or "") for e in errs if isinstance(e, dict))[:160]
    except Exception:
        pass
    if status in (401, 403):
        return ("Cloudflare refused the token or the free limit for today is used up" + (f" ({msg})" if msg else "") +
                ". Check that the API token has Workers AI -> Read and Edit, belongs to this account, and was pasted whole.")
    if status == 404:
        return "Cloudflare does not know this account ID. Check the Account ID (32 letters and numbers) on the Workers AI -> REST API page."
    if status == 429:
        return "The free allowance for today is used up (it resets at 00:00 UTC). Thumbnails are made the Better way until then."
    return f"Cloudflare answered with an error (HTTP {status}{': ' + msg if msg else ''})."


def _note(ok: bool, why: str = "") -> None:
    """Remember the last outcome so Settings can show it (the Test button and the last real thumbnail)."""
    try:
        import time as _t
        from app.models import System
        System.set_fields("thumb_best", {"last_ok": ok, "last_error": "" if ok else why[:300], "last_t": _t.time()}, upsert=True)
    except Exception:
        pass


def _request(prompt: str) -> Tuple[Optional[bytes], str]:
    """One FLUX call. Returns (picture bytes, "") or (None, the reason in plain words)."""
    if not cloudflare_ready():
        return None, "The Cloudflare account ID and API token are not both saved yet."
    acc, tok = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip(), os.environ["CLOUDFLARE_API_TOKEN"].strip()
    try:
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{CF_MODEL}", headers={"Authorization": f"Bearer {tok}"},
                          json={"prompt": prompt[:2000], "steps": 4}, timeout=120)
    except requests.RequestException as e:
        return None, f"Could not reach Cloudflare ({type(e).__name__})."
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code != 200:
        return None, _why(r.status_code, data)
    b64 = ((data.get("result") or data).get("image")) if isinstance(data, dict) else None
    if not b64:
        return None, "Cloudflare answered but sent no picture."
    try:
        return base64.b64decode(b64), ""
    except Exception:
        return None, "Cloudflare sent a picture the studio could not read."


def test() -> Dict:
    """The Settings test: are the keys the right shape, does Cloudflare draw a picture, does Gemini answer? Says what is wrong in plain words. Nothing is billed."""
    acc, tok = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip(), (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if not acc or not tok:
        return {"ok": False, "message": "Save the Cloudflare account ID and the API token first (both boxes), then test again."}
    if not re.fullmatch(r"[0-9a-fA-F]{32}", acc):
        hint = " It looks like the token was pasted into the account ID box." if len(acc) > 36 else ""
        return {"ok": False, "message": "The account ID should be 32 letters and numbers with no spaces." + hint + " Copy it again from the Workers AI -> REST API page."}
    if tok == acc or acc in tok:
        return {"ok": False, "message": "The same value is in both boxes. The account ID goes in the first box and the long API token in the second."}
    if len(tok) < 30 or re.search(r"\s", tok):
        return {"ok": False, "message": "The API token looks too short or has a space in it. Create a new token and copy all of it."}
    raw, why = _request("a simple red apple on a wooden table, bright colours")
    if raw is None:
        _note(False, why)
        return {"ok": False, "message": why}
    try:
        from PIL import Image
        size = Image.open(io.BytesIO(raw)).size
    except Exception:
        size = (0, 0)
    _note(True)
    msg = f"Cloudflare drew a test picture ({size[0]}x{size[1]}). "
    if not gemini_ready():
        return {"ok": False, "message": msg + "But the Gemini key is not saved, and Best needs it to plan the thumbnail."}
    try:
        _gemini_json([{"text": 'Reply with exactly this JSON: {"ok": true}'}], "thumb-test", 40)
    except Exception as e:
        return {"ok": False, "message": msg + f"But Gemini did not answer ({str(e)[:100]}). Check the Gemini key."}
    return {"ok": True, "message": msg + "Gemini answered too. Best thumbnails are ready."}


def status() -> Dict:
    try:
        from app.models import System
        d = System.find_one(id="thumb_best") or {}
    except Exception:
        d = {}
    return {"cloudflare": cloudflare_ready(), "gemini": gemini_ready(), "ready": ready(), "last_ok": d.get("last_ok"), "last_error": d.get("last_error") or "", "last_t": d.get("last_t") or 0}


def draw(prompt: str, out: Path, mode: str) -> Optional[Path]:
    """Ask FLUX (Cloudflare Workers AI) for one picture. Returns the saved file, or None (not set up, quota used up, busy). Records the picture for billing only when it worked."""
    if not cloudflare_ready():
        return None
    raw, why = _request(prompt)
    if raw is None:
        print(f"[Thumbnail] FLUX did not draw it: {why}", flush=True)
        _note(False, why)
        return None
    try:
        _fit(raw, mode, out)
    except Exception as e:
        print(f"[Thumbnail] FLUX picture could not be used ({type(e).__name__}: {str(e)[:100]})", flush=True)
        _note(False, "Cloudflare sent a picture the studio could not read.")
        return None
    _note(True)
    try:
        from app.models import UsageEvent
        UsageEvent.record("image", provider="flux", task="thumbnail", units=1)
    except Exception:
        pass
    return out
