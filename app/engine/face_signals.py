"""Faces and facial expressions, light enough for a small server CPU.

Two small neural networks that OpenCV runs by itself (no PyTorch, no GPU, no extra Python package):
  * YuNet            finds faces and 5 landmarks (eyes, nose, mouth corners).            MIT licence, 0.2 MB
  * MobileFaceNet    reads the expression of an aligned face: 7 classes                  Apache-2.0 (OpenCV Zoo), 4.8 MB
                     (angry, disgust, fearful, happy, neutral, sad, surprised)
Both come from the OpenCV Zoo. They are downloaded the first time they are needed, checked against a fixed checksum and kept in
state/models/. If they cannot be downloaded, every caller falls back to what it did before (the old Haar face finder), so nothing breaks.

Why not YOLO: Ultralytics YOLO is AGPL-3.0 (a hosted service would have to publish its source) and needs PyTorch (about 1 GB).

What it is and is not: expressions are a clue, not a fact. Streamers wear headphones, sit in bad light and the face is small, so a
single frame is often wrong. Callers use the share of frames over a clip, together with the sound, never one frame alone.
"""
import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from app.config import STATE_DIR

MODEL_DIR = STATE_DIR / "models"
BASE = "https://github.com/opencv/opencv_zoo/raw/main/models/"
MODELS = {
    "yunet": ("face_detection_yunet/face_detection_yunet_2023mar.onnx", "face_detection_yunet_2023mar.onnx",
              "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "fer": ("facial_expression_recognition/facial_expression_recognition_mobilefacenet_2022july.onnx", "facial_expression_recognition_mobilefacenet_2022july.onnx",
            "4f61307602fc089ce20488a31d4e4614e3c9753a7d6c41578c854858b183e1a9"),
}
EXPRESSIONS = ["angry", "disgust", "fearful", "happy", "neutral", "sad", "surprised"]
# where the eyes, nose and mouth corners sit in the 112x112 aligned face the expression model was trained on
_STD = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)
MIN_FACE_PX = 30                 # a face narrower than this (in the original picture) is found but its expression is not read

_lock = threading.Lock()
_state: Dict = {"det": None, "fer": None, "failed_at": 0.0}


def _verify(path: Path, sha: str) -> bool:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest() == sha
    except OSError:
        return False


def _fetch(key: str) -> Optional[Path]:
    rel, name, sha = MODELS[key]
    p = MODEL_DIR / name
    if p.is_file() and _verify(p, sha):
        return p
    try:
        import requests
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        r = requests.get(BASE + rel, timeout=60)
        r.raise_for_status()
        tmp = p.with_suffix(".part")
        tmp.write_bytes(r.content)
        if not _verify(tmp, sha):
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(p)
        return p
    except Exception:
        return None


def _load() -> bool:
    """True when the face finder is ready (the expression model is loaded when it can be, and is optional)."""
    import cv2
    with _lock:
        if _state["det"] is not None:
            return True
        if time.time() - _state["failed_at"] < 600:          # a failed download is not retried for 10 minutes
            return False
        yp = _fetch("yunet")
        if not yp:
            _state["failed_at"] = time.time()
            return False
        try:
            _state["det"] = cv2.FaceDetectorYN.create(str(yp), "", (320, 320), 0.7, 0.3, 200)
        except Exception:
            _state["failed_at"] = time.time()
            return False
        fp = _fetch("fer")
        if fp:
            try:
                _state["fer"] = cv2.dnn.readNet(str(fp))
            except Exception:
                _state["fer"] = None
        return True


def available() -> bool:
    return _load()


def expressions_available() -> bool:
    return _load() and _state["fer"] is not None


