"""What makes a title or a description worth clicking, as plain rules the code can check.

The AI writes many titles; this module throws away the weak ones and picks the best, so a good title does not depend on the AI
remembering every rule. The same goes for descriptions: filler phrases are removed after the AI has written them.

Nothing here calls an AI. It is all deterministic and testable (see tests in the scratchpad: test_titles.py).
"""
import re
from typing import Dict, List, Optional, Tuple

# Words that make a title sound like every other title. One of them is not fatal, but it costs points.
FLUFF = {"insane", "crazy", "unbelievable", "epic", "wild", "chaos", "chaotic", "hilarious", "amazing", "incredible", "absolute", "legendary",
         "unreal", "mindblowing", "shocking", "feral", "goes viral", "must watch", "best ever", "you won't believe", "you wont believe"}
# Description filler: the sentence that holds one of these is removed (the AI keeps writing them whatever the prompt says).
DESC_FILLER = ("worth watching", "watch to see", "watch how", "watch as", "watch the", "in this clip", "in this video", "this clip", "a clip where",
               "a clip of", "the chaos", "quick, funny look", "it is a quick", "it's a quick", "must watch", "you won't believe", "you wont believe")
GENERIC_OPENERS = ("the craziest", "the best", "the funniest", "the most", "top 10", "best of")

# Titles that work, as a guide to the feel (not to copy): specific, human, a gap the video fills.
DEFAULT_EXAMPLES = [
    "He Grabbed the Wrong Car and the Whole Street Turned on Him",
    "Nobody Warned Him About the Last Door",
    "I Can't Believe This Actually Worked",
    "Would You Quit a Chase for Tacos?",
    "The One Mistake That Cost Him the Round",
    "She Asked for Help. Chat Said Run.",
    "POV: You Trust the Wrong Teammate",
    "Wait for What He Does at 0:20",
    "This Trick Shouldn't Be Possible",
    "Why Did He Stop in the Middle of the Road?",
]


def words_of(s: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9']+", s or "")


def clean_title(t) -> str:
    t = " ".join(str(t or "").replace("#Shorts", "").replace("#shorts", "").split()).strip(' "\'')
    return t.rstrip(" -–—:")


_FIRST_PERSON = re.compile(r"(?<![A-Za-z])(i|i'm|i've|i'll|i'd|my|me|mine|we|we're|our|us)(?![A-Za-z])", re.I)


def first_person(text: str) -> bool:
    """The clip belongs to another creator: the channel must not speak as the player ("I dropped in...", "my team...")."""
    return bool(_FIRST_PERSON.search(text or ""))


def _name_parts(names: Optional[List[str]]) -> List[str]:
    out = []
    for n in names or []:
        for w in words_of(n):
            if len(w) >= 3:
                out.append(w.lower())
    return out


def score_title(title: str, names: Optional[List[str]] = None, game: str = "") -> Tuple[int, List[str]]:
    """0-100 and the reasons it lost points. Deterministic: the same title always gets the same score."""
    t = clean_title(title)
    low = t.lower()
    ws = words_of(t)
    score, why = 70, []
    n = len(t)
    if n < 25:
        score -= 20; why.append("too short")
    elif n < 35:
        score -= 6; why.append("a little short")
    elif n > 65:
        score -= 25; why.append("too long (cut off in a feed)")
    elif n > 58:
        score -= 8; why.append("a little long")
    fluff = [w for w in FLUFF if re.search(r"\b" + re.escape(w) + r"\b", low)]
    if fluff:
        score -= 14 * len(fluff); why.append("generic words: " + ", ".join(fluff))
    if any(low.startswith(g) for g in GENERIC_OPENERS):
        score -= 18; why.append("generic opener")
    if names and any(p in low for p in _name_parts(names)):
        score -= 28; why.append("starts a title with a name nobody knows" if low.split()[:1] and low.split()[0] in _name_parts(names) else "uses the creator's name")
    if first_person(t):
        score -= 30; why.append("speaks as the player (I / my / we)")
    caps = [w for w in ws if len(w) > 2 and w.isupper() and not w.isdigit()]
    if len(caps) > 1:
        score -= 12; why.append("too many ALL-CAPS words")
    if len(re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", t)) > 1:
        score -= 8; why.append("too many emoji")
    if "#" in t:
        score -= 10; why.append("hashtag in the title")
    # what helps: a question, a number or a time, a quoted line, a contrast, a person doing something specific
    if "?" in t:
        score += 8
    if re.search(r"\d", t):
        score += 5
    if re.search(r"\b(but|until|instead|after|before|when|then|wait|nobody|never|always|only|why|how)\b", low):
        score += 6
    if 4 <= len(ws) <= 11:
        score += 4
    if len(set(w.lower() for w in ws)) < len(ws) - 2:
        score -= 6; why.append("repeats words")
    if game and low.count(game.lower()) > 1:
        score -= 10; why.append("game name twice")
    return max(0, min(100, score)), why


def pick_title(cands: List[Dict], names: Optional[List[str]] = None, game: str = "", bonus=None) -> Tuple[str, List[Dict]]:
    """cands: [{"t": title, "style": str, "score": 1-10 from the AI}] (plain strings are fine too).
    Returns (the best title, all candidates with their scores, best first). The AI's own opinion counts 40%, the rules 60%.
    `bonus` (optional): a function title -> points from the Learning Lab (a small nudge learned from the owner's own results)."""
    rows = []
    seen = set()
    for c in cands or []:
        if isinstance(c, str):
            c = {"t": c}
        t = clean_title((c or {}).get("t") or (c or {}).get("title"))
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        rules, why = score_title(t, names, game)
        try:
            ai = max(1.0, min(10.0, float(c.get("score")))) * 10
        except (TypeError, ValueError):
            ai = rules
        rows.append({"title": t, "style": str(c.get("style") or "")[:20], "rules": rules, "ai": round(ai), "total": round(0.6 * rules + 0.4 * ai), "why": why})
    if bonus:
        for r in rows:
            try:
                r["lab"] = float(bonus(r["title"]))
            except Exception:
                r["lab"] = 0.0
            r["total"] = round(r["total"] + r["lab"])
    rows.sort(key=lambda r: -r["total"])
    return (rows[0]["title"] if rows else ""), rows


def clean_about(text: str) -> str:
    """Remove the filler sentences ("Worth watching for...", "In this clip...") from a description. Keeps the text as it was if that would empty it."""
    text = (text or "").strip()
    if not text:
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    keep = [p for p in parts if not any(f in p.lower() for f in DESC_FILLER)]
    out = " ".join(keep).strip()
    return out if len(out.split()) >= 12 else text


def clean_hook(text: str) -> str:
    text = " ".join((text or "").split()).strip()
    low = text.lower()
    if any(f in low for f in DESC_FILLER) or first_person(text):
        return ""                          # the caller then uses a stronger fallback (the first sentence of the story)
    return text[:140]


def examples_block(extra: Optional[List[str]] = None, limit: int = 10) -> str:
    """The style examples shown to the AI: the owner's own liked titles first (later, from the Title Lab), then the built-in ones."""
    seen, out = set(), []
    for t in list(extra or []) + DEFAULT_EXAMPLES:
        t = clean_title(t)
        if t and t.lower() not in seen:
            seen.add(t.lower()); out.append("- " + t)
    return "\n".join(out[:limit])
