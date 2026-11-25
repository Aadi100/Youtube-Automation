"""Free, local helpers that replace AI calls: find the best frame of a video, and say what kind of video it is.

Nothing here costs tokens. It uses OpenCV (already installed) and plain word lists.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TYPES = ("fail", "funny", "epic", "rage", "scary", "shock", "news", "tutorial", "reaction")
_WORDS = {
    "fail": r"fail|failed|mistake|oops|wrong|crash|crashed|died|dies|fell|falls|noob|backfire|wasted|tripped|gone wrong|worst",
    "funny": r"funny|lol|lmao|hilarious|laugh|joke|meme|prank|comedy|cringe|bruh|ridiculous|silly",
    "epic": r"clutch|insane play|ace|1v\d|victory|win|wins|won|best|perfect|headshot|record|speedrun|legendary|goat|epic|flawless|highlight",
    "rage": r"rage|angry|quit|tilt|screaming|mad|smash|toxic|furious|meltdown|scream|breaks|raging",
    "scary": r"scary|horror|jumpscare|jump scare|creepy|terrifying|haunted|nightmare|spooky",
    "shock": r"shocking|unexpected|leaked|secret|glitch|bug|wait what|no way|unbelievable|crazy|insane|wow|omg|what just|hidden|exposed",
    "news": r"trailer|news|announced|release date|reveal|revealed|update|leak|official|patch|teaser|breaking",
    "tutorial": r"how to|guide|tutorial|tips|tricks|walkthrough|best way|explained|beginner|easy way|learn",
    "reaction": r"react|reacts|reacting|reaction|first time|watching",
}
_RX = {k: re.compile(r"\b(?:" + v + r")\b", re.I) for k, v in _WORDS.items()}


def classify(*texts: str) -> Tuple[str, float]:
    """(type, confidence 0..1) of a video from its title, hook and spoken words. 'funny' when nothing stands out (the safest style for clips)."""
    blob = " ".join(t for t in texts if t)[:3000]
    score: Dict[str, float] = {}
    for k, rx in _RX.items():
        n = len(rx.findall(blob))
        if n:
            score[k] = n * (1.5 if k in ("news", "tutorial") else 1.0)       # these two are rarely said by accident
    if not score:
        return "funny", 0.2
    best = max(score, key=score.get)
    tot = sum(score.values())
    return best, round(min(1.0, 0.3 + score[best] / tot * 0.5 + min(score[best], 4) * 0.05), 2)


# ------------------------------------------------------------------ the best frame
def _faces():
    import cv2
    return cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def frame_candidates(video: Path, samples: int = 16, lo: float = 0.12, hi: float = 0.9) -> List[Dict]:
    """Sample frames of a video and measure each: sharpness, colour, motion and the biggest face. [{t, score, sharp, sat, motion, face}]."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
    if total <= 0:
        cap.release()
        return []
    cas, out, prev = _faces(), [], None
    try:
        for i in range(samples):
            t = total * (lo + (hi - lo) * i / max(1, samples - 1))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            if h > w * 1.4:                                    # a finished vertical Short: look at its sharp middle band, not the blurred bars
                frame = frame[int(h * 0.34):int(h * 0.66)]
                h, w = frame.shape[:2]
            small = cv2.resize(frame, (320, max(2, int(320 * h / w))))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            sat, val = float(hsv[..., 1].mean()), float(hsv[..., 2].mean())
            motion = float(np.abs(gray.astype("int16") - prev).mean()) if prev is not None else 0.0
            prev = gray.astype("int16")
            faces = None
            try:
                from app.engine import face_signals
                fd = face_signals.detect(small, max_side=480)
                if fd is not None:
                    faces = [(f["x"], f["y"], f["w"], f["h"]) for f in fd if f["w"] >= 20]
            except Exception:
                faces = None
            if faces is None:
                faces = cas.detectMultiScale(gray, 1.15, 5, minSize=(24, 24))
            face = max((fw * fh for _, _, fw, fh in faces), default=0) / float(gray.shape[0] * gray.shape[1])
            out.append({"t": round(t, 2), "sharp": sharp, "sat": sat, "val": val, "motion": motion, "face": float(face)})
    finally:
        cap.release()
    if not out:
        return out
    def norm(k):
        v = [o[k] for o in out]
        lo_, hi_ = min(v), max(v)
        return [(x - lo_) / (hi_ - lo_) if hi_ > lo_ else 0.5 for x in v]
    ns, nc, nm = norm("sharp"), norm("sat"), norm("motion")
    for i, o in enumerate(out):
        dark = 0.0 if 45 <= o["val"] <= 225 else -0.35          # too dark or burnt out: a bad thumbnail
        o["score"] = round(0.35 * ns[i] + 0.2 * nc[i] + 0.2 * nm[i] + 0.4 * min(o["face"] * 6, 1.0) + dark, 4)
    return out


def best_frames(video: Path, n: int = 3, spacing: float = 1.5) -> List[Dict]:
    """The n most thumbnail-worthy moments of a video, best first, at least `spacing` seconds apart."""
    cands = sorted(frame_candidates(video), key=lambda c: -c["score"])
    out: List[Dict] = []
    for c in cands:
        if all(abs(c["t"] - o["t"]) >= spacing for o in out):
            out.append(c)
        if len(out) >= n:
            break
    return out


def best_time(video: Path, default: Optional[float] = None) -> Optional[float]:
    try:
        f = best_frames(video, 1)
        return f[0]["t"] if f else default
    except Exception:
        return default
