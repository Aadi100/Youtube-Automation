"""Complete context for a clip: where it should start and end, and what the viewer (and the AI that writes about it) needs to know.

A moment found by the loudest sound or by "most replayed" is cut at a fixed length around the peak, so it often starts in the middle of a
story and stops before the payoff. With the video's captions this module
  * moves the start back to where the setup begins (a pause between two sentences) and the end to after the reaction finishes,
  * and writes a short "what came before" text, so the narration can set the scene for someone who never saw the rest of the video.

Everything here is plain code: no AI call, no download. It works on caption segments [{start, end, text}] in seconds. Without captions
the windows are returned as they are (the caller then only starts a little earlier, see discovery._peak_windows).
"""
import re
from typing import Dict, List, Optional, Tuple

PAUSE = 0.55          # a gap this long between two caption lines is where one sentence ended and the next began
MAX_LEAD = 11.0       # how far before the peak the setup may begin
LEAD_WANT = 6.0       # how much run-up a clip should have before its peak, so a stranger can follow it
MAX_TAIL = 7.0        # how far after the peak the reaction may run
PAD_END = 0.35        # a breath after the last word
MAX_LEN = 58.0        # a Short must stay under 60 s
MIN_LEN = 15.0


def _strong_start(segs: List[Dict], i: int) -> bool:
    """Is segment i the start of a new sentence? (the line before ended with . ? ! or there was a pause before it)"""
    if i <= 0:
        return True
    prev, cur = segs[i - 1], segs[i]
    if re.search(r"[.?!][\"')\]]*\s*$", prev["text"].strip()):
        return True
    return cur["start"] - prev["end"] >= PAUSE


def _strong_end(segs: List[Dict], i: int) -> bool:
    """Does segment i end a sentence? (it ends with . ? ! or a pause follows it)"""
    if i >= len(segs) - 1:
        return True
    cur, nxt = segs[i], segs[i + 1]
    if re.search(r"[.?!][\"')\]]*\s*$", cur["text"].strip()):
        return True
    return nxt["start"] - cur["end"] >= PAUSE


def snap_start(segs: List[Dict], start: float, max_lead: float = MAX_LEAD, want_lead: float = LEAD_WANT) -> float:
    """Where the clip should begin: at the start of a sentence (never in the middle of one), about `want_lead` seconds before the peak so the
    set-up is in the clip, and never more than max_lead seconds earlier."""
    if not segs:
        return start
    strong = [s["start"] for i, s in enumerate(segs) if start - max_lead <= s["start"] <= start + 0.8 and _strong_start(segs, i)]
    if strong:
        best = min(strong, key=lambda t: abs(t - (start - want_lead)))      # the sentence start nearest to "6 seconds of run-up"
        return max(0.0, best - 0.15)
    inside = [s["start"] for s in segs if start - max_lead <= s["start"] <= start + 0.8]
    return max(0.0, (inside[0] if inside else start) - 0.15)


def snap_end(segs: List[Dict], end: float, max_tail: float = MAX_TAIL) -> float:
    """The end of the sentence in which the clip would otherwise stop (never more than max_tail seconds later), plus a short breath."""
    if not segs:
        return end
    for i, s in enumerate(segs):
        if s["end"] < end - 0.8:
            continue
        if s["end"] > end + max_tail:
            break
        if _strong_end(segs, i):
            return s["end"] + PAD_END
    later = [s["end"] for s in segs if end - 0.8 <= s["end"] <= end + max_tail]
    return (later[0] if later else end) + PAD_END


def fit_window(segs: List[Dict], start: float, end: float, duration: float = 0.0,
               min_len: float = MIN_LEN, max_len: float = MAX_LEN) -> Tuple[float, float]:
    """A window that begins at the setup and ends after the reaction, within [min_len, max_len]. Keeps the peak (the payoff) when it must trim."""
    s, e = snap_start(segs, start), snap_end(segs, end)
    if duration:
        e = min(e, duration)
    if e - s > max_len:                       # too long: start later (at a sentence start) rather than lose the payoff
        later = [x["start"] for i, x in enumerate(segs) if _strong_start(segs, i) and e - max_len <= x["start"] <= start + 0.8]
        s = (later[0] - 0.15) if later else e - max_len
    guard = 0
    while e - s < min_len and s > 0.5 and guard < 6:     # too short to tell a story: add the sentence before it (never a cut in the middle of one)
        guard += 1
        prev = [x["start"] for i, x in enumerate(segs) if _strong_start(segs, i) and x["start"] < s - 0.4 and e - x["start"] <= max_len]
        if not prev:
            if not segs:
                s = max(0.0, e - min_len)
            break
        s = prev[-1] - 0.15
    return round(max(0.0, s), 1), round(e, 1)


def _squash(text: str) -> str:
    return " ".join((text or "").split())


def before_text(segs: List[Dict], start: float, seconds: float = 90.0, max_chars: int = 650) -> str:
    """What was said in the `seconds` before the clip (YouTube's rolling captions repeat lines: repeats are dropped)."""
    out, last = [], ""
    for s in segs:
        if s["end"] <= start and s["start"] >= start - seconds:
            t = _squash(s["text"])
            if t and t != last and t not in last:
                out.append(t)
            last = t
    text = " ".join(out)
    return text[-max_chars:].lstrip()


def clean_description(desc: str, max_chars: int = 300) -> str:
    """The first useful words of a video's description: no links, no hashtags, no 'subscribe' lines."""
    keep = []
    for line in (desc or "").splitlines():
        line = _squash(re.sub(r"https?://\S+|#\w+|@\w+", "", line))
        if len(line) < 25 or re.search(r"subscribe|follow me|business|sponsor|discount|promo code|socials|merch|patreon|join the|original stream|full stream|playlist|chronological|all .{0,30}highlights", line, re.I)                 or re.match(r"(watch|check out|follow|join|listen|download|use code|click)", line, re.I):
            continue
        keep.append(line)
        if sum(len(x) for x in keep) > max_chars:
            break
    return " ".join(keep)[:max_chars]


def build_context(info: Dict, segs: List[Dict], start: float) -> str:
    """The text the narration and the title step get besides the clip's own words: what the video is, and what led up to this moment."""
    parts = []
    title = _squash(info.get("title") or "")
    chan = _squash(info.get("uploader") or info.get("channel") or "")
    if title:
        parts.append(f'The full video is called "{title[:120]}"' + (f" (channel: {chan[:40]})" if chan else "") + ".")
    about = clean_description(info.get("description") or "")
    if about:
        parts.append(f"About it: {about}")
    b = before_text(segs, start)
    if b:
        parts.append(f"Just before this moment, they said: {b}")
    return " ".join(parts)[:1400]
