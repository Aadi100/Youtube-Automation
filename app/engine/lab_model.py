"""Learning Lab (beta): the small models behind it. Plain numpy, no AI service, no tokens, nothing outside the lab calls this unless the owner
switched a part on.

  titles    A title is described by a few plain features (a question, a number, short / long, talks about "he / she / they", has a turn, ...).
            A ridge regression learns which features go with MORE VIEWS PER DAY on the owner's own videos. It is pulled hard toward "no effect"
            (the shrinking), so with few videos it stays close to zero and only drifts away as real evidence arrives.
  clipping  A clip is described by where it came from and how it looks (found by words / replays / sound, source, length, score, views, hook).
            A logistic regression learns which of these go with clips the owner APPROVES (published) rather than declines.

The result is only ever a small nudge (a few points on a score of 100), never a replacement for the normal scoring, and it needs a minimum
number of examples before it speaks at all. This is "learning from results", not a trained language model: there is not enough data for that.
"""
import re
from typing import Dict, List, Optional

import numpy as np

MIN_TITLES = 12           # videos with view counts needed before the title model is used
MIN_CLIPS = 20            # approved + declined videos needed before the clipping model is used
MIN_PER_CLASS = 6         # ...and at least this many of each kind

# ------------------------------------------------------------------------------------------------ titles
TITLE_FEATURES = [
    ("question", "It is a question"),
    ("number", "It has a number"),
    ("short", "It is short (under 35 characters)"),
    ("long", "It is long (over 58 characters)"),
    ("third", "It talks about 'he / she / they'"),
    ("turn", "It has a turn (but, until, then, instead, suddenly)"),
    ("caps", "It has an ALL-CAPS word"),
    ("punct", "It has a colon or a dash"),
    ("words", "More words than usual"),
]
_THIRD = re.compile(r"\b(he|she|they|his|her|their|him|them)\b", re.I)
_TURN = re.compile(r"\b(but|until|then|instead|after|before|when|suddenly|wait)\b", re.I)


def clean_title(t: str) -> str:
    return " ".join(str(t or "").replace("#Shorts", "").replace("#shorts", "").split()).strip(' "\'')


def title_features(title: str) -> np.ndarray:
    t = clean_title(title)
    ws = re.findall(r"[A-Za-z0-9']+", t)
    f = {
        "question": "?" in t,
        "number": bool(re.search(r"\d", t)),
        "short": len(t) < 35,
        "long": len(t) > 58,
        "third": bool(_THIRD.search(t)),
        "turn": bool(_TURN.search(t)),
        "caps": any(len(w) > 2 and w.isupper() and not w.isdigit() for w in ws),
        "punct": (":" in t) or (" - " in t) or ("—" in t) or ("–" in t),
        "words": max(-1.0, min(1.0, (len(ws) - 8) / 4.0)),
    }
    return np.array([float(f[k]) for k, _ in TITLE_FEATURES], dtype=np.float64)


# ------------------------------------------------------------------------------------------------ clipping
CLIP_FEATURES = [
    ("origin_heat", "Found by YouTube's 'most replayed' curve"),
    ("origin_words", "Found by reading the captions"),
    ("origin_sound", "Found only by its loud, exciting sound"),
    ("sound_agree", "The sound agreed with the captions / replays"),
    ("src_twitch", "A Twitch clip"),
    ("src_live", "Cut from a live stream"),
    ("len_short", "Short (under 25 seconds)"),
    ("len_long", "Long (over 45 seconds)"),
    ("score_hi", "A high score (85 or more)"),
    ("views", "The source video has many views"),
    ("hook", "It has a hook line"),
]


def clip_features(lab: Dict) -> np.ndarray:
    """lab: {origin, sound_agree, src, len, score, views, hook}. Missing keys mean 'not known' and count as 0."""
    lab = lab or {}
    o, s = str(lab.get("origin") or ""), str(lab.get("src") or "")
    length, score, views = float(lab.get("len") or 0), float(lab.get("score") or 0), float(lab.get("views") or 0)
    f = {
        "origin_heat": o == "heat", "origin_words": o == "words", "origin_sound": o == "sound",
        "sound_agree": bool(lab.get("sound_agree")),
        "src_twitch": s == "twitch", "src_live": s == "live",
        "len_short": 0 < length < 25, "len_long": length > 45,
        "score_hi": score >= 85,
        "views": min(1.0, np.log10(views + 1) / 6.0),
        "hook": bool(lab.get("hook")),
    }
    return np.array([float(f[k]) for k, _ in CLIP_FEATURES], dtype=np.float64)


