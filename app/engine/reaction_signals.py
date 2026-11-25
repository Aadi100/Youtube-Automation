"""Reaction Lab (beta): measuring reactions in a recording. No AI service and no tokens: sound, chat, the camera picture and a local speech model.

  audio_signals   per second: how loud, how fast it rose, laugh-like rhythm, quiet-then-shout
  chat_signals    per second: how fast chat moves and how much of it is laughing / hype  (when the platform lets us read the chat replay)
  picture_signals a smile, a jolt of the face and sudden screen changes (OpenCV, only on the short previews of the best moments)
  word_signals    reaction words said ("no way", "oh my god")  (faster-whisper, only on those previews, switched on by the member)

These are rough measures, not mind-reading: they give the model something to weigh and learn from the member's own judgments.
Nothing in this file touches the rest of the studio.
"""
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import FFMPEG_BIN

SR = 8000
CHAT_LAG = 4                                   # chat reacts a few seconds after the moment
HYPE_RE = re.compile(r"\b(lul|lulw|kekw|omegalul|lmao|lmfao|lol|haha+|pog+|pogchamp|poggers|w|ez|clip it|clip that|no way|nooo+|wtf|omg|holy)\b|[😂🤣😭💀🔥😱]", re.I)
REACT_WORDS = re.compile(r"\b(no way|oh my god|omg|oh my gosh|what the|what was that|are you kidding|let'?s go|let'?s gooo*|holy|insane|crazy|bro+|dude|dead|i'?m dying|wtf|oh no|no no no+|what the hell|jesus|yes+)\b", re.I)


def _clip01(x):
    return np.clip(x, 0.0, 1.0)


def _z(x: np.ndarray) -> np.ndarray:
    med = np.median(x)
    spread = np.median(np.abs(x - med)) * 1.4826 or x.std() or 1.0
    return (x - med) / spread


def _smooth(a: np.ndarray, k: int) -> np.ndarray:
    return np.convolve(a, np.ones(k) / k, mode="same")


# ---------------------------------------------------------------- sound
def read_samples(media: Path) -> np.ndarray:
    p = subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, timeout=900)
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def audio_signals(x: np.ndarray) -> Dict[str, np.ndarray]:
    """Per-second arrays (each 0..1 except db): db, loud, burst, laugh, hush. Empty arrays when there is less than a minute of sound."""
    n = len(x) // SR
    if n < 60:
        return {k: np.zeros(0) for k in ("db", "loud", "burst", "laugh", "hush")}
    sec = x[:n * SR].reshape(n, SR)
    db = 20 * np.log10(np.sqrt((sec ** 2).mean(axis=1)) + 1e-5)
    loud = _clip01(_z(_smooth(db, 3)) / 6.0)
    # how much louder than the 6 to 25 seconds before (a jump or a shout)
    rise = np.zeros(n)
    for i in range(26, n):
        rise[i] = db[i] - np.median(db[i - 25:i - 5])
    burst = _clip01(rise / 20.0)
    # quiet right before, then loud: "silence, then a shout"
    hush = np.zeros(n)
    for i in range(30, n):
        pre = db[i - 6:i - 1].mean()
        quiet = np.median(db[i - 60:i]) - pre if i >= 60 else np.median(db[:i]) - pre
        hush[i] = float(_clip01(quiet / 8.0) * _clip01((db[i] - pre - 8) / 14.0))
    # laugh-like rhythm: the loudness of the voice band pulses 3 to 8 times a second
    laugh = np.zeros(n)
    try:
        from scipy.signal import butter, sosfilt
        band = sosfilt(butter(4, [500 / (SR / 2), 3500 / (SR / 2)], btype="band", output="sos"), x[:n * SR])
        env = np.abs(band).reshape(-1, 80).mean(axis=1)                 # 100 values a second
        win = 300
        for i in range(1, n - 2):
            seg = env[(i - 1) * 100:(i - 1) * 100 + win]
            if len(seg) < win:
                break
            f = np.abs(np.fft.rfft(seg - seg.mean())) ** 2
            fr = np.fft.rfftfreq(win, 0.01)
            total = f[(fr >= 0.5) & (fr <= 20)].sum() + 1e-9
            laugh[i] = float(f[(fr >= 3) & (fr <= 8)].sum() / total)
        lvl = _clip01((db - np.median(db)) / 8.0)                         # only counts when it is clearly above the usual level
        laugh = _clip01((laugh - 0.35) / 0.4) * lvl
    except Exception:
        laugh = np.zeros(n)
    return {"db": db, "loud": loud, "burst": burst, "laugh": _smooth(laugh, 3), "hush": hush}


# ---------------------------------------------------------------- chat
def parse_chat(path: Path) -> List[Tuple[float, float]]:
    """[(second, weight)] from a YouTube live-chat replay (json lines) or a Twitch chat replay (json). A hype / laugh message weighs more. [] when unreadable."""
    out: List[Tuple[float, float]] = []

    def add(t, text):
        if t is None or t < 0:
            return
        out.append((float(t), 2.5 if HYPE_RE.search(text or "") else 1.0))

    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    if "replayChatItemAction" in txt[:20000]:             # YouTube: one json object per line
        for line in txt.splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            r = j.get("replayChatItemAction") or {}
            off = r.get("videoOffsetTimeMsec")
            for a in r.get("actions") or []:
                it = ((a.get("addChatItemAction") or {}).get("item") or {}).get("liveChatTextMessageRenderer")
                if it:
                    text = "".join((run.get("text") or run.get("emoji", {}).get("emojiId", "")) for run in (it.get("message") or {}).get("runs") or [])
                    add(int(off) / 1000.0 if off is not None else None, text)
        return out
    try:
        j = json.loads(txt)
    except ValueError:
        return []
    items = j.get("comments") if isinstance(j, dict) else j
    for c in items or []:
        if isinstance(c, dict):
            add(c.get("content_offset_seconds"), ((c.get("message") or {}).get("body")) or "")
    return out


