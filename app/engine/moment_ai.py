"""AI moment picker - our own version of the logic used by open-source clippers (OpenShorts, AI-Youtube-Shorts-Generator,
the n8n "Vizard" template), built on Gemini so it costs nothing extra:

  1. get a transcript with timestamps (YouTube's own auto-captions: no heavy transcription; or Whisper for live clips),
  2. long videos are split into 20-minute chunks with 60 s overlap,
  3. the LLM scores candidate moments 0-100 on hook, humour/surprise, emotional peak, conflict, quotable line and payoff,
     and returns a hook line + reason + a "safe" flag (sexual material is rejected),
  4. overlapping picks are merged (keep the higher score), moments under MIN_SCORE are dropped, the best N are kept.
Every function fails soft: no key / quota / bad JSON -> the caller falls back to its normal behaviour.
"""
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from app.engine import clipcfg

MIN_SCORE = 60            # moments below this are not worth a Short
CHUNK_S, OVERLAP_S = 1200, 60
MAX_CHUNKS = 5            # at most this many chunks per video
TIME_BUDGET_S = 150       # give up on one video's analysis after this many seconds
RUN_BUDGET_S = 420        # ...and stop analysing new videos once this much time was spent in one run
_spent = 0.0
CRITERIA = ("a strong hook in the first 3 seconds; funny, surprising or shocking beats; emotional peaks (hype, rage, disbelief, joy); "
            "competition or conflict; clutch plays and fails; quotable one-liners; a clear payoff. "
            "Avoid: intros, waiting, menus, long explanations, ads, and ANY sexual, nude or suggestive material, hate or graphic gore.")


def _log(msg: str) -> None:
    print(f"[Moments] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)


def _gemini_json(prompt: str, timeout: int = 90, task: str = "scoring"):
    from app.engine import llm
    return json.loads(llm.generate(task, prompt, json_mode=True, timeout=timeout))


def _gemini_json_old(prompt: str, timeout: int = 90):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("no Gemini key")
    from app.engine import gemini_util
    models = gemini_util.models()
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    last = ""
    for m in models:
        for _ in range(2):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=timeout)
                if r.status_code == 200:
                    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                last = f"HTTP {r.status_code}"
            except Exception as e:
                last = type(e).__name__
            time.sleep(2)
    raise RuntimeError(f"Gemini unavailable ({last})")


# ------------------------------------------------------------------ scoring ready-made clips (live moments)
def score_clips(items: List[Tuple[str, str, str]], game_name: str) -> Dict[str, Dict]:
    """items: [(id, title, transcript)] -> {id: {score, hook, reason, safe}}. Empty dict if the AI is unavailable."""
    if not items:
        return {}
    listing = "\n".join(f'- id "{i}": title "{t[:90]}"; spoken words: "{(tr or "(no speech detected)")[:500]}"' for i, t, tr in items)
    prompt = (f"You pick clips for a YouTube Shorts channel about the video game {game_name}. Score each candidate clip (about 40 seconds) "
              f"from 0 to 100 for how likely it is to perform as a Short. {clipcfg.criteria_text()} "
              "If there is no speech, judge from the title and give 50 when unsure. Be critical: most clips should score 40-75. "
              'Reply with JSON only: a list of {"id": string, "score": integer, "hook": "max 8 words", "reason": "max 14 words", "safe": boolean}. '
              "safe=false for anything sexual or nude or suggestive, hateful, or graphically violent.\n" + listing)
    try:
        data = _gemini_json(prompt)
    except Exception as e:
        _log(f"scoring skipped: {e}")
        return {}
    out = {}
    for d in data if isinstance(data, list) else []:
        try:
            out[str(d["id"])] = {"score": max(0, min(100, int(d.get("score", 50)))), "hook": str(d.get("hook", ""))[:80],
                                 "reason": str(d.get("reason", ""))[:120], "safe": bool(d.get("safe", True))}
        except (KeyError, ValueError, TypeError):
            continue
    return out


# ------------------------------------------------------------------ long videos: captions -> best moments
NL = chr(10)
_CAP_CACHE: Dict[str, List[Dict]] = {}


