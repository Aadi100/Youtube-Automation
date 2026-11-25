"""Find the exciting moments of a video from its SOUND: shouting, laughing, cheering, a sudden loud reaction after a quiet stretch.

Why: the automatic video maker used to choose a moment only from the title, the captions or YouTube's "most replayed" curve, and took the
first seconds of a video that had none of these. The sound is always there and says a lot about where something happened.

How (plain signal processing, no AI model, no tokens): the audio is decoded to 16 kHz mono and measured second by second.
  spike    how much louder this second is than the stretch around it (a shout in normal talk)
  burst    how many sudden jumps in loudness (laughter and applause are made of them)
  noisy    broadband sound while something is audible (crowds, laughing, cheering sound "rougher" than speech)
  rise     loud after quiet (the classic pay-off shape)
Each is turned into "how unusual is this second for THIS video" (a percentile), so a quiet talker and a screaming streamer both give
meaningful peaks. They are blended into one curve; its strongest, well separated peaks are the candidate moments.

Everything fails soft: with no audio, or on any error, the callers just go on without sound peaks.
"""
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

SR = 16000
FRAME = SR // 20                    # 50 ms
WEIGHTS = {"spike": 0.42, "burst": 0.24, "noisy": 0.16, "rise": 0.18}


def _decode(media: Path, ffmpeg: str) -> np.ndarray:
    p = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                       capture_output=True, timeout=600)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("could not read the sound")
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _pct(x: np.ndarray) -> np.ndarray:
    """0..1: how unusual each second is for this video (rank among its own seconds)."""
    if x.size == 0:
        return x
    from scipy.stats import rankdata
    return ((rankdata(x, method="min") - 1) / max(1, x.size - 1)).astype(np.float32)


def _rolling_median(x: np.ndarray, size: int) -> np.ndarray:
    from scipy.ndimage import median_filter
    return median_filter(x, size=size, mode="nearest")


def features(media: Path, ffmpeg: str = "ffmpeg") -> Dict[str, np.ndarray]:
    """Per-second raw measures: loud (dB), spike, burst, noisy, rise. Empty dict when there is not enough sound."""
    pcm = _decode(media, ffmpeg)
    n_frames = pcm.size // FRAME
    per = SR // FRAME                                   # frames per second (20)
    n = n_frames // per
    if n < 30:
        return {}
    frames = pcm[: n_frames * FRAME].reshape(n_frames, FRAME)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    sec_rms = rms[: n * per].reshape(n, per).mean(axis=1)
    loud = 20 * np.log10(sec_rms + 1e-5)
    if float(np.ptp(loud)) < 8:                         # flat sound (silence, a constant hum): nothing stands out
        return {}
    # spike: loudness against the sound just BEFORE and just AFTER (a shout in normal talk). A music bed that starts and stays loud is
    # not a moment: it is as loud afterwards as it is now, so it scores low. A shout or a laugh dies away.
    med = _rolling_median(loud, 15)
    pad = np.concatenate([np.full(9, med[0]), med, np.full(9, med[-1])])
    before, after = pad[: n], pad[18: 18 + n]
    spike = np.clip(loud - np.maximum(before, after), 0, 40)
    # burst: sudden doublings of the loudness between 50 ms frames, per second (laughter / applause are onset-dense)
    on = np.concatenate([[False], rms[1:] > 2.0 * np.maximum(rms[:-1], 1e-5)])
    burst = on[: n * per].reshape(n, per).sum(axis=1).astype(np.float32)
    # noisy: zero-crossing rate, only where something is audible
    zc = (np.signbit(frames[:, 1:]) != np.signbit(frames[:, :-1])).mean(axis=1)
    noisy = zc[: n * per].reshape(n, per).mean(axis=1)
    noisy = noisy * (loud > np.percentile(loud, 35))
    # rise: loud after quiet. Only the part of the jump that does NOT stay: a bed of music that starts is as loud afterwards, so it counts for nothing.
    jump = np.clip(loud - before, 0, 40)
    stays = np.clip((after - before) / np.maximum(jump, 1e-3), 0, 1)
    rise = jump * (1 - stays)
    return {"loud": loud.astype(np.float32), "spike": spike.astype(np.float32), "burst": burst, "noisy": noisy.astype(np.float32), "rise": rise.astype(np.float32)}