def chat_signals(events: List[Tuple[float, float]], n: int, offset: float = 0.0) -> Optional[Dict[str, np.ndarray]]:
    """Per-second arrays for a window that starts `offset` seconds into the video: chat (0..1), hype (0..1). None when there are too few messages to tell."""
    if len(events) < 40:
        return None
    rate, hype = np.zeros(n), np.zeros(n)
    for t, w in events:
        i = int(t - offset - CHAT_LAG)
        if 0 <= i < n:
            rate[i] += 1.0
            hype[i] += 1.0 if w > 1.0 else 0.0
    sm = _smooth(rate, 8)
    share = _smooth(hype, 8) / (sm + 0.5)
    return {"chat": _clip01(_z(sm) / 6.0), "hype": _clip01(share / 0.6)}


# ---------------------------------------------------------------- picture (OpenCV, on a short preview)
_cascades: Dict[str, object] = {}


def _cascade(name: str):
    import cv2
    if name not in _cascades:
        _cascades[name] = cv2.CascadeClassifier(cv2.data.haarcascades + name)
    return _cascades[name]


def picture_signals(video: Path, fps: float = 3.0, faces_on: bool = True) -> Dict:
    """What the camera picture shows in a short clip: {face: share of frames with a face, smile, jolt, action} (all 0..1). Face numbers are None without a face camera
    (or when faces_on is False, which skips the face search and only measures sudden screen changes)."""
    import cv2
    if faces_on:                                   # the better way: a face finder + an expression reader (app/engine/face_signals.py)
        try:
            from app.engine import face_signals
            fs = face_signals.clip_signals(video, fps)
            if fs is not None:
                return {"face": fs["face"], "smile": fs["smile"], "jolt": fs["jolt"], "action": fs["action"]}
        except Exception:
            pass                                   # anything unexpected: the old method below
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return {"face": 0.0, "smile": None, "jolt": None, "action": 0.0}
    src = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(src / fps)))
    face_det, smile_det = _cascade("haarcascade_frontalface_default.xml"), _cascade("haarcascade_smile.xml")
    prev_gray, prev_face = None, None
    frames = faces = smiles = 0
    jolt = 0.0
    action = 0.0
    k = -1
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        k += 1
        if k % step:
            continue
        frames += 1
        small = cv2.resize(fr, (320, int(fr.shape[0] * 320 / fr.shape[1]))) if fr.shape[1] > 320 else fr
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None and prev_gray.shape == gray.shape:
            action = max(action, float(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)).mean()) / 40.0)
        prev_gray = gray
        found = face_det.detectMultiScale(gray, 1.2, 5, minSize=(28, 28)) if faces_on else []
        if len(found):
            x, y, w, h = max(found, key=lambda f: f[2] * f[3])
            faces += 1
            sm = smile_det.detectMultiScale(gray[y + h // 2:y + h, x:x + w], 1.7, 22, minSize=(max(12, w // 4), max(8, h // 8)))
            smiles += 1 if len(sm) else 0
            cx, cy, size = x + w / 2, y + h / 2, float(w)
            if prev_face is not None:
                px, py, ps = prev_face
                jolt = max(jolt, abs(size - ps) / ps + float(np.hypot(cx - px, cy - py)) / ps * 0.5)
            prev_face = (cx, cy, size)
        else:
            prev_face = None
    cap.release()
    face_frac = faces / frames if frames else 0.0
    if face_frac < 0.2 or faces < 4:                      # no face camera in this clip
        return {"face": face_frac, "smile": None, "jolt": None, "action": float(_clip01(action))}
    return {"face": face_frac, "smile": float(_clip01(smiles / faces / 0.5)), "jolt": float(_clip01(jolt / 0.6)), "action": float(_clip01(action))}


# ---------------------------------------------------------------- words
_whisper = None


def word_signals(video: Path) -> Dict:
    """{words: 0..1, text: what was said} with a local speech model (faster-whisper). words is None when the model is not available."""
    global _whisper
    try:
        from faster_whisper import WhisperModel
        if _whisper is None:
            _whisper = WhisperModel("base", device="cpu", compute_type="int8")
        segs, _ = _whisper.transcribe(str(video), vad_filter=False)
        text = " ".join(s.text.strip() for s in segs).strip()
    except Exception:
        return {"words": None, "text": ""}
    hits = len(REACT_WORDS.findall(text))
    return {"words": float(_clip01(hits / 3.0)), "text": text[:300]}


# ---------------------------------------------------------------- putting a moment's numbers together
def window_features(sig: Dict[str, np.ndarray], chat: Optional[Dict[str, np.ndarray]], heat: Optional[np.ndarray], peak: int, half: int = 4) -> Dict[str, float]:
    """The sound / chat / replay numbers of the moment around second `peak`."""
    a, b = max(0, peak - half), peak + half + 1

    def top(arr):
        return float(arr[a:b].max()) if arr is not None and len(arr) > a else 0.0
    f = {"loud": top(sig.get("loud")), "burst": top(sig.get("burst")), "laugh": top(sig.get("laugh")), "hush": top(sig.get("hush"))}
    if chat:
        f["chat"], f["hype"] = top(chat["chat"]), top(chat["hype"])
    if heat is not None and len(heat) > a:
        f["heat"] = float(heat[a:b].mean())
    return f
