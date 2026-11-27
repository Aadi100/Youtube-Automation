"""Story videos: the script. A story is a list of SCENES; each scene has the words that are spoken, what we see (the characters and what they do) and how the camera moves.

Two ways in: the AI writes the whole story from an idea, or the member writes the story (their own words are kept, the AI only cuts them into scenes and describes the pictures).
Whatever comes back from an AI is checked and cleaned here, so a strange answer can never break a video: scene count, lengths, characters, words that are not allowed.
"""
import json
import re
from typing import Dict, List, Optional

ART_STYLES = [   # id, name, what is added to every picture so that all scenes look like the same film
    ("cartoon3d", "3D cartoon", "stylised 3D animated movie still, soft lighting, expressive characters, rich colours, cinematic framing"),
    ("anime", "Anime", "anime film still, clean line art, painted backgrounds, dramatic lighting, expressive eyes"),
    ("comic", "Comic book", "comic book illustration, bold ink lines, halftone shading, vivid flat colours"),
    ("storybook", "Storybook painting", "hand painted storybook illustration, soft watercolour textures, warm gentle light"),
    ("noir", "Dark and moody", "dark moody illustration, deep shadows, cold colours, cinematic fog and rim light, no gore"),
    ("realistic", "Realistic (must be labelled as AI)", "photorealistic cinematic film still, natural light, shallow depth of field"),
]
STYLE_IDS = [a[0] for a in ART_STYLES]
CAMERAS = ("slow push in", "slow pull back", "pan left", "pan right", "static with gentle movement", "slow tilt up")
MAX_SCENES, MIN_SCENES = 12, 4
MAX_TOTAL_SECONDS = 70
WORDS_PER_SECOND = 2.6                     # a calm narrator
BAD = re.compile(r"\b(nazi|porn|nude|naked|rape|suicide|self[- ]harm|kill yourself|child abuse|terroris[mt]|bomb making)\b", re.I)


def style(sid: str) -> tuple:
    return next((a for a in ART_STYLES if a[0] == sid), ART_STYLES[0])


def speak_seconds(text: str) -> float:
    return max(1.5, len(re.findall(r"[\w']+", text)) / WORDS_PER_SECOND)


