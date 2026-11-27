"""The video editor's engine: look at a video, cut it, lay it out for a screen shape and render it with FFmpeg.

Everything here is plain functions on files (no database, no web). The studio's editor service calls them.

A *spec* describes the result:
    segments  [[start, end], ...]   the parts of the source to KEEP, in order (seconds)
    aspect    "9:16" | "16:9" | "4:5"
    fit       "crop" (fill the screen, centred on `focus`) | "blur" (whole picture over a blurred copy) | "whole" (black bars)
              | "split" (face camera on top, gameplay below; 9:16 only)
    focus     {"x": 0..1, "y": 0..1}                 where crop keeps the centre (a face)
    cam       {"x", "y", "w", "h"} 0..1               the camera area for split
    captions  true / false                            word-by-word captions from the speech
    texts     [{"text", "t0", "t1", "x", "y", "size", "color"}]   text on the picture; times are SOURCE seconds
"""
import json
import re
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from app.config import FFMPEG_BIN, FFPROBE_BIN, SUBTITLE_FONT_SIZE, TEMP_DIR

ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "4:5": (1080, 1350)}
FITS = ("crop", "blur", "whole", "split")
MAX_OUTPUT_SECONDS = 1800          # a finished edit can be up to 30 minutes
MIN_PIECE = 0.3                    # a kept piece shorter than this is not worth keeping
FILLER = re.compile(r"^(um+|uh+|uhm+|umm+|erm+|er|ah+|hmm+|mm+)[,.!?]*$")


