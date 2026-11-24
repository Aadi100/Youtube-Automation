import json
import os
from typing import Dict, List, Optional

from app.config import CONTACT_EMAIL

PLATFORM = {"twitch": "Twitch", "youtube": "YouTube"}


def format_credits(credits: List[Dict]) -> str:
    """Creator credit block: name, platform, original video link and channel link."""
    lines: List[str] = []
    seen = set()
    for c in credits or []:
        key = (c.get("creator"), c.get("video_url"))
        if key in seen:
            continue
        seen.add(key)
        head = f"• {c.get('creator') or 'Featured creator'}"
        if c.get("platform") in PLATFORM:
            head += f" ({PLATFORM[c['platform']]})"
        if c.get("title"):
            head += f' - "{c["title"]}"'
        lines.append(head)
        if c.get("channel_url"):
            lines.append(f"   Channel: {c['channel_url']}")
        if c.get("video_url"):
            lines.append(f"   Original: {c['video_url']}")
    return "\n".join(lines)


def _disclaimer(game_name: str) -> str:
    contact = (f"\nIf you are a featured creator and want a clip removed or credited differently, contact: {CONTACT_EMAIL}"
               if CONTACT_EMAIL else "")
    return f"""
========================================
Clips are shown with original commentary for commentary/entertainment purposes.
All rights belong to their respective owners ({game_name} publisher and the featured creators).{contact}
========================================
"""


def _clean_title(t: str) -> str:
    t = " ".join(str(t or "").replace("#Shorts", "").replace("#shorts", "").split()).strip(' "\'')
    return t


