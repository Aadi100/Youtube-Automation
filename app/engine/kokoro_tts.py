"""Narrator voice that runs on this computer: Kokoro-82M (Apache 2.0 licence, free, safe for a monetized channel, no account, no key).

It replaces the unofficial Microsoft read-aloud connection (edge-tts), which Microsoft now refuses ("NoAudioReceived") and whose commercial
use is not allowed. The voice files (about 120 MB) are downloaded once into models/kokoro/ on first use.
Kokoro does not give the time of each word, so the times are worked out from the length of the finished audio (good enough for captions).
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Dict, List

from app.config import BASE_DIR, FFMPEG_BIN

MODEL_DIR = BASE_DIR / "models" / "kokoro"
BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {"model": os.environ.get("KOKORO_MODEL_FILE", "kokoro-v1.0.int8.onnx"), "voices": "voices-v1.0.bin"}   # int8: a quarter of the size, fast on a server CPU

# the older Microsoft names the studio already stores map to a Kokoro voice (so saved choices keep working)
MAP = {"en-US-GuyNeural": "am_adam", "en-US-ChristopherNeural": "am_michael", "en-US-AriaNeural": "af_bella", "en-US-JennyNeural": "af_heart",
       "en-GB-RyanNeural": "bm_george", "en-GB-SoniaNeural": "bf_emma", "en-AU-WilliamNeural": "am_puck", "en-CA-LiamNeural": "am_eric"}
DEFAULT = "am_adam"
_lock = threading.Lock()
_engine = None


class Unavailable(RuntimeError):
    pass


def voice_id(name: str) -> str:
    """A Kokoro voice for whatever the studio stored (Kokoro id as it is; a Microsoft name mapped by language and sound)."""
    n = (name or "").strip()
    if re.fullmatch(r"[abjzefhip][fm]_\w+", n):
        return n
    if n in MAP:
        return MAP[n]
    m = re.fullmatch(r"en-([A-Za-z]{2})-(\w+?)Neural", n)
    if m:                                                          # an unknown Microsoft voice: same country, a male or female guess
        female = m.group(2) in ("Aria", "Jenny", "Sonia", "Emma", "Libby", "Natasha", "Clara", "Mia", "Michelle", "Ana", "Ava", "Jane", "Sara", "Nancy", "Jenny")
        return {"GB": "bf_emma" if female else "bm_george"}.get(m.group(1).upper(), "af_bella" if female else DEFAULT)
    return DEFAULT


def _download(url: str, dest: Path) -> None:
    import requests
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=(15, 120)) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)


def _load():
    global _engine
    with _lock:
        if _engine is not None:
            return _engine
        try:
            from kokoro_onnx import Kokoro
        except ImportError as e:
            raise Unavailable("The free narrator (Kokoro) is not installed on the server yet. Run the update again (it installs it).") from e
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        paths = {}
        for k, name in FILES.items():
            p = MODEL_DIR / name
            if not p.is_file() or p.stat().st_size < 1_000_000:
                try:
                    _download(BASE_URL + name, p)
                except Exception as e:
                    raise Unavailable(f"The narrator voice files could not be downloaded ({type(e).__name__}). Try again in a few minutes.") from e
            paths[k] = str(p)
        try:
            _engine = Kokoro(paths["model"], paths["voices"])
        except Exception as e:
            for p in paths.values():                              # a broken download: remove it so the next try fetches it again
                Path(p).unlink(missing_ok=True)
            raise Unavailable(f"The narrator voice could not start ({type(e).__name__}). Try again.") from e
        return _engine


def available() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def _word_times(text: str, total: float) -> List[Dict]:
    """Spread the real length of the audio over the words (longer words and a pause at . , ? ! take more time)."""
    toks = text.split()
    if not toks or total <= 0:
        return []
    weights = [len(re.sub(r"\W", "", t)) + 2 + (4 if t[-1] in ".?!" else 2 if t[-1] in ",;:" else 0) for t in toks]
    k, t, out = total / sum(weights), 0.0, []
    for tok, w in zip(toks, weights):
        out.append({"word": tok, "start": round(t, 3), "end": round(t + w * k, 3)})
        t += w * k
    return out


def synthesize(text: str, voice: str, out: Path, speed: float = 1.0) -> List[Dict]:
    """Say `text` and save it as `out` (mp3, or wav if the name ends in .wav). Returns the words with start and end seconds."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise Unavailable("There is nothing to say.")
    eng = _load()
    with _lock:                                                    # one voice at a time (the model is not built for parallel calls)
        try:
            samples, rate = eng.create(text, voice=voice_id(voice), speed=speed, lang="en-us")
        except Exception as e:
            raise Unavailable(f"The narrator voice failed ({type(e).__name__}).") from e
    import numpy as np
    import scipy.io.wavfile as wf
    out.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("int16")
    wav = out if out.suffix.lower() == ".wav" else out.with_suffix(".tmp.wav")
    wf.write(str(wav), int(rate), pcm)
    if wav != out:
        try:
            subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k", str(out)], check=True, timeout=120)
        finally:
            wav.unlink(missing_ok=True)
    return _word_times(text, len(pcm) / float(rate))
