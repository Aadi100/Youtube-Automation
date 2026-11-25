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
    extra_examples: Optional[List[str]] = None,
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
    if not own_title and (api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        try:
            from app.engine import llm
            n_words = "35-60" if video_type == "short" else "60-100"
            from app.engine import title_style as TS
            from app.services import lab_service as LAB
            lab_titles = LAB.examples_for_prompt("title") + list(extra_examples or [])          # the owner's own liked titles (Learning Lab, when on)
            lab_desc = LAB.examples_for_prompt("description", 4)
            desc_block = ("How this channel's descriptions sound (copy the voice, never the words):" + chr(10) + chr(10).join("- " + d for d in lab_desc) + chr(10) + chr(10)) if lab_desc else ""
            prompt = f"""You write the YouTube title and description for ONE {video_type.upper()} on a channel about {gname}. People see the title and thumbnail in a feed and decide in one second.

WHAT REALLY HAPPENS (facts you may use; NEVER invent events, names, numbers or quotes):
{detail}
The original upload was called: "{topic}" (use it only for facts, do not copy its words). Creator: {who} (viewers do not know this name, so it does not belong in the title).

TITLES: write 10 different ones. For each give "style" and "score" (1-10, an honest guess of how much a stranger would want to click).
- 35 to 58 characters. One clear moment and one specific detail (an object, a number, a line, a place), written the way a person would say it, not like a news report.
- Open a question in the viewer's head that the video answers. Show the stakes, the reaction or the twist, but do not give away the ending.
- Mix these styles: "question", "reaction" (what the player did or said), "stakes" (what could go wrong), "contrast" (what was expected vs what happened), "pov", "wait" (builds anticipation).
- Not allowed: insane, crazy, unbelievable, epic, wild, chaos, goes feral, "you won't believe", "must watch", "best ever", hashtags, more than one emoji, more than one ALL-CAPS word, the creator's name.
- The game name "{gname}" (or its everyday name) may appear in some titles, only where it sounds natural, and not always in the same place.
- Never claim anything that is not in the clip (no fake leaks, release dates or spoilers).
- The clip belongs to another creator. Write about the player from the outside ("He...", "She...", "They...", or a question to the viewer). NEVER as the player: no "I", "my", "me", "we", "our".
Feel of titles that work (copy the feel, never the words):
{TS.examples_block(lab_titles)}

{desc_block}DESCRIPTION
- "short_hook": ONE sentence under 110 characters. It is the first thing read in search, so it must state the moment clearly on its own. Written about the player from the outside, never as "I" or "we".
- "about": {n_words} words in plain, natural speech: what happens, in order, with the concrete details. No filler such as "worth watching", "watch to see", "in this clip", "a clip where", "the chaos", "hilarious". No hashtags, no emojis. Do not repeat the hook word for word and never copy the creator's own words.
- "question": ONE short question that is specific to this moment and easy to answer in a comment (a choice, a vote, or "would you have...?").
- "tags": 12-15 search phrases people type about this ({gname}, the situation, the creator); no # characters.
- "thumb_headline": 2-4 words, ALL CAPS, max 20 characters, an emotion or curiosity trigger that is NOT the same as the title (style: "NO WAY!", "HE PANICKED", "WAIT FOR IT", "WORST MISTAKE").
- "thumb_scene": ONE sentence describing a vivid, colourful background picture that matches the moment (setting, action, mood, lighting). No text, no real people, no names.

Return ONLY a JSON object with the keys: titles (array of 10 objects {{"t": "...", "style": "...", "score": 7}}), short_hook, about, question, tags (array), thumb_headline, thumb_scene."""
            text = llm.generate("metadata", prompt, json_mode=True, timeout=90).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(text)
            picked, rows = TS.pick_title(data.get("titles") or ([data["title"]] if data.get("title") else []), streamers, gname, bonus=LAB.title_bonus_fn())
            LAB.log("title", {"picked": picked, "rows": [{k: r.get(k) for k in ("title", "style", "rules", "ai", "lab", "total")} for r in rows[:10]]})
            if picked:
                title = picked if len(picked) <= 70 else picked[:67].rstrip() + "..."
                print("[AI Metadata] titles: " + " | ".join(f"{r['total']} {r['title']}" for r in rows[:4]), flush=True)
            tags = data.get("tags")
            short_hook, about, question = TS.clean_hook(data.get("short_hook") or ""), TS.clean_about(data.get("about") or ""), data.get("question")
            if not short_hook and about:                        # the hook was filler: the first sentence of the story takes its place
                first = about.replace("\n", " ").split(". ")[0].strip(". ")
                short_hook = (first + ".")[:140]
            thumb_headline, thumb_scene = data.get("thumb_headline"), data.get("thumb_scene")
            LAB.log("description", {"hook": short_hook, "about": about, "question": question})
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