def generate_seo_metadata(
    video_type: str,  # 'short' or 'compilation'
    topic: str,
    streamers: Optional[List[str]] = None,
    chapters: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    game: Optional[Dict] = None,
    credits: Optional[List[Dict]] = None,
    context: str = "",
) -> Dict:
    """Title, description (hook, story, comment question, credits + links), tags and thumbnail text/scene for one video.
    `context` = what really happens in the clip (AI hook + spoken words) so the packaging is specific, never invented."""
    game = game or {}
    gname = game.get("name") or "Gaming"
    label = (game.get("thumb_label") or gname).upper()[:20]
    game_tags = [t.lstrip("#") for t in game.get("hashtags", []) if t]
    chapters_text = "\n".join(chapters) if chapters else ""
    credit_block = format_credits(credits) or "\n".join(
        f"• Featured Creator: {s}" for s in (streamers or ["Featured Gamers"]))
    who = ", ".join(streamers) if streamers else "top creators"
    detail = (context or "").strip()[:900] or topic
    if video_type == "compilation" and chapters_text:
        detail = (detail + "\nThe clips, in order:\n" + chapters_text)[:1400]

    title = tags = short_hook = thumb_headline = about = question = thumb_scene = None
    own_title = (os.environ.get("DIY_TITLE") or "").strip()      # the member wrote their own: no AI call, no tokens
    if not own_title and (api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")):
        try:
            from app.engine import llm
            n_words = "35-60" if video_type == "short" else "60-100"
            prompt = f"""You are a top YouTube growth strategist for a gaming channel about {gname}. Write the packaging for ONE {video_type.upper()}.

WHAT REALLY HAPPENS IN IT (use concrete details from this, NEVER invent events):
{detail}
Original upload title: "{topic}". Featured creator(s): {who}.

TITLES - write 5 different candidates:
- 40 to 60 characters (never more than 65).
- Lead with the most intriguing detail or strongest emotion and open a curiosity gap that the video pays off.
- Be specific (what exactly happens) instead of vague words like "insane" or "crazy" alone.
- Put the game name "{gname}" (or its everyday name) naturally in the first half, for search.
- At most ONE word in ALL CAPS, at most one emoji, no hashtags, never "you won't believe".
- Never claim anything that is not in the clip (no fake leaks, release dates or spoilers).
- Make the 5 genuinely different angles (reaction, question, shock, humour, stakes). "best" = the index (0-4) of the one most likely to get clicked.

Also write:
- "short_hook": ONE sentence under 110 characters that opens the description: the moment + a reason to watch.
- "about": {n_words} words telling what happens and why it is worth watching, natural keywords for {gname}, no hashtags, no emojis, never copy the creator's words.
- "question": ONE short question that makes viewers comment (a take, a vote, or "would you have...?").
- "tags": 12-15 search phrases people type about this ({gname}, the situation, the creator); no # characters.
- "thumb_headline": 2-4 words, ALL CAPS, max 20 characters, an emotion or curiosity trigger that is NOT the same as the title (examples of the style: "NO WAY!", "HE PANICKED", "WAIT FOR IT", "WORST MISTAKE").
- "thumb_scene": ONE sentence describing a vivid, colourful background picture that matches the moment (setting, action, mood, lighting). No text, no real people, no names.

Return ONLY a JSON object with the keys: titles (array of 5 strings), best (integer), short_hook, about, question, tags (array), thumb_headline, thumb_scene."""
            text = llm.generate("metadata", prompt, json_mode=True, timeout=90).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(text)
            titles = [_clean_title(t) for t in (data.get("titles") or []) if _clean_title(t)]
            if titles:
                best = data.get("best")
                pick = titles[best] if isinstance(best, int) and 0 <= best < len(titles) else titles[0]
                title = pick if len(pick) <= 70 else next((t for t in titles if len(t) <= 65), pick[:67].rstrip() + "...")
            elif data.get("title"):
                title = _clean_title(data["title"])
            tags = data.get("tags")
            short_hook, about, question = data.get("short_hook"), data.get("about"), data.get("question")
            thumb_headline, thumb_scene = data.get("thumb_headline"), data.get("thumb_scene")
        except Exception as e:
            print(f"[AI Metadata] AI call failed ({e}). Using templates.")

    if own_title:
        title = own_title[:90]
        about = (os.environ.get("DIY_DESCRIPTION") or "").strip()[:1500] or None
        tags = [t.strip().lstrip("#") for t in (os.environ.get("DIY_TAGS") or "").split(",") if t.strip()][:30] or None
        words = [w for w in own_title.replace("#Shorts", "").split() if w.isalnum()][:3]
        thumb_headline = (os.environ.get("DIY_THUMB_TEXT") or " ".join(words)).upper()[:20] or None

    # Fallback templates (game name filled in)
    if not title:
        if video_type == "short":
            title = f"This {gname} moment went completely wrong"
            short_hook = short_hook or f"One of the wildest {gname} moments you will see this week."
        else:
            title = f"The Craziest {gname} Moments From Top Creators"
            short_hook = short_hook or f"The best, funniest and most unexpected {gname} moments from top creators!"
    tags = [t.lstrip("#") for t in (tags or [gname, f"{gname} gameplay", f"{gname} funny moments",
                                       f"{gname} highlights", "gaming", "streamer reactions"])]
    for t in game_tags:  # the game's own hashtags always come first
        if t.lower() not in [x.lower() for x in tags]:
            tags.insert(0, t)
    if video_type == "short":
        title = f"{title} #Shorts"

    uniq, seen_tags = [], set()
    for t in game_tags + tags:  # no repeated hashtags
        k = t.replace(" ", "").lower()
        if k and k not in seen_tags:
            seen_tags.add(k)
            uniq.append(t.replace(" ", ""))
    hashtag_line = " ".join(f"#{t}" for t in uniq[:3])   # YouTube shows the first 3 hashtags above the title
    if video_type == "short":
        hashtag_line += " #Shorts"
    description_parts = [short_hook or ""]
    if about:
        description_parts += ["", about]
    if question:
        description_parts += ["", f"💬 {question}"]
    description_parts += ["", f"🔔 Subscribe for daily {gname} moments, new videos every day!", "",
                          "━━━━━━━━━━━━━━━━━━━━━━",
                          "👥 CREDITS - featured creators (please go support them!):",
                          credit_block,
                          "━━━━━━━━━━━━━━━━━━━━━━"]
    if chapters_text:
        description_parts += ["", "⏱️ TIMESTAMPS / CHAPTERS:", chapters_text, "━━━━━━━━━━━━━━━━━━━━━━"]
    description_parts += ["", _disclaimer(gname), "", hashtag_line + " " + " ".join(f"#{t}" for t in uniq[3:6])]

    return {
        "title": title[:100],
        "description": "\n".join(description_parts),
        "tags": tags,
        "thumb_headline": (thumb_headline or ("UNREAL MOMENT!" if video_type == "short" else "CAN'T BELIEVE THIS!")).upper()[:24],
        "thumb_scene": thumb_scene or "",
        "thumb_subtext": label,
        "privacy_status": "unlisted",  # always upload unlisted first to check Content ID
    }
