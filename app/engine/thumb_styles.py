"""Thumbnail looks. Every look draws the same ingredients (a picture, a headline, a small tag, an optional logo) in a different way,
so the thumbnails of a channel do not all look alike. Fonts, text colour and accent colour are chosen per video or from the member's own look.
"""
import math
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.engine import thumbnail_generator as tg

STYLES = [("classic", "Classic"), ("bottom", "Headline at the bottom"), ("sticker", "Big sticker word"), ("burst", "Comic burst"),
          ("cinema", "Cinema bars"), ("split", "Split panel"), ("minimal", "Minimal"), ("polaroid", "Photo card")]
STYLE_IDS = [s[0] for s in STYLES]
FONTS = {"anton": ("Anton", "Anton-Regular.ttf"), "bebas": ("Bebas Neue", "BebasNeue-Regular.ttf"), "bangers": ("Bangers (comic)", "Bangers-Regular.ttf"),
         "righteous": ("Righteous", "Righteous-Regular.ttf"), "marker": ("Permanent Marker", "PermanentMarker-Regular.ttf")}
DEFAULT_TEXT, DEFAULT_ACCENT, DEFAULT_FONT = "#FFE600", "#FF2D87", "anton"


def valid_color(c: Optional[str], default: str) -> str:
    c = (c or "").strip()
    return c if len(c) == 7 and c[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in c[1:]) else default


def available_fonts() -> List[Dict]:
    fonts_dir = Path(__file__).resolve().parents[2] / "fonts"
    return [{"id": k, "name": v[0]} for k, v in FONTS.items() if (fonts_dir / v[1]).is_file()]


LOOK: Dict = {}        # the recipe's look for the thumbnail being drawn: {"sat": colour strength, "vignette": corner darkness}


def pick_style(uid: Optional[str] = None, fixed: Optional[str] = None, prefer: Optional[List[str]] = None) -> str:
    """A style for this member's next video: their own fixed choice, else one that suits the kind of video (the recipe) and is not one of their last two."""
    if fixed in STYLE_IDS:
        return fixed
    recent: List[str] = []
    if uid:
        try:
            from app.models import Video
            recent = [v.get("thumb_style") for v in Video.find_all(user_id=str(uid), order=("-created_at",), limit=2, only=("thumb_style",))]
        except Exception:
            pass
    fav = [s for s in (prefer or []) if s in STYLE_IDS]
    pool = [s for s in fav if s not in recent] or [s for s in STYLE_IDS if s not in recent] or STYLE_IDS
    return random.choice(pool)


# ------------------------------------------------------------------ helpers
def _punch(img: Image.Image) -> Image.Image:
    k = max(1.2, min(2.0, 1.8 * float(LOOK.get("sat", 1.2)) / 1.2))      # colour strength from the recipe (1.8 when there is none)
    out = ImageEnhance.Contrast(ImageEnhance.Brightness(ImageEnhance.Color(img).enhance(k)).enhance(1.12)).enhance(1.2)
    v = float(LOOK.get("vignette", 0) or 0)
    if v > 0.05:                                                           # darker corners pull the eye to the middle
        w, h = out.size
        mask = Image.radial_gradient("L").resize((w, h))                  # 0 in the middle, 255 at the corners
        out = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), out, mask.point(lambda p: int(p * min(0.6, v))))
    return out


def _canvas(c: Dict, dim: float = 1.0) -> Image.Image:
    base = c["art"] or c["frame"]
    img = tg._cover(base, (c["W"], c["H"])).convert("RGBA") if base is not None else Image.new("RGBA", (c["W"], c["H"]), (20, 20, 30, 255))
    img = _punch(img)
    return ImageEnhance.Brightness(img).enhance(dim) if dim != 1.0 else img


def _vgrad(img: Image.Image, y0: float, y1: float, a0: int, a1: int) -> Image.Image:
    """A black fade from alpha a0 at y0 to a1 at y1 (fractions of the height)."""
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for yy in range(H):
        t = (yy / H - y0) / max(1e-6, (y1 - y0))
        d.line([(0, yy), (W, yy)], fill=(0, 0, 0, int(a0 + (a1 - a0) * min(1.0, max(0.0, t)))))
    return Image.alpha_composite(img, layer)


