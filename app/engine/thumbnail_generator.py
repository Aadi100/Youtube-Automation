import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from app.config import FFMPEG_BIN, OUTPUT_DIR

def pictures_wanted(brand: dict) -> int:
    """How many AI pictures a new thumbnail draws: 1, or 3 to choose from later in the Thumbnail studio (this run's choice, else the member's setting)."""
    try:
        n = int(os.environ.get("THUMB_PICTURES") or (brand or {}).get("pictures") or 1)
    except ValueError:
        n = 1
    return 3 if n >= 3 else 1


def slot_of(video: Path, i: int) -> Path:
    """The numbered picture file next to a video (the Thumbnail studio lists these)."""
    p = Path(video)
    return p.with_name(f"{p.stem}_art_{int(i)}.jpg")


def brand_of(uid: Optional[str]) -> dict:
    """A member's own thumbnail look: {style, text, accent, font}. Empty if they have not set one."""
    if not uid:
        return {}
    try:
        from app.models import UserPrefs
        return UserPrefs.of(uid).get("brand") or {}
    except Exception:
        return {}


def logo_path(uid: Optional[str]) -> Optional[Path]:
    if not uid:
        return None
    p = Path(__file__).resolve().parents[2] / "state" / "brands" / f"{uid}.png"
    return p if p.is_file() else None


def logo_of(uid: Optional[str]) -> Optional[Image.Image]:
    p = logo_path(uid)
    try:
        if not p:
            return None
        with Image.open(p) as im:        # close the file again straight away (Windows cannot delete an open file)
            return im.convert("RGBA")
    except Exception:
        return None


def extract_keyframe(video_path: Path, output_image: Path, timestamp: float = 2.0) -> Path:
    """Extracts a frame from a video using FFmpeg."""
    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(output_image)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_image

_local = threading.local()
FONT_FILES = {"anton": "Anton-Regular.ttf", "bebas": "BebasNeue-Regular.ttf", "bangers": "Bangers-Regular.ttf", "righteous": "Righteous-Regular.ttf", "marker": "PermanentMarker-Regular.ttf"}
LAST: dict = {}     # what the last generate_thumbnail() call used (the pipeline stores the style on the video)


def set_font(name: str) -> None:
    _local.font = name if name in FONT_FILES else "anton"


def get_font(size: int):
    """The chosen bundled font (same look on every computer), else a system font."""
    fonts_dir = Path(__file__).resolve().parents[2] / "fonts"
    font_candidates = [
        str(fonts_dir / FONT_FILES.get(getattr(_local, "font", "anton"), "Anton-Regular.ttf")),
        str(fonts_dir / "Anton-Regular.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        r"C:\Windows\Fonts\impact.ttf",
        r"C:\Windows\Fonts\ariblk.ttf",    # Arial Black
        r"C:\Windows\Fonts\arialbd.ttf",   # Arial Bold
        r"C:\Windows\Fonts\segoeuib.ttf",  # Segoe UI Bold
    ]
    for font_path in font_candidates:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_stroked_text(
    draw: ImageDraw.ImageDraw,
    position: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill_color: str,
    stroke_color: str = "black",
    stroke_width: int = 6,
    shadow_offset: int = 5
):
    """Draws text with heavy drop shadow and thick stroke for high readability."""
    x, y = position
    
    # Shadow
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0, 200), stroke_width=stroke_width, stroke_fill="black")
    # Main text with outline
    draw.text((x, y), text, font=font, fill=fill_color, stroke_width=stroke_width, stroke_fill=stroke_color)

def _cover(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    """Resize + centre-crop so the image fills `size` without stretching."""
    w, h = img.size
    scale = max(size[0] / w, size[1] / h)
    img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
    x, y = (img.width - size[0]) // 2, (img.height - size[1]) // 2
    return img.crop((x, y, x + size[0], y + size[1]))


def _wrap(draw: ImageDraw.ImageDraw, text: str, max_w: int, start_size: int, max_lines: int, min_size: int = 40):
    """Largest font (<= start_size) whose wrapped text fits max_w in at most max_lines lines."""
    words = text.upper().split()
    for size in range(start_size, min_size - 1, -4):
        font = get_font(size)
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=font) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font) <= max_w for l in lines):
            return font, lines
    return get_font(min_size), lines[:max_lines]