def _s(v, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def clean(raw: Dict, genre: str = "", style_id: str = "cartoon3d") -> Dict:
    """Check and tidy a script. Raises ValueError with a plain message when it cannot be used."""
    if not isinstance(raw, dict):
        raise ValueError("The script is not valid.")
    chars, ids = [], set()
    for c in (raw.get("characters") or [])[:4]:
        if isinstance(c, dict) and _s(c.get("name"), 40):
            cid = re.sub(r"[^a-z0-9_]", "", _s(c.get("id"), 12).lower()) or f"c{len(chars) + 1}"
            if cid in ids:
                cid = f"c{len(chars) + 1}"
            ids.add(cid)
            chars.append({"id": cid, "name": _s(c.get("name"), 40), "look": _s(c.get("look"), 200)})
    scenes = []
    for sc in (raw.get("scenes") or [])[:MAX_SCENES]:
        if not isinstance(sc, dict):
            continue
        narr, vis = _s(sc.get("narration"), 240), _s(sc.get("visual"), 300)
        if not narr or not vis:
            continue
        try:
            sec = float(sc.get("seconds") or 0)
        except (TypeError, ValueError):
            sec = 0.0
        sec = max(3.0, min(8.0, max(sec, round(speak_seconds(narr) + 0.4, 1))))
        cam = _s(sc.get("camera"), 40).lower()
        scenes.append({"n": len(scenes) + 1, "narration": narr, "visual": vis, "camera": cam if cam in CAMERAS else CAMERAS[len(scenes) % len(CAMERAS)], "seconds": round(sec, 1),
                       "characters": [x for x in (sc.get("characters") or []) if x in ids][:3]})
    if len(scenes) < MIN_SCENES:
        raise ValueError(f"The story needs at least {MIN_SCENES} scenes. Add more to the script or try again.")
    total = sum(s["seconds"] for s in scenes)
    if total > MAX_TOTAL_SECONDS:
        raise ValueError(f"The story is {int(total)} seconds long. A Short can be about {MAX_TOTAL_SECONDS} seconds at most. Cut some scenes.")
    text = " ".join([_s(raw.get("title"), 90), _s(raw.get("description"), 600)] + [s["narration"] + " " + s["visual"] for s in scenes])
    if BAD.search(text):
        raise ValueError("The story has a subject that is not allowed (it must be safe for a general audience). Change it and try again.")
    sid = raw.get("style") if raw.get("style") in STYLE_IDS else (style_id if style_id in STYLE_IDS else "cartoon3d")
    tags = [re.sub(r"[^\w]", "", str(t))[:30] for t in (raw.get("tags") or [])[:8]]
    return {"title": _s(raw.get("title"), 90) or "A short story", "description": _s(raw.get("description"), 600), "tags": [t for t in tags if t], "genre": genre or _s(raw.get("genre"), 20),
            "style": sid, "characters": chars, "scenes": scenes, "seconds": round(total, 1), "realistic": bool(raw.get("realistic")) or sid == "realistic"}


def _ask(prompt: str) -> Dict:
    from app.engine import llm
    raw = llm.generate("story-script", prompt, json_mode=True, timeout=90).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("The AI did not send a script. Try again.")
    return json.loads(raw[a:b + 1])


FORMAT = ('Return only JSON: {"title": "...", "description": "1-2 sentences for the video description", "tags": ["5 single words"], "realistic": false, '
          '"characters": [{"id": "c1", "name": "...", "look": "short, fixed visual description: age, hair, clothes, colours"}], '
          '"scenes": [{"narration": "what the narrator says (max 25 words)", "visual": "what we SEE: who is where and what they DO (movement), one clear picture", '
          '"camera": "one of: ' + ", ".join(CAMERAS) + '", "seconds": 5, "characters": ["c1"]}]}')


def write(genre_name: str, premise: str, seconds: int = 40, style_id: str = "cartoon3d", genre: str = "") -> Dict:
    """The AI writes the whole story from an idea."""
    seconds = max(20, min(60, int(seconds or 40)))
    n = max(MIN_SCENES, min(MAX_SCENES, round(seconds / 5.5)))
    prompt = (f"Write an ORIGINAL short story for a vertical video of about {seconds} seconds, genre: {genre_name}.\nIdea: {_s(premise, 500)}\n\n"
              f"Rules: exactly {n} scenes. The first narration line is a hook that makes people stay. Invented characters and places only: no real people, brands or real tragedies. "
              "Safe for a general audience (no gore, no sexual content, no hate). Keep the SAME characters (use their ids) so the pictures match. Each scene is one clear moving picture. "
              "The last scene ends on a twist or a line that makes people want to watch it again. Plain spoken English, short sentences.\n" + FORMAT)
    return clean(_ask(prompt), genre, style_id)


def split_own(text: str, seconds: int = 40, style_id: str = "cartoon3d", genre: str = "") -> Dict:
    """The member's own story: their words are kept exactly; the AI only cuts them into scenes and says what each picture shows (or, with no AI, the text is cut by sentences)."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) < 80:
        raise ValueError("Write a longer story (at least a few sentences).")
    if len(text) > 2500:
        raise ValueError("That story is too long for a Short. Keep it under about 2,500 characters.")
    if BAD.search(text):
        raise ValueError("The story has a subject that is not allowed (it must be safe for a general audience).")
    try:
        prompt = (f"Cut this story into scenes for a vertical video. KEEP THE WORDS EXACTLY as written (do not rewrite them): the scene narrations together must be the whole text, in order.\n"
                  f"For each scene say what we SEE (who and what they do) and the camera. Invent short fixed looks for the characters so the pictures match.\n\nSTORY:\n{text}\n\n" + FORMAT)
        return clean(_ask(prompt), genre, style_id)
    except Exception as e:
        print(f"[Stories] own script cut by sentences (no AI answer: {str(e)[:80]})", flush=True)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    scenes, cur = [], ""
    for s in sentences:
        if cur and (len((cur + " " + s).split()) > 22):
            scenes.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        scenes.append(cur)
    return clean({"title": " ".join(sentences[0].split()[:8]).rstrip(".!?"), "description": sentences[0][:200], "characters": [],
                  "scenes": [{"narration": s, "visual": f"An illustration of: {s[:160]}", "camera": CAMERAS[i % len(CAMERAS)]} for i, s in enumerate(scenes)]}, genre, style_id)
