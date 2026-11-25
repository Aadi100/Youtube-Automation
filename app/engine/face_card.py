"""The streamer's face for the thumbnail, only when the video really has a face camera.

Gaming thumbnails work best with a big, readable reaction face. When the clip has a webcam (a face that stays in about the same place across the clip,
which is how a face camera is told apart from a game character), the sharpest and most expressive frame of that face is cut out and placed on the
thumbnail as a rounded card in a corner that is free of the headline. Nothing is compulsory:
  * no webcam, no steady face, a face too small to look good, or the face finder not available -> None, and the thumbnail is made as before;
  * THUMB_FACE=off (Settings) or the member's own choice 'never' switches it off.
It is plain OpenCV (the same face finder the studio already uses): no AI service, no tokens, nothing sent anywhere.
"""
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageChops, ImageEnhance

MIN_FACE_PX = 70          # a face smaller than this looks blurry when it is made big
SAMPLES = 12


def enabled(brand: Optional[Dict] = None) -> bool:
    """On unless the owner (THUMB_FACE=off) or the member (brand face = off) switched it off."""
    if (os.environ.get("THUMB_FACE") or "on").strip().lower() in ("off", "0", "no", "false"):
        return False
    return (brand or {}).get("face", "on") != "off"


def _sharp(gray) -> float:
    import cv2
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def make(video: Path, brand: Optional[Dict] = None) -> Optional[Dict]:
    """{"image": RGB card picture, "w": face width in pixels, "t": second it was taken} or None when this video has no usable face camera."""
    if not enabled(brand):
        return None
    try:
        import cv2
        from app.engine import face_signals
        from app.engine.video_processor import get_video_info
        if not face_signals.available():
            return None
        info = get_video_info(Path(video))
        dur = float(info.get("duration") or 0)
        if dur <= 0:
            return None
        box = face_signals.find_face_box(Path(video), dur)           # a face that stays put: the face camera
        if not box:
            return None
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            return None
        best: Optional[Tuple[float, object, Dict]] = None
        try:
            for i in range(SAMPLES):
                cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, dur * (0.08 + 0.84 * i / (SAMPLES - 1))) * 1000)
                ok, fr = cap.read()
                if not ok:
                    continue
                H, W = fr.shape[:2]
                cx, cy = (box["x"] + box["w"] / 2) * W, (box["y"] + box["h"] / 2) * H
                found = [f for f in (face_signals.detect(fr) or []) if abs(f["x"] + f["w"] / 2 - cx) < 0.18 * W and abs(f["y"] + f["h"] / 2 - cy) < 0.18 * H]
                if not found:
                    continue
                f = found[0]
                if f["w"] < MIN_FACE_PX:
                    continue
                x0, y0 = max(0, int(f["x"])), max(0, int(f["y"]))
                crop = fr[y0:int(f["y"] + f["h"]), x0:int(f["x"] + f["w"])]
                if crop.size == 0:
                    continue
                sharp = min(1.0, _sharp(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)) / 400.0)
                ex = face_signals.expression(fr, f) or {}
                react = max(ex.get("happy", 0.0), ex.get("surprise", 0.0))        # a reaction face is what people click
                score = 0.45 * sharp + 0.35 * react + 0.2 * min(1.0, f["w"] / (0.16 * W)) + 0.1 * f["score"]
                if best is None or score > best[0]:
                    best = (score, fr.copy(), {**f, "t": dur * (0.08 + 0.84 * i / (SAMPLES - 1))})
        finally:
            cap.release()
        if best is None:
            return None
        _score, fr, f = best
        H, W = fr.shape[:2]
        cw, ch = f["w"] * 2.1, f["h"] * 2.7                                   # the head with hair, and the shoulders
        x0 = int(max(0, min(W - cw, f["x"] + f["w"] / 2 - cw / 2)))
        y0 = int(max(0, min(H - ch, f["y"] - f["h"] * 0.75)))
        crop = fr[y0:min(H, int(y0 + ch)), x0:min(W, int(x0 + cw))]
        if crop.size == 0:
            return None
        img = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        k = min(4.0, 720.0 / img.height)
        img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
        img = ImageEnhance.Contrast(ImageEnhance.Sharpness(img).enhance(1.4)).enhance(1.08)
        return {"image": img, "w": int(f["w"]), "t": float(f["t"])}
    except Exception as e:
        print(f"[Thumbnail] no streamer face this time ({type(e).__name__}: {str(e)[:80]})", flush=True)
        return None


def _box(canvas: Tuple[int, int], mode: str) -> Tuple[int, int]:
    """The most room the face card may take: a third of a wide thumbnail, about half of a tall one."""
    W, H = canvas
    return (int(W * 0.56), int(H * 0.36)) if mode == "9:16" else (int(W * 0.31), int(H * 0.68))


def text_bbox(with_text: Image.Image, without_text: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    """Where the headline is: the area that differs between a thumbnail drawn with and without it."""
    diff = ImageChops.difference(with_text.convert("RGB"), without_text.convert("RGB")).convert("L").point(lambda v: 255 if v > 40 else 0)
    return diff.getbbox()


def place(img: Image.Image, face: Dict, mode: str, side: str = "right", avoid: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
    """The thumbnail with the face card in the corner where it hides the least of the headline (bottom corners first). The picture is returned as a new image."""
    from app.engine import thumbnail_generator as tg
    W, H = img.size
    bw, bh = _box((W, H), mode)
    fw, fh = face["image"].size
    k = min(bw / fw, bh / fh)
    size = (max(40, int(fw * k)), max(40, int(fh * k)))
    card = tg._rounded_card(face["image"], size, border=8, radius=30)          # white border and a soft shadow
    cw, ch = card.size
    mx, my = int(W * 0.015), int(H * 0.012)
    corners = {"bottom-right": (W - cw - mx, H - ch - my), "bottom-left": (mx, H - ch - my), "top-right": (W - cw - mx, my), "top-left": (mx, my)}
    order = [f"bottom-{side}", f"bottom-{'left' if side == 'right' else 'right'}", f"top-{side}", f"top-{'left' if side == 'right' else 'right'}"]
    def overlap(pos):
        if not avoid:
            return 0
        x, y = pos
        ox = max(0, min(x + cw, avoid[2]) - max(x, avoid[0])); oy = max(0, min(y + ch, avoid[3]) - max(y, avoid[1]))
        return ox * oy
    best = min(order, key=lambda c: (overlap(corners[c]), order.index(c)))
    out = img.convert("RGBA")
    out.alpha_composite(card, corners[best])
    return out.convert("RGB")