# ---------------------------------------------------------------- looking at a video
def probe(path: Path) -> Dict:
    """duration, width, height, fps, has_audio. Raises ValueError when the file is not a video."""
    try:
        data = json.loads(subprocess.check_output([FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60))
    except Exception:
        raise ValueError("That file could not be read as a video.")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        raise ValueError("That file has no picture.")
    dur = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    if dur <= 0:
        raise ValueError("That video has no length.")
    num, _, den = str(v.get("avg_frame_rate") or "30/1").partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    return {"duration": round(dur, 3), "width": int(v.get("width") or 0), "height": int(v.get("height") or 0), "fps": round(fps or 30.0, 2),
            "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}


def filmstrip(path: Path, out: Path, duration: float, count: int = 16, height: int = 72) -> Path:
    """One wide picture made of `count` small frames in a row: the timeline background."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vf",
                    f"fps={count}/{max(duration, 1):.3f},scale=-2:{height},tile={count}x1:padding=0:margin=0", "-frames:v", "1", "-q:v", "6", str(out)],
                   check=True, timeout=300)
    return out


# ---------------------------------------------------------------- cutting
def normalize(segs: List[List[float]], duration: float) -> List[List[float]]:
    """Sort, clip to the video, merge overlaps and drop pieces that are too short."""
    clean = sorted([max(0.0, float(a)), min(float(duration), float(b))] for a, b in segs if b is not None and a is not None)
    out: List[List[float]] = []
    for a, b in clean:
        if b - a <= 0:
            continue
        if out and a <= out[-1][1] + 0.02:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 3), round(b, 3)] for a, b in out if b - a >= MIN_PIECE]


def subtract(segs: List[List[float]], cuts: List[List[float]]) -> List[List[float]]:
    """The kept parts without the cut parts."""
    out = [list(s) for s in segs]
    for ca, cb in cuts:
        nxt = []
        for a, b in out:
            if cb <= a or ca >= b:
                nxt.append([a, b])
                continue
            if ca > a:
                nxt.append([a, ca])
            if cb < b:
                nxt.append([cb, b])
        out = nxt
    return out


def silences(path: Path, noise_db: float = -32.0, min_len: float = 0.7, duration: float = 0.0) -> List[List[float]]:
    """Quiet stretches (dead air) found by FFmpeg's silence detector."""
    r = subprocess.run([FFMPEG_BIN, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=1800)
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and start is not None:
            out.append([start, float(m.group(1))])
            start = None
    if start is not None and duration:
        out.append([start, duration])
    return out


def auto_segments(duration: float, quiet: List[List[float]], keep_pad: float = 0.12) -> List[List[float]]:
    """Keep everything except the dead air, leaving a small breath of quiet at each cut so it does not sound chopped."""
    cuts = [[a + keep_pad, b - keep_pad] for a, b in quiet if b - a > 2 * keep_pad + 0.05]
    return normalize(subtract([[0.0, duration]], cuts), duration)


def filler_cuts(words: List[Dict]) -> List[List[float]]:
    """The "um"s and "uh"s found in a word list (each with start and end seconds)."""
    return [[max(0.0, w["start"] - 0.04), w["end"] + 0.04] for w in words if FILLER.match(str(w.get("word", "")).strip().lower())]


# ---------------------------------------------------------------- finding the face
def find_face(path: Path, duration: float, samples: int = 8) -> Optional[Dict]:
    """Where the streamer's face is: {"x","y","w","h"} as 0..1 fractions of the picture (the middle of several frames), or None."""
    try:
        import cv2
    except ImportError:
        return None
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    found = []
    try:
        for i in range(samples):
            cap.set(cv2.CAP_PROP_POS_MSEC, duration * (0.08 + 0.84 * i / max(1, samples - 1)) * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            faces = []
            try:
                from app.engine import face_signals
                fd = face_signals.detect(frame)
                if fd is not None:                 # the better face finder (face_signals.py); None means it is not available
                    faces = [(int(f["x"]), int(f["y"]), int(f["w"]), int(f["h"])) for f in fd if f["w"] >= max(36, h // 16)]
                else:
                    raise RuntimeError("fallback")
            except Exception:
                gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                faces = cas.detectMultiScale(gray, 1.15, 5, minSize=(max(36, h // 16), max(36, h // 16)))
            if len(faces):
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                found.append(((x + fw / 2) / w, (y + fh / 2) / h, fw / w, fh / h))
    finally:
        cap.release()
    if len(found) < 2:
        return None
    mid = lambda k: sorted(f[k] for f in found)[len(found) // 2]
    return {"x": round(mid(0), 4), "y": round(mid(1), 4), "w": round(mid(2), 4), "h": round(mid(3), 4)}


# ---------------------------------------------------------------- "ask" commands (understood without any AI, so they are free)
def _secs(text: str) -> float:
    m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", text.strip())
    if m:
        a, b, c = int(m[1]), int(m[2]), m[3]
        return a * 3600 + b * 60 + int(c) if c else a * 60 + b
    m = re.match(r"(\d+(?:\.\d+)?)", text.strip())
    if not m:
        raise ValueError(f"I could not read the time '{text}'.")
    return float(m.group(1))


T = r"(\d+:\d{1,2}(?::\d{1,2})?|\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)?"


def ask(text: str, state: Dict, duration: float) -> Tuple[Dict, List[str]]:
    """Apply what the member typed to the edit `state` (segments, aspect, fit, captions). Returns (new state, what was done).
    Understands: trim/cut N seconds off the start or end, keep only A to B, cut A to B, vertical / landscape / 4:5, blur / crop / whole / split,
    captions on / off. Several commands can be joined with 'and', a comma or a semicolon. Raises ValueError with a plain message."""
    st = {**state, "segments": [list(s) for s in state.get("segments", [])]}
    done: List[str] = []
    parts = [p.strip() for p in re.split(r"\s*(?:,|;|\band\b|\bthen\b)\s*", text.lower()) if p.strip()]
    if not parts:
        raise ValueError("Type what you want changed, for example: trim 3s off the end.")
    for p in parts:
        m = re.search(rf"(?:trim|cut|remove|delete|drop)\s+(?:the\s+)?(?:last|final)\s+{T}", p) or re.search(rf"(?:trim|cut|remove|delete|drop)\s+{T}\s+(?:off|from)\s+(?:the\s+)?(?:end|back|last)", p)
        if m:
            n = _secs(m.group(1))
            st["segments"] = subtract(st["segments"], [[max(0.0, (st["segments"][-1][1] if st["segments"] else duration) - n), duration + 1]]) if st["segments"] else []
            done.append(f"Removed the last {n:g} seconds")
            continue
        m = re.search(rf"(?:trim|cut|remove|delete|drop)\s+(?:the\s+)?first\s+{T}", p) or re.search(rf"(?:trim|cut|remove|delete|drop)\s+{T}\s+(?:off|from)\s+(?:the\s+)?(?:start|beginning|front)", p)
        if m:
            n = _secs(m.group(1))
            lo = st["segments"][0][0] if st["segments"] else 0.0
            st["segments"] = subtract(st["segments"], [[-1.0, lo + n]])
            done.append(f"Removed the first {n:g} seconds")
            continue
        m = re.search(rf"keep\s+(?:only\s+)?(?:from\s+)?{T}\s*(?:to|-|until|till)\s*{T}", p)
        if m:
            a, b = _secs(m.group(1)), _secs(m.group(2))
            st["segments"] = [[max(s[0], a), min(s[1], b)] for s in st["segments"] if min(s[1], b) > max(s[0], a)]
            done.append(f"Kept only {a:g}s to {b:g}s")
            continue
        m = re.search(rf"(?:cut|remove|delete|drop|trim)\s+(?:out\s+)?(?:from\s+)?{T}\s*(?:to|-|until|till)\s*{T}", p)
        if m:
            a, b = _secs(m.group(1)), _secs(m.group(2))
            st["segments"] = subtract(st["segments"], [[a, b]])
            done.append(f"Cut out {a:g}s to {b:g}s")
            continue
        hit = False
        if re.search(r"\b(vertical|portrait mode|9:16|shorts?)\b", p):
            st["aspect"] = "9:16"; done.append("Vertical 9:16"); hit = True
        elif re.search(r"\b(landscape|horizontal|wide|16:9)\b", p):
            st["aspect"] = "16:9"; done.append("Landscape 16:9"); hit = True
        elif re.search(r"\b(4:5|portrait)\b", p):
            st["aspect"] = "4:5"; done.append("Portrait 4:5"); hit = True
        if re.search(r"\bblur", p):
            st["fit"] = "blur"; done.append("Blurred background"); hit = True
        elif re.search(r"\bsplit", p):
            st["fit"] = "split"; done.append("Split screen"); hit = True
        elif re.search(r"\b(whole|full|fit|bars)\b", p):
            st["fit"] = "whole"; done.append("Whole clip"); hit = True
        elif re.search(r"\b(crop|zoom|fill|face)\b", p):
            st["fit"] = "crop"; done.append("Crop to fill"); hit = True
        if re.search(r"\b(captions?|subtitles?)\b", p):
            off = re.search(r"\b(no|remove|without|off|hide|disable)\b", p)
            st["captions"] = not off; done.append("Captions off" if off else "Captions on"); hit = True
        if not hit:
            raise ValueError(f"I did not understand '{p}'. Try: trim 3s off the end, cut 0:20 to 0:35, keep 0:10 to 0:40, vertical, blur background, captions on.")
    st["segments"] = normalize(st["segments"], duration)
    if not st["segments"]:
        raise ValueError("That would remove the whole video.")
    return st, done


# ---------------------------------------------------------------- the render
LOOKS = {"none": "", "warm": "colorbalance=rs=.08:gs=.02:bs=-.10:rm=.06:bm=-.06", "cool": "colorbalance=rs=-.08:bs=.12:rm=-.05:bm=.08",
         "vivid": "eq=saturation=1.5:contrast=1.08", "bw": "hue=s=0,eq=contrast=1.1", "vintage": "curves=preset=vintage",
         "cinematic": "curves=preset=increase_contrast,eq=saturation=0.9,vignette=PI/6", "bright": "eq=brightness=0.06:contrast=1.05:saturation=1.1"}
ANIMS = ("none", "fade", "pop")


def out_size(spec: Dict) -> Tuple[int, int]:
    """The size of the finished picture: the shape's full size times the spec's scale (a fast draft is smaller). Always even numbers."""
    W, H = ASPECTS[spec["aspect"]]
    k = float(spec.get("scale", 1.0))
    return max(2, int(W * k) // 2 * 2), max(2, int(H * k) // 2 * 2)


def _numv(v, d, lo, hi):
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return d


def _hexv(v, d):
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else d


def look_filter(look: Optional[Dict]) -> str:
    """The ffmpeg filters of a clip's colour look: a preset, then the member's own brightness / contrast / colour. Empty when nothing is changed."""
    if not look:
        return ""
    parts = [LOOKS.get(look.get("preset"), "")]
    b, c, s = float(look.get("brightness", 0)), float(look.get("contrast", 1)), float(look.get("saturation", 1))
    if abs(b) > 1e-3 or abs(c - 1) > 1e-3 or abs(s - 1) > 1e-3:
        parts.append(f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f}")
    return ",".join(p for p in parts if p)


def clean_spec(spec: Dict, info: Dict) -> Dict:
    """Check what the browser sent. Raises ValueError with a plain message."""
    dur = float(info["duration"])
    segs = normalize([[s[0], s[1]] for s in (spec.get("segments") or []) if isinstance(s, (list, tuple)) and len(s) == 2], dur)
    if not segs:
        raise ValueError("Keep at least one part of the video.")
    if sum(b - a for a, b in segs) > MAX_OUTPUT_SECONDS:
        raise ValueError(f"A finished video can be up to {MAX_OUTPUT_SECONDS // 60} minutes. Cut it shorter.")
    aspect = spec.get("aspect") if spec.get("aspect") in ASPECTS else "9:16"
    fit = spec.get("fit") if spec.get("fit") in FITS else "crop"
    if fit == "split" and aspect != "9:16":
        raise ValueError("Split screen is for the vertical 9:16 shape.")

    def frac(v, d):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return d
    focus = spec.get("focus") if isinstance(spec.get("focus"), dict) else {}
    cam = spec.get("cam") if isinstance(spec.get("cam"), dict) else None
    texts = []
    for t in (spec.get("texts") or [])[:20]:
        if not isinstance(t, dict) or not str(t.get("text") or "").strip():
            continue
        try:
            t0, t1 = float(t.get("t0", 0)), float(t.get("t1", dur))
        except (TypeError, ValueError):
            continue
        col = str(t.get("color") or "#ffffff")
        texts.append({"text": " ".join(str(t["text"]).split())[:120], "t0": max(0.0, t0), "t1": min(dur, t1) if t1 > t0 else dur,
                      "x": frac(t.get("x"), 0.5), "y": frac(t.get("y"), 0.5), "size": int(min(200, max(20, float(t.get("size") or 64)))),
                      "color": col if re.fullmatch(r"#[0-9a-fA-F]{6}", col) else "#ffffff",
                      "bold": bool(t.get("bold", True)), "italic": bool(t.get("italic", False)), "upper": bool(t.get("upper", False)),
                      "outline": _hexv(t.get("outline"), "#000000"), "ow": int(_numv(t.get("ow"), 4, 0, 16)), "shadow": int(_numv(t.get("shadow"), 1, 0, 8)),
                      "bg": _hexv(t.get("bg"), ""), "anim": t.get("anim") if t.get("anim") in ANIMS else "none"})
    total_len = sum(b - a for a, b in segs)

    def num(v, d, lo, hi):
        try:
            return min(hi, max(lo, float(v)))
        except (TypeError, ValueError):
            return d
    vol = num(spec.get("volume"), 1.0, 0.0, 2.0)
    fi, fo = num(spec.get("fade_in"), 0.0, 0.0, 10.0), num(spec.get("fade_out"), 0.0, 0.0, 10.0)
    if fi + fo > total_len:                                  # the two fades never overlap
        k = total_len / max(fi + fo, 0.001)
        fi, fo = fi * k, fo * k
    lk = spec.get("look") if isinstance(spec.get("look"), dict) else {}
    look = {"preset": lk.get("preset") if lk.get("preset") in LOOKS else "none", "brightness": round(num(lk.get("brightness"), 0.0, -0.5, 0.5), 3),
            "contrast": round(num(lk.get("contrast"), 1.0, 0.5, 2.0), 3), "saturation": round(num(lk.get("saturation"), 1.0, 0.0, 3.0), 3)}
    if not look_filter(look):
        look = None
    speed = num(spec.get("speed"), 1.0, 0.25, 4.0)
    scale, crf = num(spec.get("scale"), 1.0, 0.25, 1.0), int(num(spec.get("crf"), 20, 14, 32))
    zm = spec.get("zoom") if isinstance(spec.get("zoom"), dict) else {}
    zf, zt = num(zm.get("from"), 1.0, 1.0, 3.0), num(zm.get("to"), 1.0, 1.0, 3.0)
    zoom = {"from": round(zf, 3), "to": round(zt, 3), "x": round(num(zm.get("x"), 0.5, 0.0, 1.0), 3), "y": round(num(zm.get("y"), 0.5, 0.0, 1.0), 3)} if (zf > 1.001 or zt > 1.001) else None
    return {"segments": segs, "aspect": aspect, "fit": fit, "focus": {"x": frac(focus.get("x"), 0.5), "y": frac(focus.get("y"), 0.5)},
            "volume": round(vol, 3), "fade_in": round(fi, 2), "fade_out": round(fo, 2), "speed": round(speed, 3), "zoom": zoom, "look": look, "scale": round(scale, 3), "crf": crf,
            "cam": {k: frac(cam.get(k), d) for k, d in (("x", 0.0), ("y", 0.0), ("w", 0.3), ("h", 0.3))} if cam else None,
            "captions": bool(spec.get("captions")), "texts": texts}


def to_output(segs: List[List[float]], a: float, b: float) -> List[Tuple[float, float]]:
    """A stretch of the SOURCE as the pieces of it that survive in the result (times on the result's own clock)."""
    off, res = 0.0, []
    for s, e in segs:
        lo, hi = max(a, s), min(b, e)
        if hi > lo:
            res.append((off + lo - s, off + hi - s))
        off += e - s
    return res


def _ass_color(hex_color: str) -> str:
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H00{b}{g}{r}&".upper()


def build_ass(path: Path, W: int, H: int, segs: List[List[float]], words: Optional[List[Dict]], texts: List[Dict]) -> Path:
    """One subtitle file with the captions (already on the result's clock) and the member's text overlays."""
    from app.engine.subtitles import create_ass_header, format_timestamp
    head = create_ass_header(W, H)
    k = 1.0 if H >= W else 0.62
    head = head.replace(f",{SUBTITLE_FONT_SIZE},", f",{max(24, int(SUBTITLE_FONT_SIZE * k))},")
    if W > H:
        head = head.replace(",50,50,330,1", ",50,50,90,1")
    head = head.replace("\n[Events]", "\nStyle: UserText,Arial,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,5,20,20,20,1\n\n[Events]", 1)
    lines = [head.rstrip("\n")]
    if words:
        per = 3
        for i in range(0, len(words), per):
            chunk = words[i:i + per]
            for active in chunk:
                parts = []
                for w in chunk:
                    word = str(w["word"]).strip().upper().replace("{", "").replace("}", "")
                    parts.append(("{\\c&H0000FFFF&}" + word + "{\\c&H00FFFFFF&}") if w is active else word)
                lines.append(f"Dialogue: 0,{format_timestamp(active['start'])},{format_timestamp(active['end'])},ShortsDefault,,0,0,0,,{' '.join(parts)}")
    for t in texts:
        body = t["text"].replace("{", "").replace("}", "").replace("\\", "")
        for oa, ob in to_output(segs, t["t0"], t["t1"]):
            k = W / 1080 if H >= W else W / 1920 * 1.6
            tags = f"\\an5\\pos({int(t['x'] * W)},{int(t['y'] * H)})\\fs{int(t['size'] * k)}\\c{_ass_color(t['color'])}\\b{1 if t.get('bold', True) else 0}\\i{1 if t.get('italic') else 0}"
            if t.get("bg"):                                           # a box behind the text: a thick outline in the box colour
                tags += f"\\bord{max(int(t.get('ow', 4)), 14) * k:.1f}\\3c{_ass_color(t['bg'])}\\shad0"
            else:
                tags += f"\\bord{int(t.get('ow', 4)) * k:.1f}\\3c{_ass_color(t.get('outline') or '#000000')}\\shad{int(t.get('shadow', 1)) * k:.1f}"
            if t.get("anim") == "fade":
                tags += "\\fad(250,250)"
            elif t.get("anim") == "pop":
                tags += "\\fscx60\\fscy60\\t(0,180,\\fscx100\\fscy100)"
            lines.append(f"Dialogue: 1,{format_timestamp(oa)},{format_timestamp(ob)},UserText,,0,0,0,,{{{tags}}}{(body.upper() if t.get('upper') else body)}")
    from app.engine.video_processor import safe_name
    out = TEMP_DIR / f"{safe_name(path.stem)}_edit.ass"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _esc(p: Path) -> str:
    from app.engine.video_processor import escape_ffmpeg_path
    return escape_ffmpeg_path(p)


def _cover(sw: int, sh: int, W: int, H: int) -> Tuple[int, int]:
    k = max(W / sw, H / sh)
    return (int(sw * k + 1) // 2 * 2, int(sh * k + 1) // 2 * 2)


def layout(fit: str, W: int, H: int, info: Dict, focus: Dict, cam: Optional[Dict]) -> str:
    """The FFmpeg filter that turns the cut video [cv] into the final picture [lay]."""
    sw, sh = info["width"], info["height"]
    if fit == "blur":
        return (f"[cv]split=2[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:5[bgb];"
                f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs];[bgb][fgs]overlay=(W-w)/2:(H-h)/2[lay]")
    if fit == "whole":
        return f"[cv]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black[lay]"
    if fit == "split":
        top = H * 38 // 100 // 2 * 2
        bot = H - top
        if cam:
            cx, cy, cw, ch = cam["x"], cam["y"], cam["w"], cam["h"]
        else:                                      # no camera chosen: the top-left corner, where streamers keep it
            cx, cy, cw, ch = 0.0, 0.0, 0.3, 0.3
        pw, ph = max(2, int(cw * sw) // 2 * 2), max(2, int(ch * sh) // 2 * 2)
        px, py = min(max(0, int(cx * sw)), sw - pw), min(max(0, int(cy * sh)), sh - ph)
        return (f"[cv]split=2[a][b];[a]crop={pw}:{ph}:{px}:{py},scale={W}:{top}:force_original_aspect_ratio=increase,crop={W}:{top}[top];"
                f"[b]scale={W}:{bot}:force_original_aspect_ratio=increase,crop={W}:{bot}[bot];[top][bot]vstack=inputs=2[lay]")
    cwid, chei = _cover(sw, sh, W, H)               # crop: fill the screen and keep the face in view
    x = int(min(max(0.0, focus["x"] * cwid - W / 2), cwid - W))
    y = int(min(max(0.0, focus["y"] * chei - H / 2), chei - H))
    return f"[cv]scale={cwid}:{chei},crop={W}:{H}:{x}:{y}[lay]"


def build_cmd(src: Path, out: Path, spec: Dict, info: Dict, ass: Optional[Path], threads: int = 0) -> List[str]:
    W, H = out_size(spec)
    segs = spec["segments"]
    n, a = len(segs), info["has_audio"]
    g = []
    for i, (s, e) in enumerate(segs):
        g.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        if a:
            g.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
    ins = "".join(f"[v{i}][a{i}]" if a else f"[v{i}]" for i in range(n))
    g.append(f"{ins}concat=n={n}:v=1:a={1 if a else 0}[cv]" + ("[ca]" if a else ""))
    ca = "[ca]"
    vol, fi, fo = float(spec.get("volume", 1.0)), float(spec.get("fade_in", 0.0)), float(spec.get("fade_out", 0.0))
    if a and (abs(vol - 1.0) > 1e-3 or fi > 0 or fo > 0):          # the clip's own sound: louder, quieter, silent, faded
        total_len = sum(e - s for s, e in segs)
        chain = [f"volume={vol:.3f}"] + ([f"afade=t=in:st=0:d={fi:.2f}"] if fi > 0 else []) + ([f"afade=t=out:st={max(0.0, total_len - fo):.2f}:d={fo:.2f}"] if fo > 0 else [])
        g.append("[ca]" + ",".join(chain) + "[caf]")
        ca = "[caf]"
    g.append(layout(spec["fit"], W, H, info, spec["focus"], spec["cam"]))
    lay = "[lay]"
    lf = look_filter(spec.get("look"))
    if lf:                                                           # the colour look of the clip (before anything is drawn on top)
        g.append(f"{lay}{lf}[lk]")
        lay = "[lk]"
    zm = spec.get("zoom")
    if zm:                                                           # a slow zoom or a punch-in: the picture grows over the clip and a window of it is kept
        total_len = max(0.1, sum(e - s for s, e in segs))
        z = f"({zm['from']}+({zm['to']}-{zm['from']})*min(t/{total_len:.3f},1))"
        g.append(f"{lay}scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame,crop={W}:{H}:x='(iw-{W})*{zm['x']}':y='(ih-{H})*{zm['y']}'[lay2]")
        lay = "[lay2]"
    pip = spec.get("pip")
    if pip:                                                          # picture-in-picture: the member's reaction video in a corner for a stretch of the clip (its sound is not used)
        pi = len(spec.get("overlays") or []) + 1
        g.append(f"[{pi}:v]setpts=PTS-STARTPTS+{pip['t0']:.2f}/TB,scale=w='trunc({W}*{pip['scale']}/2)*2':h=-2" + (",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.95:t=5" if pip.get("border") else "") + "[pipv]")
        g.append(f"{lay}[pipv]overlay=x='(W-w)*{pip['x']}':y='(H-h)*{pip['y']}':enable='between(t,{pip['t0']:.2f},{pip['t1']:.2f})':eof_action=pass[pp]")
        lay = "[pp]"
    ovs = spec.get("overlays") or []
    for k, ov in enumerate(ovs):                                     # stickers and logos: pictures on top of the clip (they are not zoomed), each for its own stretch of time
        g.append(f"[{k + 1}:v]scale=w='trunc({W}*{ov['scale']}/2)*2':h=-2,format=rgba,colorchannelmixer=aa={ov['opacity']}[ov{k}]")
        g.append(f"{lay}[ov{k}]overlay=x='(W-w)*{ov['x']}':y='(H-h)*{ov['y']}':enable='between(t,{ov['t0']:.2f},{ov['t1']:.2f})':shortest=1[o{k}]")
        lay = f"[o{k}]"
    if ass:
        g.append(f"{lay}ass='{_esc(ass)}'[vout]")
        v = "[vout]"
    else:
        v = lay
    speed = float(spec.get("speed", 1.0))
    if abs(speed - 1.0) > 1e-3:                                      # slow motion or fast forward: picture and sound together
        g.append(f"{v}setpts=PTS/{speed:.4f}[vsp]")
        v = "[vsp]"
        if a:
            tempo, left = [], speed
            while left > 2.0 + 1e-9:
                tempo.append("atempo=2.0"); left /= 2.0
            while left < 0.5 - 1e-9:
                tempo.append("atempo=0.5"); left /= 0.5
            tempo.append(f"atempo={left:.4f}")
            g.append(f"{ca}{','.join(tempo)}[cas]")
            ca = "[cas]"
    pic_len = sum(e - s for s, e in segs) + 1.0
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y"] + (["-threads", str(int(threads))] if threads else []) + ["-i", str(src)]
    for ov in ovs:
        cmd += ["-loop", "1", "-t", f"{pic_len:.2f}", "-i", str(ov["path"])]
    if spec.get("pip"):
        cmd += ["-ss", f"{float(spec['pip']['start']):.2f}", "-t", f"{float(spec['pip']['t1']) - float(spec['pip']['t0']) + 0.5:.2f}", "-i", str(spec["pip"]["path"])]
    cmd += ["-filter_complex", ";".join(g), "-map", v]
    if a:
        cmd += ["-map", ca, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(spec.get("crf", 20))), "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out)]
    return cmd


def audio_of_cut(src: Path, segs: List[List[float]], out: Path) -> Path:
    """The sound of the kept parts only, for the speech-to-text (so caption times are already on the result's clock)."""
    g = [f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]" for i, (s, e) in enumerate(segs)]
    g.append("".join(f"[a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1,aresample=16000,aformat=channel_layouts=mono[o]")
    subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-filter_complex", ";".join(g), "-map", "[o]", str(out)], check=True, timeout=1800)
    return out


def render(src: Path, out: Path, spec: Dict, info: Dict, on_progress: Optional[Callable[[float], None]] = None, threads: int = 0) -> Path:
    """Cut, lay out, caption and write the finished video. `spec` must come from clean_spec."""
    out.parent.mkdir(parents=True, exist_ok=True)
    W, H = out_size(spec)
    total = sum(e - s for s, e in spec["segments"])
    out_total = total / float(spec.get("speed", 1.0))        # how long the result is
    words = None
    if spec["captions"] and info["has_audio"]:
        from app.engine.subtitles import transcribe_audio_to_words
        wav = TEMP_DIR / f"{out.stem}_cut.wav"
        try:
            audio_of_cut(src, spec["segments"], wav)
            words = transcribe_audio_to_words(wav, TEMP_DIR)
        finally:
            wav.unlink(missing_ok=True)
    ass = build_ass(out, W, H, spec["segments"], words, spec["texts"]) if (words or spec["texts"]) else None
    cmd = build_cmd(src, out, spec, info, ass, threads)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        for line in p.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    if on_progress:
                        on_progress(min(1.0, float(line.split("=")[1]) / 1_000_000 / max(out_total, 0.1)))
                except ValueError:
                    pass
        err = p.stderr.read()
        if p.wait() != 0:
            raise RuntimeError("The video could not be rendered: " + " ".join(err.strip().splitlines()[-2:])[:300])
    finally:
        if p.poll() is None:
            p.kill()
        if ass:
            ass.unlink(missing_ok=True)
    return out
