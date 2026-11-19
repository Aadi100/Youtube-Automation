import subprocess
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from app.config import FFMPEG_BIN, OUTPUT_DIR

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

def get_font(size: int):
    """The bundled bold font (same look on every computer), else a system font."""
    font_candidates = [
        str(Path(__file__).resolve().parents[2] / "fonts" / "Anton-Regular.ttf"),
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


def generate_thumbnail(
    video_path: Optional[Path] = None,
    background_image: Optional[Path] = None,
    headline: str = "INSANE MOMENT!",
    subtext: str = "GTA 6 GAMEPLAY",
    mode: str = "16:9",  # '16:9' (1280x720) or '9:16' (1080x1920)
    output_path: Optional[Path] = None,
    game_name: Optional[str] = None,
    scene: str = "",
) -> Path:
    """High-CTR thumbnail: AI-made artwork as the background, the real video frame as a framed card,
    a big headline that wraps and always fits, and a game badge. Falls back to the video frame if no AI art."""
    target_size = (1280, 720) if mode == "16:9" else (1080, 1920)
    W, H = target_size
    if not output_path:
        stem = video_path.stem if video_path else "gta6_thumb"
        output_path = OUTPUT_DIR / f"{stem}_{mode.replace(':', 'x')}_thumb.jpg"

    # 1. real frame from the video + AI artwork
    frame = None
    if video_path and Path(video_path).exists():
        tmp = output_path.parent / f"{output_path.stem}_frame.jpg"
        try:
            try:   # a frame from the action part of the clip (about two thirds in), not the quiet start
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
    try:
        from app.engine.ai_art import generate_background
        if background_image and Path(background_image).exists():
            art = Image.open(background_image).convert("RGB")
        else:
            got = generate_background(game_name or subtext, mode, art_file, scene=scene)
            if got:
                art = Image.open(got).convert("RGB")
                art.load()
                art = art.crop((0, 0, art.width, int(art.height * 0.94)))   # trims the free service's corner watermark
    except Exception as e:
        print(f"[Thumbnail] AI art skipped: {e}")
    finally:
        art_file.unlink(missing_ok=True)

    base = art or frame
    if base is None:
        base = Image.new("RGB", target_size, (20, 20, 30))
    img = _cover(base, target_size).convert("RGBA")
    img = ImageEnhance.Contrast(ImageEnhance.Brightness(ImageEnhance.Color(img).enhance(1.8)).enhance(1.12)).enhance(1.2)   # brighter, punchier colours

    # 2. dark gradients so text always reads
    grad = Image.new("RGBA", target_size, (0, 0, 0, 0))
    g = ImageDraw.Draw(grad)
    for yy in range(H):
        top = max(0.0, 1 - yy / (H * 0.5))
        bot = max(0.0, (yy - H * 0.55) / (H * 0.45))
        g.line([(0, yy), (W, yy)], fill=(0, 0, 0, int(150 * max(top, bot * 0.7))))
    img = Image.alpha_composite(img, grad)
    draw = ImageDraw.Draw(img)

    # 3. real video frame as a framed card (only when AI art is the background, otherwise it would repeat the same picture)
    if art is not None and frame is not None:
        if mode == "9:16":
            card = _rounded_card(frame, (900, 560))
            img.alpha_composite(card, ((W - card.width) // 2, 880))
        else:
            card = _rounded_card(frame, (560, 350))
            img.alpha_composite(card, (W - card.width - 20, (H - card.height) // 2 + 20))

    # 4. headline + badge
    badge_font = get_font(38 if mode == "9:16" else 32)
    badge = (subtext or game_name or "").upper()[:26]
    if mode == "9:16":
        font, lines = _wrap(draw, headline, W - 140, 150, 3)
        y = 150
        for ln in lines:
            draw_stroked_text(draw, ((W - draw.textlength(ln, font=font)) // 2, y), ln, font, "#FFE600", "black", 10, 6)
            y += int(font.size * 1.08)
        if badge:
            bw = draw.textlength(badge, font=badge_font) + 56
            bx, by = (W - bw) // 2, 70
            draw.rounded_rectangle([bx, by, bx + bw, by + 66], radius=33, fill="#FF2D87")
            draw.text((bx + 28, by + 12), badge, font=badge_font, fill="white")
    else:
        text_w = int(W * (0.46 if art is not None and frame is not None else 0.88))
        font, lines = _wrap(draw, headline, text_w, 120, 3)
        total = int(len(lines) * font.size * 1.08)
        y = (H - total) // 2 + 20
        for ln in lines:
            draw_stroked_text(draw, (50, y), ln, font, "#FFE600", "black", 8, 5)
            y += int(font.size * 1.08)
        if badge:
            bw = draw.textlength(badge, font=badge_font) + 48
            draw.rounded_rectangle([50, 40, 50 + bw, 100], radius=30, fill="#FF2D87")
            draw.text((74, 50), badge, font=badge_font, fill="white")

    final_img = img.convert("RGB")
    final_img.save(output_path, "JPEG", quality=94)
    print(f"[Thumbnail] Generated {mode} thumbnail ({'AI art' if art is not None else 'video frame'}): {output_path}")
    return output_path
