"""Reaction Lab (beta): the scoring model and how it learns.

Every moment has a few numbers between 0 and 1 (its signals: loud, laugh, chat ...). The model is a small logistic regression:

    chance a moment is a good reaction = sigmoid( bias + sum( weight[signal] * value[signal] ) )

It starts from sensible weights ("prior"). Each time the member says "good reaction" or "not good" the lab keeps that judgment, and training
moves the weights toward what that member's judgments show. The weights are pulled back toward the prior (ridge toward the prior), so with
few judgments the model stays close to the starting weights and only drifts away as real evidence arrives. Plain numpy, no extra packages.
Nothing in this file touches the rest of the studio.
"""
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

SIGNALS = ["loud", "burst", "laugh", "hush", "chat", "hype", "smile", "jolt", "action", "words", "heat"]
LABEL = {
    "loud": "Loud moment", "burst": "Sudden jump in sound", "laugh": "Laughing sounds", "hush": "Quiet, then a shout", "chat": "Chat speeds up", "hype": "Laugh / hype emotes in chat",
    "smile": "Smile on camera", "jolt": "Jolt or lean-in on camera", "action": "Sudden change on screen", "words": "Reaction words said", "heat": "Most replayed by viewers",
}
HELP = {
    "loud": "How much louder than the rest of the stream.", "burst": "How fast the sound rose in the seconds before.", "laugh": "Rhythmic, laugh-like sound (a rough guess from the audio).",
    "hush": "Silence or low sound right before a shout.", "chat": "How much faster chat messages come in (needs chat to be readable for that video).",
    "hype": "Share of chat that is laughing or hype emotes.", "smile": "A smile found on the streamer's face camera (needs a face camera).",
    "jolt": "The face suddenly moves or grows (a jump or lean-in).", "action": "The picture changes suddenly (a crash, a kill, a jump scare).",
    "words": "Words like \"no way\", \"oh my god\", \"let's go\" (needs the 'listen to words' option).", "heat": "YouTube's most replayed curve (YouTube videos only).",
}
CATEGORIES = ["any", "funny", "rage", "fail", "scary", "shock", "epic"]
PRIOR = {"loud": 1.6, "burst": 1.2, "laugh": 1.4, "hush": 0.9, "chat": 2.2, "hype": 1.0, "smile": 1.0, "jolt": 0.7, "action": 0.6, "words": 1.2, "heat": 1.8}
PRIOR_BIAS = -3.0
LAMBDA = 3.0              # how strongly the weights are held near the prior (higher = needs more judgments to move)
MIN_EACH_CLASS = 5        # at least this many "good" and this many "not good" before the model trains
CATEGORY_MIN = 20         # a kind-of-reaction model needs this many judgments of its own, otherwise the general model is used
W_MIN, W_MAX = -1.0, 6.0


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def vector(feat: Dict[str, float]) -> np.ndarray:
    return np.array([float(feat.get(s) or 0.0) for s in SIGNALS], dtype=float)


def prior_model() -> Dict:
    return {"w": [PRIOR[s] for s in SIGNALS], "b": PRIOR_BIAS, "n": 0, "pos": 0, "trained": False, "acc": None, "base": None}


def score(feat: Dict[str, float], model: Optional[Dict] = None) -> int:
    """0 to 100: how likely this moment is a strong reaction, by the model (the starting weights when there is none)."""
    m = model or prior_model()
    return int(round(100 * float(sigmoid(vector(feat) @ np.array(m["w"]) + m["b"]))))


def reasons(feat: Dict[str, float], model: Optional[Dict] = None, top: int = 4) -> List[str]:
    """The signals that pushed the score up the most, in plain words."""
    m = model or prior_model()
    contrib = sorted(((float(vector(feat)[i] * m["w"][i]), s) for i, s in enumerate(SIGNALS)), reverse=True)
    return [LABEL[s] for c, s in contrib if c >= 0.35][:top]


