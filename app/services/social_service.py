"""Post on TikTok, Instagram and Facebook: the 'Rewrite with AI' button. The first captions are built by rules (free); this asks an AI to write a fresh one for one platform.
It is paid for like the headline ideas: a member pays at least 1 token for a caption that was written, nothing if the AI failed. The owner is never charged."""
import re
from typing import Dict, Optional

from app.models import Video, oid
from app.services import token_service as tokens
from app.views.serializers import SOCIAL, SOCIAL_NAMES, social_pack

LIMITS = {"tiktok": 300, "instagram": 2200, "facebook": 2200}
RULES = {
    "tiktok": "A TikTok caption: at most 300 characters in all. One punchy hook line that makes people want to watch, then the credit line, then 3 to 5 hashtags. At most 2 emojis.",
    "instagram": "An Instagram Reels caption: a hook line first (it is all people see before 'more'), then 1 or 2 short lines of story, then the credit line, then 6 to 8 hashtags on the last line. At most 3 emojis.",
    "facebook": "A Facebook Reels caption: friendly and conversational, no hashtag wall (at most 2 hashtags). A hook line, one short story line, a question that makes people comment, then the YouTube link if one is given, then the credit line.",
}


def price() -> float:
    """Tokens a member pays for one rewrite: the owner's price (Settings -> Pricing). A fraction is collected on the account and taken once it adds up to a whole token."""
    return float(tokens.pricing().get("social_caption") or 0)


def _facts(doc: dict) -> Dict:
    pack = social_pack({k: v for k, v in doc.items() if k != "social_text"})
    title = re.sub(r"\s*#\w+", "", doc.get("title") or "").strip()
    head = next((ln.strip() for ln in (doc.get("description") or "").split("\n") if ln.strip() and not ln.strip().startswith("#")), "")
    names = []
    for c in doc.get("credits") or []:
        n = (c.get("creator") or "").strip()
        if n and n.lower() not in [x.lower() for x in names]:
            names.append(n)
    yt = doc.get("youtube_url") or (f"https://youtu.be/{doc['youtube_id']}" if doc.get("youtube_id") else "")
    return {"title": title, "story": re.sub(r"\s*#\w+", "", head).strip(), "game": doc.get("game_name") or "", "credit": ("Clip by " + ", ".join(names[:3])) if names else "", "youtube": yt, "rules_caption": pack}


def _clean(text: str, platform: str, facts: Dict) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-z]*\n?|```$", "", t).strip().strip('"').strip()
    t = re.sub(r"(?i)\s*#(shorts|short|youtubeshorts)\b", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if facts["credit"] and facts["credit"].lower() not in t.lower():       # the credit is never dropped
        t = (t + "\n" + facts["credit"]).strip()
    if platform == "facebook" and facts["youtube"] and facts["youtube"] not in t:
        t = (t + "\n" + facts["youtube"]).strip()
    tags = re.findall(r"#\w+", t)
    cap = {"tiktok": 5, "instagram": 8, "facebook": 2}[platform]
    for extra in tags[cap:]:                                                  # more hashtags than the platform likes: drop the extra ones
        t = t.replace(extra, "", 1)
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    if len(t) > LIMITS[platform]:
        t = t[:LIMITS[platform]].rsplit(" ", 1)[0].rstrip()
    return t


def rewrite(doc: dict, uid: str, platform: str) -> Dict:
    """Write a new caption for one platform. Returns {caption, charged}. Raises ValueError for a plain message (no tokens, no AI)."""
    if platform not in SOCIAL:
        raise ValueError(f"platform must be one of {sorted(SOCIAL)}")
    why = tokens.small_shortfall(str(uid), "social_caption")
    if why:
        raise ValueError(why)
    f = _facts(doc)
    prompt = (f"Write the caption for a short vertical gaming video that will be posted on {SOCIAL_NAMES[platform]}.\n\n"
              f"FACTS (use only these, never invent anything):\n- Title: {f['title']}\n- What happens: {f['story'] or 'not given'}\n- Game: {f['game'] or 'not given'}\n"
              f"- Credit line (must appear exactly as written): {f['credit'] or 'none'}\n" + (f"- YouTube link: {f['youtube']}\n" if platform == 'facebook' and f['youtube'] else "") +
              f"\nRULES:\n- {RULES[platform]}\n- Do not copy the title word for word. Do not use the word 'Shorts'. Do not promise anything the facts do not say.\n"
              f"- Write a different caption from this earlier one:\n{f['rules_caption'][platform]}\n\n"
              "Reply with the caption text only, no quotes, no explanation.")
    from app.engine import llm
    try:
        raw = llm.generate("social-caption", prompt, json_mode=False, timeout=45)
    except Exception as e:
        raise ValueError("The AI could not write a caption right now. Nothing was charged. Try again in a minute.") from e
    if len((raw or "").strip().strip('"')) < 10:                 # judge the AI's own answer, before the credit is added
        raise ValueError("The AI answer was empty. Nothing was charged. Try again.")
    caption = _clean(raw, platform, f)
    if len(caption) < 10:
        raise ValueError("The AI answer was empty. Nothing was charged. Try again.")
    Video.update_where(id=oid(str(doc["_id"])), fields={f"social_text.{platform}": caption})
    charged = tokens.charge_action(str(uid), "social_caption", ref=str(doc["_id"]))       # only a caption that was really written is charged
    return {"caption": caption, "charged": charged}


def reset(doc: dict, platform: str) -> None:
    """Go back to the first (rules-built) caption."""
    if platform not in SOCIAL:
        raise ValueError(f"platform must be one of {sorted(SOCIAL)}")
    Video.update_where(id=oid(str(doc["_id"])), unset=(f"social_text.{platform}",))