def _rounded_card(frame: Image.Image, size: Tuple[int, int], border: int = 8, radius: int = 34) -> Image.Image:
    """The real video frame as a rounded card with a white border and a soft shadow."""
    card = _cover(frame.convert("RGB"), size).convert("RGBA")
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    pad = 40
    out = Image.new("RGBA", (size[0] + 2 * border + 2 * pad, size[1] + 2 * border + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([pad, pad + 14, pad + size[0] + 2 * border, pad + size[1] + 2 * border + 14], radius=radius + border, fill=(0, 0, 0, 170))
    out = Image.alpha_composite(out, shadow.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(out).rounded_rectangle([pad, pad, pad + size[0] + 2 * border, pad + size[1] + 2 * border], radius=radius + border, fill=(255, 255, 255, 255))
    out.paste(card, (pad + border, pad + border), mask)
    return out


TIERS = ("better", "best")
LEGACY = {"free": "better", "medium": "better", "high": "best"}      # the older level names (saved settings, queued videos) still work


def norm_tier(t: Optional[str]) -> str:
    t = (t or "").strip().lower()
    t = LEGACY.get(t, t)
    return t if t in TIERS else "better"


def tier_of(requested: Optional[str] = None, brand: Optional[dict] = None) -> str:
    """The level for this thumbnail: this run's choice, else the member's setting, else Better. Best needs the Gemini key and the FLUX (Cloudflare) keys."""
    t = norm_tier(requested or os.environ.get("THUMB_TIER") or (brand or {}).get("tier"))
    if t == "best":
        from app.engine import thumb_best
        if not thumb_best.ready():
            return "better"
    return t


def generate_thumbnail(
    video_path: Optional[Path] = None,
    background_image: Optional[Path] = None,
    headline: str = "INSANE MOMENT!",
    subtext: str = "GAMEPLAY",
    mode: str = "16:9",  # '16:9' (1280x720) or '9:16' (1080x1920)
    output_path: Optional[Path] = None,
    game_name: Optional[str] = None,
    scene: str = "",
    style: Optional[str] = None,
    text_color: Optional[str] = None,
    accent: Optional[str] = None,
    font: Optional[str] = None,
    art_stem: Optional[Path] = None,
    content_type: Optional[str] = None,
    tier: Optional[str] = None,
    context: Optional[dict] = None,
) -> Path:
    """High-CTR thumbnail: artwork as the background, the real video frame as a framed card, a big headline that always fits, a game badge.
    Two levels. better: a free AI image behind the real frame, the best frame found by code, the headline drawn by code.
    best: Gemini looks at the best frames and plans the thumbnail (frame, headline, look, scene), FLUX draws the finished thumbnail (headline included, or the
    picture only when THUMB_TEXT=code), and Gemini can check the result once (THUMB_REVIEW=on). Every failure falls back to Better. Falls back to the video frame if there is no AI art."""
    from app.engine import playbook, thumb_styles
    target_size = (1280, 720) if mode == "16:9" else (1080, 1920)
    W, H = target_size
    if not output_path:
        stem = video_path.stem if video_path else "clipstudio_thumb"
        output_path = OUTPUT_DIR / f"{stem}_{mode.replace(':', 'x')}_thumb.jpg"
    uid = os.environ.get("CLIPSTUDIO_USER_ID") or None
    brand = brand_of(uid)
    recipe = playbook.recipe_for(content_type)               # what popular thumbnails of this kind of video look like (measured once, kept as numbers)
    tier = tier_of(tier, brand)
    requested_tier = tier
    ctx = {**(context or {}), "game": game_name or subtext, "content_type": content_type}

    # 0. Best: Gemini plans it (the plan is checked; if Gemini cannot, the level drops to Better)
    plan = None
    if tier == "best" and video_path and Path(video_path).exists():
        try:
            from app.engine import thumb_best
            plan = thumb_best.plan(Path(video_path), ctx, recipe)
        except Exception as e:
            print(f"[Thumbnail] Gemini plan failed: {e}")
        if not plan:
            tier = "better"
            print("[Thumbnail] Best level not available this time - using Better")
    if plan:
        scene = plan.get("scene") or scene
        headline = plan.get("headline") or headline

    # 1. real frame from the video + AI artwork
    frame = None
    ref_file = output_path.parent / f"{output_path.stem}_ref.jpg"
    if video_path and Path(video_path).exists():
        tmp = output_path.parent / f"{output_path.stem}_frame.jpg"
        try:
            ts = (plan or {}).get("t")
            if ts is None:
                try:   # the most thumbnail-worthy frame (sharp, colourful, moving, a face), found by code: no AI, no tokens
                    from app.engine import content_ai
                    ts = content_ai.best_time(Path(video_path))
                    if ts is None:
                        raise ValueError("no frame found")
                except Exception:
                    try:   # fall back to the action part of the clip (about two thirds in), not the quiet start
                        from app.engine.video_processor import get_video_info
                        ts = max(1.0, float(get_video_info(Path(video_path))["duration"]) * 0.65)
                    except Exception:
                        ts = 3.0
            extract_keyframe(Path(video_path), tmp, timestamp=ts)
            frame = Image.open(tmp).convert("RGB")
            frame.load()
            if frame.height > frame.width * 1.4:   # a finished vertical Short: keep only its sharp middle band, not the blurred bars
                frame = frame.crop((0, int(frame.height * 0.34), frame.width, int(frame.height * 0.66)))
            frame = frame.crop((0, 0, frame.width, int(frame.height * 0.82)))   # drop the bottom: creators' own subtitles and watermarks live there
        except Exception:
            frame = None
        finally:
            tmp.unlink(missing_ok=True)
    art = None
    art_file = output_path.parent / f"{output_path.stem}_ai.jpg"
    n_pics = pictures_wanted(brand)
    ref = None
    flux_headline = headline
    try:
        from app.engine.ai_art import generate_background
        if background_image and Path(background_image).exists():
            art = Image.open(background_image).convert("RGB")
        else:
            got = None
            if tier == "best":                        # FLUX draws it (the headline is part of the picture unless the setting says the studio writes it)
                from app.engine import thumb_best
                with_text = not thumb_best.text_by_code()
                got = thumb_best.draw(thumb_best.build_prompt(game_name or subtext, scene, headline, mode, with_text), art_file, mode)
                if got and with_text and thumb_best.review_on():
                    better = thumb_best.review(got, headline, ctx)           # optional: Gemini checks the printed headline once
                    if better:
                        again = thumb_best.draw(thumb_best.build_prompt(game_name or subtext, scene, better, mode, True), art_file, mode)
                        if again:
                            got, flux_headline = again, better
                if not got:
                    tier = "better"
                    print("[Thumbnail] FLUX could not draw it this time - using Better")
            if not got:
                got = generate_background(game_name or subtext, mode, art_file, scene=scene, ref=ref, tier=tier)
            if got:
                art = Image.open(got).convert("RGB")
                art.load()
                if tier != "best":
                    art = art.crop((0, 0, art.width, int(art.height * 0.94)))   # trims the free service's corner watermark
                if art_stem is not None and n_pics > 1:    # the member asked for 3 pictures to choose from: keep them next to the video
                    shutil.copyfile(got, slot_of(art_stem, 1))
                    for i in range(2, n_pics + 1):
                        try:
                            if tier == "best":
                                from app.engine import thumb_best
                                thumb_best.draw(thumb_best.build_prompt(game_name or subtext, scene, flux_headline, mode, not thumb_best.text_by_code()), slot_of(art_stem, i), mode)
                            else:
                                generate_background(game_name or subtext, mode, slot_of(art_stem, i), scene=scene, ref=ref, tier=tier)
                        except Exception as e:
                            print(f"[Thumbnail] extra picture {i} skipped: {e}")
    except Exception as e:
        print(f"[Thumbnail] AI art skipped: {e}")
    finally:
        art_file.unlink(missing_ok=True)
        ref_file.unlink(missing_ok=True)

    # Best with FLUX writing the headline: the picture IS the thumbnail
    if tier == "best" and art is not None and not background_image:
        from app.engine import thumb_best
        if not thumb_best.text_by_code():
            art.save(output_path, "JPEG", quality=94)
            LAST.update({"style": None, "recipe": content_type if recipe else None, "tier": "best", "headline": flux_headline})
            print(f"[Thumbnail] Generated {mode} thumbnail (best, FLUX): {output_path}")
            return output_path

    # 2. the look: the member's own settings win, then Claude's plan, then the recipe for this kind of video
    p = plan or {}
    fixed_style = brand.get("style") if brand.get("style") in thumb_styles.STYLE_IDS else None
    style = style or fixed_style or p.get("style") or thumb_styles.pick_style(uid, None, (recipe or {}).get("styles"))
    tcol = text_color or brand.get("text") or p.get("text_color") or (recipe or {}).get("text_color")
    acol = accent or brand.get("accent") or p.get("accent") or (recipe or {}).get("accent")
    if recipe:
        headline = playbook.headline_for(recipe, headline)
        thumb_styles.LOOK.clear()
        thumb_styles.LOOK.update(sat=recipe.get("sat_boost", 1.2), vignette=recipe.get("vignette", 0))

    def draw(text: str) -> Image.Image:
        return thumb_styles.render(art, frame, style=style, mode=mode, headline=text, subtext=subtext or (game_name or ""), text=tcol, accent=acol,
                                   font=font or brand.get("font"), logo=logo_of(uid))
    try:
        img = draw(headline)
        img.save(output_path, "JPEG", quality=94)
        if plan and tier == "best":               # Best with the studio writing the headline: Gemini may check the finished thumbnail once (optional)
            from app.engine import thumb_best
            better = thumb_best.review(output_path, headline, ctx) if thumb_best.review_on() else None
            if better:
                headline = playbook.headline_for(recipe, better)
                img = draw(headline)
                img.save(output_path, "JPEG", quality=94)
    finally:
        thumb_styles.LOOK.clear()
    LAST["style"] = style
    LAST["recipe"] = content_type if recipe else None
    from app.engine import ai_art as _art
    used = "best" if (tier == "best" and art is not None) else "better"
    if used == "better" and requested_tier == "best":
        print("[Thumbnail] the Best level could not be used this time (the picture came from the free service); it is recorded and billed as Better")
    LAST["tier"] = used
    LAST["headline"] = headline
    print(f"[Thumbnail] Generated {mode} thumbnail ({style}, {tier}, {'AI art' if art is not None else 'video frame'}): {output_path}")
    return output_path
