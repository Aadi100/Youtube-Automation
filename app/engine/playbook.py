"""The thumbnail playbook: what popular YouTube gaming thumbnails look like for each kind of video, measured (not copied).

    python -m app.engine.playbook build        study fresh thumbnails (needs internet, takes a few minutes)
    python -m app.engine.playbook show         print the recipes

For every kind of video (fail, funny, epic, rage, scary, shock, news, tutorial, reaction) we look at the top results YouTube gives for a few
searches and MEASURE each thumbnail with free tools: how big the face is and on which side, how much of the picture is headline text and where,
what colour the headline is, the main colours, how strong the colours and contrast are, and how dark the corners are.
Only the numbers are kept (state/playbook.json). No picture is stored or reused.
A "recipe" is the typical measurement of one kind of video. The thumbnail generator uses it for colours, the style, the headline length and the
look, then your own brand kit (if you set one) still wins.
"""
import json
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import requests

from app.config import STATE_DIR
from app.engine import discovery as D

PATH = STATE_DIR / "playbook.json"
QUERIES = {
    "fail": ["gaming fails funny", "epic game fail"], "funny": ["funny gaming moments", "funniest game moments"], "epic": ["insane clutch gaming", "best gaming plays"],
    "rage": ["gaming rage compilation", "streamer rage quit"], "scary": ["horror game jumpscare", "scary game moments"], "shock": ["gaming glitch unexpected", "shocking game moment"],
    "news": ["new game news trailer", "new game reveal trailer"], "tutorial": ["gaming tutorial how to", "beginner guide game tips"], "reaction": ["streamer reacts to trailer", "reacting to gameplay"],
}
# which of our 8 looks suits which headline position
STYLE_BY_POS = {"top": ["classic", "burst", "sticker"], "middle": ["sticker", "burst", "split", "polaroid"], "bottom": ["bottom", "cinema", "minimal"]}
# sensible starting recipes, used until the first real study has been made (and for any kind with too few thumbnails)
DEFAULT = {
    "fail": {"text_color": "#FFE600", "accent": "#FF2D2D", "styles": ["burst", "sticker", "classic"], "max_words": 3, "sat_boost": 1.25, "vignette": 0.25},
    "funny": {"text_color": "#FFE600", "accent": "#FF2D87", "styles": ["sticker", "classic", "burst"], "max_words": 3, "sat_boost": 1.3, "vignette": 0.15},
    "epic": {"text_color": "#FFFFFF", "accent": "#FFB000", "styles": ["classic", "cinema", "bottom"], "max_words": 3, "sat_boost": 1.15, "vignette": 0.3},
    "rage": {"text_color": "#FFFFFF", "accent": "#FF1E1E", "styles": ["burst", "classic", "sticker"], "max_words": 3, "sat_boost": 1.3, "vignette": 0.35},
    "scary": {"text_color": "#FFFFFF", "accent": "#B000FF", "styles": ["cinema", "bottom", "minimal"], "max_words": 3, "sat_boost": 0.9, "vignette": 0.5},
    "shock": {"text_color": "#FFE600", "accent": "#00E0FF", "styles": ["classic", "burst", "split"], "max_words": 3, "sat_boost": 1.25, "vignette": 0.2},
    "news": {"text_color": "#FFFFFF", "accent": "#FF6A00", "styles": ["cinema", "bottom", "split"], "max_words": 4, "sat_boost": 1.0, "vignette": 0.3},
    "tutorial": {"text_color": "#FFFFFF", "accent": "#22C55E", "styles": ["split", "polaroid", "classic"], "max_words": 4, "sat_boost": 1.05, "vignette": 0.1},
    "reaction": {"text_color": "#FFE600", "accent": "#FF2D87", "styles": ["polaroid", "split", "classic"], "max_words": 3, "sat_boost": 1.2, "vignette": 0.15},
}