def excitement(feat: Dict[str, np.ndarray], smooth: int = 3) -> np.ndarray:
    """One 0..1 curve: how exciting each second sounds compared with the rest of this video."""
    if not feat:
        return np.zeros(0, dtype=np.float32)
    c = sum(WEIGHTS[k] * _pct(feat[k]) for k in WEIGHTS)
    # the loudest part of a video is rarely silence: a second must also be audible to count
    c = c * (0.35 + 0.65 * _pct(feat["loud"]))
    if smooth > 1:
        c = np.convolve(c, np.ones(smooth) / smooth, mode="same")
    lo, hi = float(c.min()), float(c.max())
    return ((c - lo) / (hi - lo)).astype(np.float32) if hi > lo else np.zeros_like(c)


def peaks(curve: np.ndarray, want: int, min_gap: int = 50, edge: int = 12, floor: float = 0.55) -> List[Tuple[float, float]]:
    """[(second, strength 0..1)] strongest first, at least min_gap seconds apart, not at the very start or end, and only really standing-out seconds."""
    if curve.size < 40:
        return []
    c = curve.copy()
    c[:edge] = 0
    c[-edge:] = 0
    out: List[Tuple[float, float]] = []
    while len(out) < want:
        i = int(c.argmax())
        if c[i] < floor:
            break
        out.append((float(i), float(c[i])))
        c[max(0, i - min_gap): i + min_gap] = 0
    return out


def windows(pk: List[Tuple[float, float]], length: float, duration: float, before_share: float = 0.58) -> List[Tuple[float, float, int]]:
    """[(start, end, score)] around each peak: more run-up than aftermath (the loud part is the reaction, the story comes before it)."""
    out = []
    for t, s in pk:
        start = max(0.0, t - before_share * length)
        end = min(duration or (t + length), start + length)
        start = max(0.0, end - length)
        out.append((round(start, 1), round(end, 1), int(min(82, 50 + 32 * s))))        # below a moment that the words AND the sound agree on
    return out


def events(feat: Dict[str, np.ndarray], curve: np.ndarray, limit: int = 30) -> List[Tuple[float, str]]:
    """Short notes for the AI that picks moments from the captions: where the sound jumps and what kind of jump it is."""
    if not feat or curve.size == 0:
        return []
    out = []
    for t, _s in peaks(curve, limit, min_gap=12, edge=3, floor=0.7):
        i = int(t)
        kinds = []
        if _pct(feat["burst"])[i] > 0.9:
            kinds.append("laughter or applause likely")
        if _pct(feat["spike"])[i] > 0.92:
            kinds.append("sudden shout")
        if _pct(feat["rise"])[i] > 0.92:
            kinds.append("loud after quiet")
        out.append((t, "SOUND: " + (", ".join(kinds) or "loud moment")))
    return sorted(out)


def analyse(media: Path, ffmpeg: str = "ffmpeg") -> Optional[Dict]:
    """features + curve in one call, or None when there is no usable sound."""
    try:
        f = features(media, ffmpeg)
    except Exception:
        return None
    if not f:
        return None
    return {"features": f, "curve": excitement(f), "seconds": int(f["loud"].size)}


def merge_windows(found: List[Tuple[float, float, float, str]], sound: List[Tuple[float, float, int]], want: int, boost: int = 8) -> List[Tuple[float, float, float, str]]:
    """Combine the windows chosen from words / replays with the sound windows. A window the sound agrees with gets more score; a strong
    sound peak nobody else found is added. [(start, end, score, hook)] best first, no two overlapping by more than half."""
    out: List[list] = [list(w) for w in found]
    for s, e, sc in sound:
        hit = next((o for o in out if min(o[1], e) - max(o[0], s) > 0.35 * (e - s)), None)
        if hit:
            hit[2] = min(99, float(hit[2]) + boost)
        else:
            out.append([s, e, float(sc), "Loud, exciting moment"])
    out.sort(key=lambda w: -float(w[2]))
    keep: List[list] = []
    for w in out:
        if all(min(w[1], k[1]) - max(w[0], k[0]) <= 0.5 * (w[1] - w[0]) for k in keep):
            keep.append(w)
    return [tuple(w) for w in keep[:want]]