def fetch_captions(url: str) -> List[Dict]:
    """YouTube auto-captions as [{start, end, text}] (seconds). [] if the video has none. The last few are remembered for this run."""
    key = re.sub(r"[?&](si|t|feature)=[^&]*", "", url)
    if key in _CAP_CACHE:
        return _CAP_CACHE[key]
    segs = _fetch_captions(url)
    if segs:                                 # an empty answer may only be a temporary refusal (HTTP 429): never remembered
        if len(_CAP_CACHE) >= 6:
            _CAP_CACHE.pop(next(iter(_CAP_CACHE)))
        _CAP_CACHE[key] = segs
    return segs


def _fetch_captions(url: str) -> List[Dict]:
    from app.engine import discovery as D
    with tempfile.TemporaryDirectory() as td:
        try:
            D._ytdlp("--js-runtimes", "node", "--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", "en.*,en",
                     "--sub-format", "json3", "--no-playlist", "-o", str(Path(td) / "cap"), url)
        except Exception as e:
            _log(f"no captions ({str(e)[:80]})")
            return []
        files = sorted(Path(td).glob("cap*.json3"))
        if not files:
            return []
        data = json.loads(files[0].read_text(encoding="utf-8"))
    segs = []
    for ev in data.get("events", []):
        text = "".join(s.get("utf8", "") for s in ev.get("segs", []) or []).replace("\n", " ").strip()
        if text:
            st = ev.get("tStartMs", 0) / 1000
            segs.append({"start": st, "end": st + ev.get("dDurationMs", 2000) / 1000, "text": text})
    return segs


def _mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def _parse_time(v) -> float:
    """'12:34' / '1:02:03' / 754 -> seconds."""
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(v))]
    sec = 0.0
    for x in parts[-3:]:
        sec = sec * 60 + x
    return sec


def rank_transcript(segs: List[Dict], duration: float, want: int, game_name: str, min_score: int = MIN_SCORE,
                    events: Optional[List[Tuple[float, str]]] = None) -> List[Dict]:
    if min_score == MIN_SCORE:
        min_score = clipcfg.load()["min_score"]
    """Best moments of a long video: [{start, end, score, hook, reason}] sorted by score."""
    if not segs:
        return []
    chunks, t0 = [], 0.0
    while t0 < max(duration, segs[-1]["end"]):
        chunks.append((t0, t0 + CHUNK_S + OVERLAP_S))
        t0 += CHUNK_S
    # very long streams: look at a handful of evenly spread chunks, not all of them (each Gemini call takes a while)
    if len(chunks) > MAX_CHUNKS:
        step = (len(chunks) - 1) / (MAX_CHUNKS - 1)
        chunks = [chunks[round(i * step)] for i in range(MAX_CHUNKS)]
    found: List[Dict] = []

    def one_chunk(span):
        a, b = span
        lines = [f"[{_mmss(s['start'])}] {s['text']}" for s in segs if a <= s["start"] < b]
        if len(lines) < 5:
            return []
        notes = [f"[{_mmss(t)}] {d}" for t, d in (events or []) if a <= t < b][:25]
        heard = ("The sound of the video was measured too. These are the places where it jumps (a shout, laughter, loud after quiet); a moment "
                 "that has one of them is usually worth more:" + NL + NL.join(notes) + NL + NL) if notes else ""
        prompt = (f"You pick moments for a YouTube Shorts channel about the video game {game_name}. Below is a timestamped transcript "
                  f"([mm:ss] text) of part of a long video. Choose up to 5 moments of 20 to 55 seconds with the highest viral potential. "
                  f"{clipcfg.criteria_text()} Each moment must make sense to a stranger who has not seen the rest of the video: "
                  "start where the SETUP begins (the sentence that explains what is going on, a few seconds before the peak, never in the middle of a sentence) "
                  "and end 2 to 4 seconds AFTER the reaction or payoff has finished, never right at the peak. "
                  'Reply with JSON only: a list of {"start": "mm:ss copied exactly from a transcript bracket", "end": "mm:ss from a later bracket", "score": 0-100 integer, "hook": "max 8 words", '
                  '"reason": "max 14 words", "safe": boolean}. safe=false if it is sexual, nude, suggestive, hateful or graphic.\n\n'
                  + heard + "\n".join(lines)[:45000])
        try:
            data = _gemini_json(prompt, timeout=75, task="moments")
        except Exception as e:
            _log(f"chunk skipped: {e}")
            return []
        out = []
        for d in data if isinstance(data, list) else []:
            try:
                st, en, sc = _parse_time(d["start"]), _parse_time(d["end"]), int(d.get("score", 0))
            except (KeyError, ValueError, TypeError):
                continue
            if st < a - 1 or st >= segs[-1]["end"] or (duration and st >= duration):   # the model invented a time: ignore it
                continue
            en = min(en, segs[-1]["end"] + 2, duration or en)
            if not d.get("safe", True) or sc < min_score or en <= st:
                continue
            if en - st > 58:
                en = st + 58
            if en - st < 15:
                en = st + 25
            out.append({"start": st, "end": en, "score": sc, "hook": str(d.get("hook", ""))[:80], "reason": str(d.get("reason", ""))[:120]})
        return out

    from concurrent.futures import ThreadPoolExecutor, as_completed
    ex = ThreadPoolExecutor(max_workers=3)
    futs = [ex.submit(one_chunk, c) for c in chunks]
    deadline = time.time() + TIME_BUDGET_S
    try:
        for f in as_completed(futs, timeout=TIME_BUDGET_S):
            found += f.result()
    except Exception:
        _log(f"time budget ({TIME_BUDGET_S}s) reached - using what was found so far")
    ex.shutdown(wait=False, cancel_futures=True)
    found.sort(key=lambda m: -m["score"])
    keep: List[Dict] = []
    for m in found:   # drop moments that overlap an already-kept, higher-scoring one by more than 50%
        if all(min(m["end"], k["end"]) - max(m["start"], k["start"]) <= 0.5 * (m["end"] - m["start"]) for k in keep):
            keep.append(m)
    return keep[:want]