# ---------------------------------------------------------------- measuring one thumbnail
def measure(img) -> Dict:
    """Numbers about one thumbnail (a BGR OpenCV image)."""
    import cv2
    import numpy as np
    img = cv2.resize(img, (320, 180))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cas.detectMultiScale(gray, 1.1, 4, minSize=(18, 18))
    face = max(faces, key=lambda f: f[2] * f[3]) if len(faces) else None
    # headline text: bright white or yellow blobs that sit next to dark / saturated pixels (that is how thumbnail text is made)
    white = (hsv[..., 1] < 45) & (hsv[..., 2] > 215)
    yellow = (hsv[..., 0] >= 18) & (hsv[..., 0] <= 36) & (hsv[..., 1] > 130) & (hsv[..., 2] > 180)
    mask = (white | yellow).astype("uint8") * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask)
    blobs = [i for i in range(1, n) if 0.004 * W * H <= stats[i, cv2.CC_STAT_AREA] <= 0.2 * W * H and stats[i, cv2.CC_STAT_WIDTH] > stats[i, cv2.CC_STAT_HEIGHT] * 0.8]
    tarea = sum(stats[i, cv2.CC_STAT_AREA] for i in blobs) / float(W * H)
    ty = (sum(cent[i][1] * stats[i, cv2.CC_STAT_AREA] for i in blobs) / max(1, sum(stats[i, cv2.CC_STAT_AREA] for i in blobs)) / H) if blobs else None
    ywhite = int(sum(white[lab == i].sum() for i in blobs)) if blobs else 0
    yyel = int(sum(yellow[lab == i].sum() for i in blobs)) if blobs else 0
    # main colours
    px = cv2.resize(img, (48, 27)).reshape(-1, 3).astype("float32")
    _, labels, centers = cv2.kmeans(px, 3, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0), 2, cv2.KMEANS_PP_CENTERS)
    cols = []
    for c in centers:
        b, g, r = [int(v) for v in c]
        h_, s_, v_ = cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2HSV)[0][0]
        cols.append((f"#{r:02X}{g:02X}{b:02X}", int(s_), int(v_)))
    sat = [c for c in cols if c[1] > 110 and c[2] > 110]
    corners = np.concatenate([gray[:H // 5, :W // 5].ravel(), gray[:H // 5, -W // 5:].ravel(), gray[-H // 5:, :W // 5].ravel(), gray[-H // 5:, -W // 5:].ravel()])
    centre = gray[H // 4: 3 * H // 4, W // 4: 3 * W // 4]
    return {"face": float(face[2] * face[3]) / (W * H) if face is not None else 0.0, "face_x": float(face[0] + face[2] / 2) / W if face is not None else None,
            "text": float(tarea), "text_y": float(ty) if ty is not None else None, "text_color": ("yellow" if yyel > ywhite else "white") if blobs else None,
            "accent": sat[0][0] if sat else None, "sat": float(hsv[..., 1].mean()), "contrast": float(gray.std()),
            "vignette": float(max(0.0, 1 - corners.mean() / max(1.0, centre.mean())))}


# ---------------------------------------------------------------- the study
def collect(per_query: int = 12) -> Dict[str, List[Dict]]:
    import cv2
    import numpy as np
    out: Dict[str, List[Dict]] = {}
    for typ, queries in QUERIES.items():
        rows: List[Dict] = []
        seen = set()
        for q in queries:
            try:
                info = json.loads(D._ytdlp("--flat-playlist", "-J", f"ytsearch{per_query}:{q}", capture=True, timeout=120))
            except Exception as e:
                print(f"[Playbook] search failed for '{q}': {str(e)[:80]}", flush=True)
                continue
            for e in info.get("entries") or []:
                vid = (e or {}).get("id")
                if not vid or vid in seen or int((e or {}).get("duration") or 0) < 20:
                    continue
                seen.add(vid)
                for name in ("maxresdefault", "sddefault", "mqdefault"):
                    try:
                        r = requests.get(f"https://i.ytimg.com/vi/{vid}/{name}.jpg", timeout=15)
                        if r.status_code == 200 and len(r.content) > 5000:
                            im = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                            if im is not None:
                                m = measure(im)
                                m["views"] = int((e or {}).get("view_count") or 0)
                                rows.append(m)
                                break
                    except Exception:
                        continue
        out[typ] = rows
        print(f"[Playbook] {typ}: measured {len(rows)} thumbnails", flush=True)
    return out


def _mode(vals: List) -> Optional[str]:
    vals = [v for v in vals if v]
    return Counter(vals).most_common(1)[0][0] if vals else None


def aggregate(rows: List[Dict], typ: str) -> Dict:
    """One recipe from the measurements of one kind of video (falls back to the starting recipe when there are too few)."""
    base = dict(DEFAULT[typ])
    if len(rows) < 8:
        return {**base, "type": typ, "source": "starting recipe", "n": len(rows)}
    pos_vals = ["top" if r["text_y"] < 0.38 else "bottom" if r["text_y"] > 0.62 else "middle" for r in rows if r["text_y"] is not None]
    pos = _mode(pos_vals) or "top"
    faces = [r for r in rows if r["face"] > 0.012]
    accents = Counter(r["accent"] for r in rows if r["accent"]).most_common(4)
    tcol = _mode([r["text_color"] for r in rows])
    styles = STYLE_BY_POS[pos]
    sat = statistics.median(r["sat"] for r in rows)
    out = {**base, "type": typ, "source": f"measured from {len(rows)} thumbnails", "n": len(rows), "text_pos": pos, "styles": styles,
           "face_share": round(len(faces) / len(rows), 2), "face_size": round(statistics.median([r["face"] for r in faces]), 3) if faces else 0.0,
           "face_side": _mode(["left" if r["face_x"] < 0.4 else "right" if r["face_x"] > 0.6 else "center" for r in faces if r["face_x"] is not None]),
           "text_share": round(statistics.median(r["text"] for r in rows), 3), "contrast": round(statistics.median(r["contrast"] for r in rows), 1),
           "sat_level": round(sat, 1), "sat_boost": round(max(0.9, min(1.5, 0.85 + sat / 160.0)), 2), "vignette": round(max(0.05, min(0.55, statistics.median(r["vignette"] for r in rows))), 2)}
    # colours are noisy to measure from a small sample (a white sky looks like white text): only a clear majority overrides the designed colours
    tc = [r["text_color"] for r in rows if r["text_color"]]
    if tc and sum(1 for c in tc if c == "yellow") / len(tc) >= 0.5:
        out["text_color"], out["text_confident"] = "#FFE600", True
    elif tc and sum(1 for c in tc if c == "white") / len(tc) >= 0.8:
        out["text_color"], out["text_confident"] = "#FFFFFF", True
    if accents:
        out["accents_seen"] = [a[0] for a in accents]           # what was seen, for information; the accent stays the designed one
    return out


def build(per_query: int = 12) -> Dict:
    data = collect(per_query)
    recipes = {t: aggregate(rows, t) for t, rows in data.items()}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"recipes": recipes}, indent=1), encoding="utf-8")
    return recipes


# ---------------------------------------------------------------- using it
_cache: Dict = {}


def recipes() -> Dict[str, Dict]:
    try:
        m = PATH.stat().st_mtime
        if _cache.get("m") != m:
            _cache.update(m=m, data=json.loads(PATH.read_text(encoding="utf-8"))["recipes"])
        merged = {}
        for t, r in _cache["data"].items():
            base = DEFAULT.get(t, {})
            merged[t] = {**r, "accent": base.get("accent", r.get("accent")), **({} if r.get("text_confident") else {"text_color": base.get("text_color", r.get("text_color"))})}
        return {**{t: {**DEFAULT[t], "type": t, "source": "starting recipe", "n": 0} for t in DEFAULT}, **merged}
    except Exception:
        return {t: {**DEFAULT[t], "type": t, "source": "starting recipe", "n": 0} for t in DEFAULT}


def recipe_for(content_type: Optional[str]) -> Optional[Dict]:
    return recipes().get(content_type or "")


def headline_for(recipe: Optional[Dict], headline: str) -> str:
    """Shorten a headline to the length that works for this kind of video (never cut in the middle of a word)."""
    if not recipe:
        return headline
    words, mx = headline.split(), int(recipe.get("max_words") or 4)
    return " ".join(words[:mx]) if len(words) > mx + 1 else headline         # one word over is fine; more is cut


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        r = build()
        print(json.dumps({t: {k: v for k, v in x.items() if k in ("source", "text_pos", "styles", "text_color", "accent", "face_share", "face_side", "sat_boost", "vignette")} for t, x in r.items()}, indent=1))
    else:
        print(json.dumps(recipes(), indent=1))