def detect(frame, max_side: int = 960, min_score: float = 0.7) -> Optional[List[Dict]]:
    """Faces in a BGR picture, biggest first: [{x, y, w, h, score, lm}] in the picture's own pixels. None when the finder is not available
    (the caller then uses its old method); [] when it works and there is no face."""
    if not _load():
        return None
    h0, w0 = frame.shape[:2]
    sc = min(1.0, max_side / float(max(h0, w0)))
    small = frame if sc == 1.0 else __import__("cv2").resize(frame, (max(32, int(w0 * sc)), max(32, int(h0 * sc))))
    h, w = small.shape[:2]
    with _lock:
        det = _state["det"]
        det.setInputSize((w, h))
        _n, res = det.detect(small)
    out: List[Dict] = []
    for r in (res if res is not None else []):
        if float(r[14]) < min_score:
            continue
        x, y, bw, bh = (float(v) / sc for v in r[:4])
        lm = (np.array(r[4:14], dtype=np.float32).reshape(5, 2) / sc)
        out.append({"x": max(0.0, x), "y": max(0.0, y), "w": bw, "h": bh, "score": float(r[14]), "lm": lm})
    out.sort(key=lambda f: -(f["w"] * f["h"]))
    return out


def expression(frame, face: Dict) -> Optional[Dict[str, float]]:
    """{"happy": 0.8, ...} for one face from detect(), or None (no model, or the face is too small to read)."""
    import cv2
    if not expressions_available() or face["w"] < MIN_FACE_PX:
        return None
    M, _ = cv2.estimateAffinePartial2D(face["lm"].astype(np.float32), _STD, method=cv2.LMEDS)
    if M is None:
        return None
    crop = cv2.warpAffine(frame, M, (112, 112))
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    blob = cv2.dnn.blobFromImage((rgb - 0.5) / 0.5)
    with _lock:
        net = _state["fer"]
        net.setInput(blob, "data")
        logits = net.forward(["label"])[0][0]
    e = np.exp(logits - logits.max())
    p = e / e.sum()
    return {k: float(v) for k, v in zip(EXPRESSIONS, p)}


def clip_signals(video: Path, fps: float = 3.0, max_frames: int = 160) -> Optional[Dict]:
    """What the faces in a short clip show: {face, smile, surprise, jolt, action, read}.
      face      share of frames with a face (0..1)
      smile     share of face frames where the expression is 'happy' (0..1, scaled so half the frames smiling is 1.0)
      surprise  share where it is 'surprised' or 'fearful' (scaled so 40% of the frames is 1.0)
      jolt      how much the face jumps in size or position between frames (a lean-in or a recoil), 0..1
      action    the biggest sudden change of the whole picture, 0..1
      read      how many frames had a face big enough for the expression to be read
    None when the face finder is not available (the caller uses its old method)."""
    import cv2
    if not _load():
        return None
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return {"face": 0.0, "smile": None, "surprise": None, "jolt": None, "action": 0.0, "read": 0}
    src = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(src / fps)))
    frames = faces = read = smiles = surprised = 0
    jolt, action = 0.0, 0.0
    prev_gray, prev_face = None, None
    k = -1
    while frames < max_frames:
        ok, fr = cap.read()
        if not ok:
            break
        k += 1
        if k % step:
            continue
        frames += 1
        small = cv2.resize(fr, (160, max(2, int(fr.shape[0] * 160 / fr.shape[1])))) if fr.shape[1] > 160 else fr
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.int16)
        if prev_gray is not None and prev_gray.shape == gray.shape:
            action = max(action, float(np.abs(gray - prev_gray).mean()) / 40.0)
        prev_gray = gray
        found = detect(fr)
        if not found:
            prev_face = None
            continue
        faces += 1
        f = found[0]
        if prev_face is not None:                          # follow the SAME person (two people on camera: the biggest face flips between them)
            px, py, ps = prev_face
            near = min(found, key=lambda g: float(np.hypot(g["x"] + g["w"] / 2 - px, g["y"] + g["h"] / 2 - py)))
            if float(np.hypot(near["x"] + near["w"] / 2 - px, near["y"] + near["h"] / 2 - py)) < 1.5 * ps:
                f = near
        cx, cy, size = f["x"] + f["w"] / 2, f["y"] + f["h"] / 2, float(f["w"])
        if prev_face is not None:
            px, py, ps = prev_face
            jolt = max(jolt, abs(size - ps) / ps + float(np.hypot(cx - px, cy - py)) / ps * 0.5)
        prev_face = (cx, cy, size)
        reads = [ex for ex in (expression(fr, g) for g in found[:2]) if ex]     # anyone on camera reacting counts
        if reads:
            read += 1
            smiles += 1 if any(max(e, key=e.get) == "happy" and e["happy"] > 0.5 for e in reads) else 0
            surprised += 1 if any(max(e, key=e.get) in ("surprised", "fearful") and max(e.values()) > 0.45 for e in reads) else 0
    cap.release()
    face_frac = faces / frames if frames else 0.0
    clip01 = lambda v: float(max(0.0, min(1.0, v)))
    if face_frac < 0.2 or faces < 4:                              # no face camera in this clip
        return {"face": face_frac, "smile": None, "surprise": None, "jolt": None, "action": clip01(action), "read": read}
    sm = clip01(smiles / read / 0.5) if read >= 3 else None
    su = clip01(surprised / read / 0.4) if read >= 3 else None
    j = clip01(jolt / 0.6)
    return {"face": face_frac, "smile": sm, "surprise": su, "jolt": max(j, su or 0.0) if su is not None else j, "action": clip01(action), "read": read}