def _fit(X: np.ndarray, y: np.ndarray, w0: np.ndarray, b0: float, steps: int = 700) -> Tuple[np.ndarray, float]:
    w, b = w0.copy(), float(b0)
    n = len(y)
    lr = 1.0 / (0.6 * n + 2 * LAMBDA + 1)          # a safe step for this size of problem (inputs are between 0 and 1)
    for _ in range(steps):
        p = sigmoid(X @ w + b)
        gw = X.T @ (p - y) + 2 * LAMBDA * (w - w0)
        gb = float((p - y).sum()) + 2 * 0.5 * (b - b0)
        w = np.clip(w - lr * gw, W_MIN, W_MAX)
        b -= lr * gb
    return w, b


def cv_accuracy(X: np.ndarray, y: np.ndarray, w0: np.ndarray, b0: float, folds: int = 5) -> Optional[Tuple[float, float]]:
    """(accuracy on moments the model has not seen, accuracy of always guessing the more common answer). None when there are too few judgments."""
    n = len(y)
    if n < 15 or min(int(y.sum()), int(n - y.sum())) < 4:
        return None
    rng = np.random.default_rng(7)
    fold = np.zeros(n, dtype=int)
    for c in (0, 1):
        ids = rng.permutation(np.where(y == c)[0])
        fold[ids] = np.arange(len(ids)) % folds
    hit = 0
    for f in range(folds):
        te, tr = fold == f, fold != f
        if te.sum() == 0 or tr.sum() < 6:
            continue
        w, b = _fit(X[tr], y[tr], w0, b0, steps=300)
        hit += int(((sigmoid(X[te] @ w + b) >= 0.5).astype(int) == y[te]).sum())
    base = max(float(y.mean()), 1 - float(y.mean()))
    return hit / n, base


def train(rows: Sequence[Dict[str, float]], ys: Sequence[int]) -> Optional[Dict]:
    """Learn from the member's judgments. Returns the new model, or None while there are not enough of both kinds yet."""
    y = np.array([1 if v else 0 for v in ys], dtype=float)
    pos = int(y.sum())
    if len(y) == 0 or pos < MIN_EACH_CLASS or len(y) - pos < MIN_EACH_CLASS:
        return None
    X = np.vstack([vector(r) for r in rows])
    w0 = np.array([PRIOR[s] for s in SIGNALS], dtype=float)
    w, b = _fit(X, y, w0, PRIOR_BIAS)
    cv = cv_accuracy(X, y, w0, PRIOR_BIAS)
    return {"w": [round(float(v), 3) for v in w], "b": round(float(b), 3), "n": int(len(y)), "pos": pos, "trained": True,
            "acc": round(cv[0], 3) if cv else None, "base": round(cv[1], 3) if cv else None}


def phase(n: int, trained: bool) -> Dict:
    """Where the learning stands, in words a member understands."""
    steps = [(10, "Just started", "Using the starting weights. Judge about 10 moments (some good, some not) and it starts to learn."),
             (30, "Learning", "Starting to lean toward your taste. About 30 judgments make it noticeably yours."),
             (100, "Personal", "It follows your taste. More judgments keep sharpening it."),
             (10 ** 9, "Well tuned", "Plenty of judgments. It changes slowly now.")]
    for lim, name, text in steps:
        if n < lim:
            return {"name": name, "text": text, "next": lim if lim < 10 ** 9 else None}
    return {"name": "Well tuned", "text": steps[-1][2], "next": None}


def describe(model: Optional[Dict], category: str = "any") -> Dict:
    """What a member sees about one model: how many judgments, how accurate, and what it now cares about."""
    m = model or prior_model()
    weights = [{"signal": s, "label": LABEL[s], "prior": PRIOR[s], "now": m["w"][i], "change": round(m["w"][i] - PRIOR[s], 2)} for i, s in enumerate(SIGNALS)]
    top = max(m["w"]) or 1.0
    for w in weights:
        w["share"] = int(round(100 * max(0.0, w["now"]) / max(top, 1e-6)))
    ph = phase(int(m.get("n") or 0), bool(m.get("trained")))
    return {"category": category, "n": int(m.get("n") or 0), "pos": int(m.get("pos") or 0), "trained": bool(m.get("trained")), "acc": m.get("acc"), "base": m.get("base"),
            "phase": ph, "weights": weights, "bias": m["b"]}