def _pill(d, xy: Tuple[int, int], text: str, font, fill, color="white", pad: int = 26) -> int:
    w = int(d.textlength(text, font=font)) + 2 * pad
    h = int(font.size * 1.55)
    d.rounded_rectangle([xy[0], xy[1], xy[0] + w, xy[1] + h], radius=h // 2, fill=fill)
    d.text((xy[0] + pad, xy[1] + int(font.size * 0.25)), text, font=font, fill=color)
    return w


def _lines(d, c: Dict, max_w: int, start: int, max_lines: int, min_size: int = 40):
    return tg._wrap(d, c["headline"], max_w, start, max_lines, min_size)


def _text_block(d, lines, font, x, y, color, stroke, shadow, align="left", width=0):
    for ln in lines:
        tx = x if align == "left" else x + (width - d.textlength(ln, font=font)) // 2
        tg.draw_stroked_text(d, (int(tx), int(y)), ln, font, color, "black", stroke, shadow)
        y += int(font.size * 1.08)
    return y


def _tag(d, c: Dict, x: int, y: int) -> None:
    tag = (c["subtext"] or "").upper()[:26]
    if tag:
        _pill(d, (x, y), tag, tg.get_font(38 if c["mode"] == "9:16" else 30), c["accent"])


# ------------------------------------------------------------------ the looks
def style_classic(c: Dict) -> Image.Image:
    """The original look: artwork background, the real frame as a card, a big yellow headline and a pink tag."""
    W, H, mode = c["W"], c["H"], c["mode"]
    img = _canvas(c)
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(grad)
    for yy in range(H):
        top = max(0.0, 1 - yy / (H * 0.5))
        bot = max(0.0, (yy - H * 0.55) / (H * 0.45))
        g.line([(0, yy), (W, yy)], fill=(0, 0, 0, int(150 * max(top, bot * 0.7))))
    img = Image.alpha_composite(img, grad)
    draw = ImageDraw.Draw(img)
    art, frame = c["art"], c["frame"]
    if art is not None and frame is not None:
        if mode == "9:16":
            card = tg._rounded_card(frame, (900, 560))
            img.alpha_composite(card, ((W - card.width) // 2, 880))
        else:
            card = tg._rounded_card(frame, (560, 350))
            img.alpha_composite(card, (W - card.width - 20, (H - card.height) // 2 + 20))
    badge_font = tg.get_font(38 if mode == "9:16" else 32)
    badge = (c["subtext"] or "").upper()[:26]
    if mode == "9:16":
        font, lines = _lines(draw, c, W - 140, 150, 3)
        _text_block(draw, lines, font, 0, 150, c["text"], 10, 6, "center", W)
        if badge:
            bw = draw.textlength(badge, font=badge_font) + 56
            bx, by = (W - bw) // 2, 70
            draw.rounded_rectangle([bx, by, bx + bw, by + 66], radius=33, fill=c["accent"])
            draw.text((bx + 28, by + 12), badge, font=badge_font, fill="white")
    else:
        text_w = int(W * (0.46 if art is not None and frame is not None else 0.88))
        font, lines = _lines(draw, c, text_w, 120, 3)
        y = (H - int(len(lines) * font.size * 1.08)) // 2 + 20
        _text_block(draw, lines, font, 50, y, c["text"], 8, 5)
        if badge:
            bw = draw.textlength(badge, font=badge_font) + 48
            draw.rounded_rectangle([50, 40, 50 + bw, 100], radius=30, fill=c["accent"])
            draw.text((74, 50), badge, font=badge_font, fill="white")
    return img


def style_bottom(c: Dict) -> Image.Image:
    W, H, mode = c["W"], c["H"], c["mode"]
    img = _vgrad(_canvas(c), 0.42, 1.0, 0, 235)
    d = ImageDraw.Draw(img)
    margin = int(W * 0.06)
    font, lines = _lines(d, c, W - 2 * margin, 170 if mode == "9:16" else 130, 3)
    total = int(len(lines) * font.size * 1.08)
    _text_block(d, lines, font, margin, H - total - int(H * 0.06), c["text"], 9, 5, "center" if mode == "9:16" else "left", W - 2 * margin)
    _tag(d, c, margin, int(H * 0.04))
    return img


def style_sticker(c: Dict) -> Image.Image:
    W, H, mode = c["W"], c["H"], c["mode"]
    img = _vgrad(_canvas(c, 0.9), 0.0, 1.0, 40, 130)
    words = c["headline"].upper().split() or ["WOW"]
    first, rest = words[0], " ".join(words[1:])
    d0 = ImageDraw.Draw(img)
    font, _ln = tg._wrap(d0, first, int(W * 0.78), 330 if mode == "9:16" else 250, 1, 80)
    tw, th = int(d0.textlength(first, font=font)), int(font.size * 1.1)
    pad = int(font.size * 0.22)
    sticker = Image.new("RGBA", (tw + 2 * pad + 40, th + 2 * pad + 40), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sticker)
    sd.rounded_rectangle([26, 30, sticker.width - 14, sticker.height - 10], radius=34, fill=(0, 0, 0, 190))
    sd.rounded_rectangle([14, 14, sticker.width - 26, sticker.height - 26], radius=34, fill=c["accent"], outline="white", width=10)
    tg.draw_stroked_text(sd, (14 + pad, 10 + int(pad * 0.3)), first, font, c["text"], "black", 8, 4)
    sticker = sticker.rotate(random.choice([-7, -5, 5, 7]), expand=True, resample=Image.Resampling.BICUBIC)
    sy = int(H * (0.16 if mode == "9:16" else 0.12))
    img.alpha_composite(sticker, ((W - sticker.width) // 2, sy))
    if rest:
        d = ImageDraw.Draw(img)
        f2, l2 = _lines_for(d, rest, int(W * 0.86), 130 if mode == "9:16" else 90, 2)
        _text_block(d, l2, f2, 0, sy + sticker.height + int(H * 0.03), "white", 8, 4, "center", W)
    _tag(ImageDraw.Draw(img), c, int(W * 0.05), int(H * 0.035))
    return img


def _lines_for(d, text: str, max_w: int, start: int, max_lines: int):
    return tg._wrap(d, text, max_w, start, max_lines, 36)


def style_burst(c: Dict) -> Image.Image:
    W, H, mode = c["W"], c["H"], c["mode"]
    img = _vgrad(_canvas(c, 0.85), 0.0, 1.0, 30, 90)
    cx, cy, R, n = W / 2, H * (0.5 if mode == "16:9" else 0.45), min(W, H) * (0.47 if mode == "16:9" else 0.5), 22
    pts = [(cx + (R if i % 2 == 0 else R * 0.74) * math.cos(math.pi * i / n - math.pi / 2), cy + (R if i % 2 == 0 else R * 0.74) * math.sin(math.pi * i / n - math.pi / 2)) for i in range(2 * n)]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.polygon([(x + 12, y + 14) for x, y in pts], fill=(0, 0, 0, 170))
    ld.polygon(pts, fill=c["accent"])
    ld.line(pts + [pts[0]], fill="black", width=9)
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    font, lines = _lines(d, c, int(R * 1.25), 150 if mode == "9:16" else 120, 3)
    total = int(len(lines) * font.size * 1.08)
    _text_block(d, lines, font, cx - R * 0.625, cy - total / 2, c["text"], 8, 5, "center", int(R * 1.25))
    _tag(d, c, int(W * 0.05), int(H * 0.035))
    return img


def style_cinema(c: Dict) -> Image.Image:
    W, H, mode = c["W"], c["H"], c["mode"]
    img = _canvas(c)
    d = ImageDraw.Draw(img)
    bar = int(H * (0.15 if mode == "16:9" else 0.1))
    d.rectangle([0, 0, W, bar], fill=(0, 0, 0, 255))
    d.rectangle([0, H - bar, W, H], fill=(0, 0, 0, 255))
    d.rectangle([0, bar, W, bar + 8], fill=c["accent"])
    d.rectangle([0, H - bar - 8, W, H - bar], fill=c["accent"])
    tag = (c["subtext"] or "").upper()[:30]
    if tag:
        tf = tg.get_font(34 if mode == "9:16" else 30)
        d.text(((W - d.textlength(tag, font=tf)) // 2, (bar - tf.size) // 2), tag, font=tf, fill=c["accent"])
    font, lines = _lines(d, c, W - int(W * 0.1), int(bar * 0.8), 1, 30)
    line = " ".join(lines)
    bb = d.textbbox((0, 0), line, font=font)         # centre the real ink of the text inside the bar
    d.text(((W - (bb[2] - bb[0])) // 2 - bb[0], H - bar + (bar - (bb[3] - bb[1])) // 2 - bb[1]), line, font=font, fill=c["text"])
    return img


def style_split(c: Dict) -> Image.Image:
    W, H, mode = c["W"], c["H"], c["mode"]
    img = _canvas(c)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if mode == "16:9":
        poly = [(0, 0), (int(W * 0.5), 0), (int(W * 0.4), H), (0, H)]
        box = (int(W * 0.04), int(H * 0.1), int(W * 0.40), int(H * 0.9))
    else:
        poly = [(0, int(H * 0.56)), (W, int(H * 0.5)), (W, H), (0, H)]
        box = (int(W * 0.06), int(H * 0.6), int(W * 0.94), int(H * 0.96))
    ld.polygon([(x + 10, y + 10) for x, y in poly], fill=(0, 0, 0, 150))
    ld.polygon(poly, fill=c["accent"] + "E6" if len(c["accent"]) == 7 else c["accent"])
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    bw, bh = box[2] - box[0], box[3] - box[1]
    font, lines = _lines(d, c, bw, 150 if mode == "9:16" else 125, 4)
    total = int(len(lines) * font.size * 1.08)
    _text_block(d, lines, font, box[0], box[1] + max(0, (bh - total) // 2), c["text"], 8, 5, "left")
    _tag(d, c, box[0], int(H * 0.04) if mode == "16:9" else int(H * 0.04))
    return img


def style_minimal(c: Dict) -> Image.Image:
    W, H, mode = c["W"], c["H"], c["mode"]
    img = _canvas(c, 1.0)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * 0.25, -H * 0.25, W * 1.25, H * 1.25], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(int(min(W, H) * 0.12)))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 150))
    img = Image.composite(img, Image.alpha_composite(img, dark), vig)
    d = ImageDraw.Draw(img)
    font, lines = _lines(d, c, int(W * 0.8), 90 if mode == "9:16" else 80, 2, 36)
    line = "  ".join(lines) if len(lines) == 1 else "\n".join(lines)
    tw = max(int(d.textlength(l, font=font)) for l in lines)
    ph = int(len(lines) * font.size * 1.15) + 40
    x0, y0 = (W - tw - 70) // 2, H - ph - int(H * 0.07)
    d.rounded_rectangle([x0, y0, x0 + tw + 70, y0 + ph], radius=26, fill=(0, 0, 0, 175))
    d.rectangle([x0, y0 + 14, x0 + 10, y0 + ph - 14], fill=c["accent"])
    yy = y0 + 20
    for ln in lines:
        d.text((x0 + 42, yy), ln, font=font, fill=c["text"])
        yy += int(font.size * 1.15)
    _tag(d, c, x0, y0 - int(tg.get_font(30).size * 1.9))
    return img


def style_polaroid(c: Dict) -> Image.Image:
    W, H, mode = c["W"], c["H"], c["mode"]
    base = c["art"] or c["frame"]
    bg = tg._cover(base, (W, H)).convert("RGBA").filter(ImageFilter.GaussianBlur(22)) if base is not None else Image.new("RGBA", (W, H), (20, 20, 30, 255))
    bg = Image.alpha_composite(_punch(bg), Image.new("RGBA", (W, H), tuple(int(c["accent"][i:i + 2], 16) for i in (1, 3, 5)) + (120,)))
    photo = c["frame"] or c["art"]
    d = ImageDraw.Draw(bg)
    if photo is not None:
        cw = int(W * (0.62 if mode == "16:9" else 0.86))
        card = tg._rounded_card(photo, (cw, int(cw * (9 / 16 if mode == "16:9" else 0.62))), border=14, radius=26).rotate(random.choice([-4, 4]), expand=True, resample=Image.Resampling.BICUBIC)
        bg.alpha_composite(card, ((W - card.width) // 2, int(H * (0.3 if mode == "16:9" else 0.36))))
    font, lines = _lines(d, c, int(W * 0.9), 120 if mode == "9:16" else 100, 2)
    _text_block(d, lines, font, 0, int(H * 0.04), c["text"], 8, 5, "center", W)
    _tag(d, c, int(W * 0.05), int(H * 0.93) - 40)
    return bg


STYLE_FUNCS = {"classic": style_classic, "bottom": style_bottom, "sticker": style_sticker, "burst": style_burst, "cinema": style_cinema,
               "split": style_split, "minimal": style_minimal, "polaroid": style_polaroid}


def _paste_logo(img: Image.Image, logo: Optional[Image.Image]) -> None:
    if logo is None:
        return
    W, H = img.size
    lw = int(W * (0.15 if W > H else 0.2))
    lg = logo.resize((lw, max(1, int(logo.height * lw / logo.width))), Image.Resampling.LANCZOS)
    img.alpha_composite(lg, (W - lw - int(W * 0.03), int(H * 0.03)))


def render(art: Optional[Image.Image], frame: Optional[Image.Image], *, style: str = "classic", mode: str = "16:9", headline: str = "", subtext: str = "",
           text: str = DEFAULT_TEXT, accent: str = DEFAULT_ACCENT, font: str = DEFAULT_FONT, logo: Optional[Image.Image] = None) -> Image.Image:
    """Draw one thumbnail. `art` = AI or uploaded picture (may be None), `frame` = a frame of the video (may be None)."""
    tg.set_font(font if font in FONTS else DEFAULT_FONT)
    W, H = (1280, 720) if mode == "16:9" else (1080, 1920)
    c = {"W": W, "H": H, "mode": mode, "art": art, "frame": frame, "headline": (headline or "WATCH THIS").strip(), "subtext": subtext or "",
         "text": valid_color(text, DEFAULT_TEXT), "accent": valid_color(accent, DEFAULT_ACCENT)}
    img = STYLE_FUNCS.get(style, style_classic)(c)
    _paste_logo(img, logo)
    return img.convert("RGB")