def find_face_box(video: Path, duration: float, samples: int = 8) -> Optional[Dict]:
    """Where the streamer's face is, as fractions of the picture {x, y, w, h}: the middle of the boxes from several frames. None when the
    finder is not available or there is no steady face (the caller then uses its old method)."""
    import cv2
    if not _load():
        return None
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return None
    W, H = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0, cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0
    boxes = []
    try:
        for i in range(samples):
            t = max(0.0, duration * (0.08 + 0.84 * i / max(1, samples - 1)))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, fr = cap.read()
            if not ok:
                continue
            found = detect(fr)
            if found:
                grp = [g for g in found if g["w"] >= 0.5 * found[0]["w"]]       # everybody in the camera, not one of them
                x0, y0 = min(g["x"] for g in grp), min(g["y"] for g in grp)
                x1, y1 = max(g["x"] + g["w"] for g in grp), max(g["y"] + g["h"] for g in grp)
                boxes.append((x0 / fr.shape[1], y0 / fr.shape[0], (x1 - x0) / fr.shape[1], (y1 - y0) / fr.shape[0]))
    finally:
        cap.release()
    if len(boxes) < max(3, samples // 3) or not W or not H:
        return None
    b = np.array(boxes)
    ctr = np.stack([b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], axis=1)
    mid = np.median(ctr, axis=0)
    keep = b[(np.abs(ctr[:, 0] - mid[0]) < 0.12) & (np.abs(ctr[:, 1] - mid[1]) < 0.12)]     # a game character's face in one frame is not the camera
    if len(keep) < max(3, samples // 3):
        return None
    if float(keep[:, 0].std()) > 0.08 or float(keep[:, 1].std()) > 0.08:      # the face moves all over the picture: not a face camera
        return None
    m = np.median(keep, axis=0)
    return {"x": float(m[0]), "y": float(m[1]), "w": float(m[2]), "h": float(m[3])}


def webcam_crop(box: Dict, width: int, height: int, aspect: float = 1.5) -> Optional[str]:
    """'x:y:w:h' (pixels) of a rectangle around the face camera, with the proportions the split layout shows on top (3:2), or None when the face
    fills the picture (no separate camera overlay: nothing to cut out)."""
    if not box or not width or not height:
        return None
    fw, fh = box["w"] * width, box["h"] * height
    if fw * fh > 0.18 * width * height:                       # a big face: the whole picture IS the camera
        return None
    cw = fw * 2.6
    ch = cw / aspect
    if ch < fh * 1.8:
        ch = fh * 1.8
        cw = ch * aspect
    cw, ch = min(cw, width), min(ch, height)
    if cw / ch > aspect:
        cw = ch * aspect
    else:
        ch = cw / aspect
    cx, cy = (box["x"] + box["w"] / 2) * width, (box["y"] + box["h"] / 2) * height
    x = int(max(0, min(width - cw, cx - cw / 2)))
    y = int(max(0, min(height - ch, cy - ch * 0.46)))
    return f"{x}:{y}:{int(cw) // 2 * 2}:{int(ch) // 2 * 2}"