def lab_from_clip(clip: Dict) -> Dict:
    """The lab features of a stored clip: what was recorded when it was found (clip['lab']), with the older plain fields as the fallback."""
    lab = dict(clip.get("lab") or {})
    lab.setdefault("src", clip.get("source") or "")
    lab.setdefault("views", clip.get("views") or 0)
    lab.setdefault("len", clip.get("duration") or 0)
    lab.setdefault("score", clip.get("score") or 0)
    lab.setdefault("hook", bool(clip.get("hook")))
    return lab


# ------------------------------------------------------------------------------------------------ the fits
def fit_ridge(X: np.ndarray, y: np.ndarray, ids: List[str], lam: float = 4.0) -> Dict:
    """Ridge regression of the standardised outcome on the centred features: w = (X'X + lam I)^-1 X'y."""
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    mu = X.mean(axis=0)
    sd = float(y.std()) or 1.0
    Xc, yz = X - mu, (y - y.mean()) / sd
    w = np.linalg.solve(Xc.T @ Xc + lam * np.eye(X.shape[1]), Xc.T @ yz)
    return {"kind": "ridge", "ids": ids, "w": [round(float(v), 5) for v in w], "mu": [round(float(v), 5) for v in mu], "n": int(len(y))}


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logistic(X: np.ndarray, y: np.ndarray, ids: List[str], lam: float = 1.5, iters: int = 30) -> Dict:
    """L2-regularised logistic regression (Newton steps) on the centred features."""
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    mu = X.mean(axis=0)
    Xc = X - mu
    w, b = np.zeros(X.shape[1]), float(np.log((y.mean() + 1e-3) / (1 - y.mean() + 1e-3)))
    for _ in range(iters):
        p = _sigmoid(Xc @ w + b)
        W = p * (1 - p) + 1e-6
        grad = Xc.T @ (y - p) - lam * w
        H = Xc.T @ (Xc * W[:, None]) + lam * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        w += step
        b += float((y - p).sum() / W.sum())
        if float(np.abs(step).max()) < 1e-6:
            break
    return {"kind": "logistic", "ids": ids, "w": [round(float(v), 5) for v in w], "mu": [round(float(v), 5) for v in mu], "b": round(b, 5),
            "n": int(len(y)), "pos": int(y.sum()), "neg": int(len(y) - y.sum())}


def _score(model: Dict, f: np.ndarray) -> float:
    return float((f - np.array(model["mu"])) @ np.array(model["w"]))


# ------------------------------------------------------------------------------------------------ what the models do to a score
def title_bonus(model: Optional[Dict], title: str, cap: float = 12.0) -> float:
    """Points added to a title's score (out of 100): at most +/-12, scaled by how much data there is behind it."""
    if not model or model.get("kind") != "ridge" or model.get("n", 0) < MIN_TITLES:
        return 0.0
    conf = model["n"] / (model["n"] + 30.0)
    return round(max(-cap, min(cap, 8.0 * _score(model, title_features(title)))) * conf, 1)


def clip_bonus(model: Optional[Dict], lab: Dict, cap: float = 10.0) -> float:
    """Points added to a clip window's score (out of 100): at most +/-10, scaled by how much data there is behind it."""
    if not model or model.get("kind") != "logistic" or model.get("n", 0) < MIN_CLIPS:
        return 0.0
    conf = model["n"] / (model["n"] + 40.0)
    return round(max(-cap, min(cap, 6.0 * _score(model, clip_features(lab)))) * conf, 1)


def explain(model: Optional[Dict], features: List) -> List[Dict]:
    """The learned weights in plain words, strongest first: [{label, direction (+1 / -1), strength ('strong' | 'medium' | 'slight')}]."""
    if not model:
        return []
    labels = dict(features)
    out = []
    for fid, w in zip(model["ids"], model["w"]):
        a = abs(w)
        if a < 0.05:
            continue
        hi, mid = (0.4, 0.2) if model.get("kind") == "ridge" else (1.0, 0.5)      # logistic weights are in log-odds: larger numbers mean the same thing
        out.append({"id": fid, "label": labels.get(fid, fid), "direction": 1 if w > 0 else -1, "weight": w,
                    "strength": "strong" if a >= hi else "medium" if a >= mid else "slight"})
    out.sort(key=lambda r: -abs(r["weight"]))
    return out