def pick_windows(url: str, duration: float, game_name: str, n: int = 4, events: Optional[List[Tuple[float, str]]] = None) -> List[Dict]:
    """The best n moments of a long YouTube video without 'most replayed' data: [{start, end, score, hook, reason}]."""
    global _spent
    if _spent > RUN_BUDGET_S:
        _log("analysis time budget for this run is used up - skipping the AI pick")
        return []
    from app.engine import ai_saver
    ckey = ai_saver.key_of("moments", re.sub(r"[?&](si|t|feature)=[^&]*", "", url), int(duration // 30), n, clipcfg.criteria_text(), [(round(a), b) for a, b in (events or [])])
    hit = ai_saver.cache_get("moments", ckey)
    if hit is not None:
        _log(f"moments of this video were found before: reusing them ({len(hit)})")
        return hit
    t0 = time.time()
    segs = fetch_captions(url)
    if not segs:
        _spent += time.time() - t0
        return []
    before_tokens = ai_saver.spent()
    best = rank_transcript(segs, duration, n, game_name, events=events)
    _spent += time.time() - t0
    for m in best:
        m["start"], m["end"] = round(m["start"], 1), round(min(m["end"], duration), 1)
        _log(f"moment {_mmss(m['start'])}-{_mmss(m['end'])} score {m['score']}: {m['hook']}")
    if best:
        ai_saver.cache_put("moments", ckey, best, max(1500, ai_saver.spent() - before_tokens))
    return best


def pick_window(url: str, duration: float, game_name: str, length: int = 45) -> Optional[Tuple[float, float, Dict]]:
    """Best (start, end, info) of a long YouTube video without 'most replayed' data, or None."""
    global _spent
    if _spent > RUN_BUDGET_S:
        _log("analysis time budget for this run is used up - skipping the AI pick")
        return None
    t0 = time.time()
    segs = fetch_captions(url)
    if not segs:
        _spent += time.time() - t0
        return None
    best = rank_transcript(segs, duration, 1, game_name)
    _spent += time.time() - t0
    if not best:
        return None
    m = best[0]
    _log(f"picked {_mmss(m['start'])}-{_mmss(m['end'])} score {m['score']}: {m['hook']} ({m['reason']})")
    return round(m["start"], 1), round(min(m["end"], duration), 1), m
