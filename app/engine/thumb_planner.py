"""High level: Claude is the art director of one thumbnail.

It sees up to four frames that code already picked (never twenty), the facts about the video and the recipe for that kind of video, and
answers with a plan: which frame, the headline, the look, the colours and a scene for the background. Afterwards it can look at the
finished thumbnail once and fix the headline. Everything it says is checked before it is used, so a strange answer can never break a thumbnail.
"""
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from app.config import FFMPEG_BIN
from app.engine import claude_util, content_ai
from app.engine.thumb_styles import STYLE_IDS, valid_color

SYSTEM = ("You are the art director of a YouTube gaming channel. You design thumbnails that get clicked: one clear subject, a face or action in the "
          "middle of the picture, 2 to 4 punchy words, strong contrast, and never a promise the video does not keep.")


def _frames(video: Path, td: Path, n: int = 4) -> List[Dict]:
    out = []
    for i, f in enumerate(content_ai.best_frames(Path(video), n)):
        p = td / f"f{i + 1}.jpg"
        subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{f['t']:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(p)], capture_output=True)
        if p.is_file():
            out.append({"t": f["t"], "path": p})
    return out


def _clean_headline(h: str) -> str:
    h = re.sub(r"[^\w\s!?'\-]", "", str(h or "")).strip().upper()
    words = h.split()[:4]
    return " ".join(words)[:22]


def check(plan: Dict, frames: int) -> Dict:
    """Keep only what is valid: a frame number in range, a short headline, a known style, real colours, a plain scene."""
    out: Dict = {}
    try:
        k = int(plan.get("frame"))
        if 1 <= k <= frames:
            out["frame"] = k
    except (TypeError, ValueError):
        pass
    h = _clean_headline(plan.get("headline"))
    if h:
        out["headline"] = h
    if isinstance(plan.get("style"), str) and plan.get("style") in STYLE_IDS:
        out["style"] = plan["style"]
    for k in ("text_color", "accent"):
        v = valid_color(str(plan.get(k) or ""), "")
        if v:
            out[k] = v.upper()
    scene = re.sub(r"[^\w\s,.\-']", "", str(plan.get("art_prompt") or ""))[:220].strip()
    if scene:
        out["scene"] = scene
    out["why"] = str(plan.get("why") or "")[:100]
    return out


def plan(video: Path, ctx: Dict, recipe: Optional[Dict] = None) -> Optional[Dict]:
    """The plan for one thumbnail, or None when Claude is unavailable (the caller then uses the Medium or Free way)."""
    if not claude_util.ready():
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
        content = []
        for i, f in enumerate(fr):
            content += [{"type": "text", "text": f"Frame {i + 1}:"}, claude_util.image_block(f["path"], 512)]
        content.append({"type": "text", "text": facts + f' Pick the best of the {len(fr)} frames. Return JSON: {{"frame": 1-{len(fr)}, "headline": "2-4 words, ALL CAPS, max 20 characters, not the same as the title", '
                        f'"style": one of {STYLE_IDS}, "text_color": "#RRGGBB", "accent": "#RRGGBB", "art_prompt": "one sentence describing a vivid background scene that matches the moment, no text, no real people", "why": "max 12 words"}}'})
        try:
            raw = claude_util.ask_json("thumb-plan", SYSTEM, content, 700)
        except Exception as e:
            print(f"[Thumbnail] Claude plan unavailable ({str(e)[:100]})", flush=True)
            return None
        p = check(raw, len(fr))
        if "frame" in p:
            p["t"] = fr[p["frame"] - 1]["t"]
        print(f"[Thumbnail] Claude plan: frame {p.get('frame')}, '{p.get('headline')}', {p.get('style')} ({p.get('why')})", flush=True)
        return p


def review(thumb: Path, headline: str, ctx: Dict) -> Optional[str]:
    """Claude looks at the finished thumbnail once. Returns a better headline when it thinks the current one is weak, else None."""
    if not claude_util.ready():
        return None
    try:
        raw = claude_util.ask_json("thumb-review", SYSTEM, [claude_util.image_block(thumb, 512), {"type": "text", "text":
                                   f'This is the finished thumbnail for "{ctx.get("title") or ""}". Headline on it: "{headline}". Is it clear, readable and clickable? '
                                   'Return JSON: {"score": 1-10, "headline": "a better 2-4 word ALL CAPS headline, or the same one if it is already good"}'}], 300)
        score = int(raw.get("score") or 0)
        new = _clean_headline(raw.get("headline"))
        print(f"[Thumbnail] Claude review: {score}/10", flush=True)
        return new if new and score < 7 and new != headline.upper() else None
    except Exception as e:
        print(f"[Thumbnail] Claude review skipped ({str(e)[:100]})", flush=True)
        return None
