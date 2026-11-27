"""Views (the V of MVC): how models are presented to the browser as JSON."""
import re
from pathlib import Path

from app.models import Clip, UserPrefs, clean
from app.services import auth_service as auth
from app.views.progress import friendly_error, job_progress


def _clipping_payload(uid) -> dict:
    from app.engine import clipcfg
    cfg = clipcfg.load(uid)
    return {"config": cfg, "types": [{"id": t[0], "name": t[1], "desc": t[2]} for t in clipcfg.TYPES],
            "criteria": clipcfg.criteria_text(cfg), "bank": Clip.bank_size(uid)}


def twitch_pack(d: dict) -> dict:
    """Title + description trimmed and cleaned for a manual Twitch upload (no #hashtags, short)."""
    title = re.sub(r"\s*#\w+", "", d.get("title") or "").strip()[:140]
    desc = d.get("description") or ""
    tail = "Clips shown with original commentary. All rights belong to their owners."
    head = desc.split("\n", 1)[0].strip()
    credit_lines, used = [], len(head) + len(tail) + 40
    seen = set()
    for c in d.get("credits") or []:
        name = c.get("creator")
        if not name or name in seen:
            continue
        seen.add(name)
        line = f"{name}: {c['channel_url']}" if c.get("channel_url") else name
        if used + len(line) + 1 > 500:
            break
        credit_lines.append(line)
        used += len(line) + 1
    parts = [head, "Credits:\n" + "\n".join(credit_lines) if credit_lines else "", tail]
    tags = [t.lstrip("#") for t in re.findall(r"#\w+", desc)][:10]
    return {"title": title, "description": "\n\n".join(p for p in parts if p)[:500],
            "category": d.get("game_name") or "", "tags": tags}


SOCIAL = ("tiktok", "instagram", "facebook")
SOCIAL_NAMES = {"tiktok": "TikTok", "instagram": "Instagram Reels", "facebook": "Facebook Reels"}
SOCIAL_HOSTS = {"tiktok": ("tiktok.com",), "instagram": ("instagram.com",), "facebook": ("facebook.com", "fb.watch", "fb.com")}
SOCIAL_OPEN = {"tiktok": "https://www.tiktok.com/upload", "instagram": "https://www.instagram.com/", "facebook": "https://www.facebook.com/reels/create"}
SOCIAL_STATUSES = {"pending", "posted", "skipped"}


def _tag(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(text or ""))[:30]


def _tags(*groups, limit: int) -> list:
    """Hashtags without repeats (ignoring case), in the order given, at most `limit`."""
    out, seen = [], set()
    for g in groups:
        for t in g:
            t = _tag(t)
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append("#" + t)
            if len(out) >= limit:
                return out
    return out


def social_pack(d: dict) -> dict:
    """One caption per platform for a manual post, each written the way that platform is read: TikTok short and punchy, Instagram a hook, a line of story and
    hashtags, Facebook friendly with a question and the YouTube link. Built from the video's own title, description and credits (no AI call, no cost)."""
    title = re.sub(r"\s*#\w+", "", d.get("title") or "").strip()
    desc = d.get("description") or ""
    head = next((ln.strip() for ln in desc.split("\n") if ln.strip() and not ln.strip().startswith("#")), "")
    head = re.sub(r"\s*#\w+", "", head).strip()
    if head.lower() == title.lower():
        head = ""
    game = d.get("game_name") or ""
    own = [t for t in re.findall(r"#(\w+)", desc) if t.lower() not in ("shorts", "short", "youtubeshorts")]
    names, seen = [], set()
    for c in d.get("credits") or []:
        n = (c.get("creator") or "").strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            names.append(n)
    credit = ("Clip by " + ", ".join(names[:3])) if names else ""
    yt = d.get("youtube_url") or (f"https://youtu.be/{d['youtube_id']}" if d.get("youtube_id") else "")

    tt = _tags([game], own[:3], ["gaming", "gamingclips"], limit=5)
    tiktok = "\n".join(x for x in [title[:110], credit, " ".join(tt)] if x)[:300]

    ig_tags = _tags([game], own, ["gaming", "gamer", "reels", "gamingreels", "clips", "funny"], limit=8)
    insta = "\n\n".join(x for x in [title, head, (f"Follow for more {game} moments." if game else "Follow for more gaming moments."), credit, " ".join(ig_tags)] if x)[:2200]

    fb_tags = _tags([game], limit=2)
    fb = "\n\n".join(x for x in [title, head, "What would you have done? Tell us in the comments.", (f"Watch the full video on YouTube: {yt}" if yt else ""), credit,
                                "All rights belong to the original creators and owners.", " ".join(fb_tags)] if x)[:2200]
    return {"tiktok": tiktok, "instagram": insta, "facebook": fb}


def _vid(doc: dict, owner: bool = False, permitted=None) -> dict:
    out = clean(doc)
    try:                                                            # the reused-content risk (plain rules; the member's permission records lower it)
        from app.engine import risk
        if permitted is None and doc.get("user_id"):
            from app.services import permission_service
            permitted = permission_service.allowed_map(doc["user_id"])
        out["risk"] = risk.assess(doc, permitted or {})
    except Exception:
        out["risk"] = None
    if not owner:                       # members see what was done and what it cost, never which service did it
        from app.services import token_service
        if out.get("receipt") is not None:
            out["receipt"] = token_service.member_receipt(out["receipt"])
    out["twitch"] = {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                     for k, v in (doc.get("twitch") or {"status": "pending"}).items()}
    out["twitch_pack"] = twitch_pack(doc)
    try:
        from app.services import analytics_service
        out["results"] = analytics_service.view(doc)          # what YouTube says happened to it (None until the member allowed Analytics and a day has passed)
    except Exception:
        out["results"] = None
    sc = doc.get("social") or {}
    out["social"] = {p: {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (sc.get(p) or {"status": "pending"}).items()} for p in SOCIAL}
    out["social_pack"] = {**social_pack(doc), **{p: t for p, t in (doc.get("social_text") or {}).items() if p in SOCIAL and t}}
    out["social_ai"] = {p: True for p, t in (doc.get("social_text") or {}).items() if p in SOCIAL and t}       # these captions were written by the AI
    out["file_mb"] = round(Path(doc.get("video_path") or "").stat().st_size / 1e6, 1) if Path(doc.get("video_path") or "").is_file() else None
    return out


def _utc_iso(dt):
    if not dt:
        return None
    from datetime import timezone as dtz
    return (dt.replace(tzinfo=dtz.utc) if dt.tzinfo is None else dt).isoformat()


def _job_view(j, games_by_id, videos_by_id, owner=False):
    log = [str(x) for x in (j.get("log") or [])]
    game = next((m[1].strip() for m in (re.match(r"\[Game\]\s*(.+)", l) for l in log) if m), None)
    vid = videos_by_id.get(str(j.get("video_id") or ""))
    gid = (j.get("params") or {}).get("game_id")
    if not game and vid:
        game = vid.get("game_name")
    if not game and gid and gid != "auto":
        game = (games_by_id.get(gid) or {}).get("name", gid)
    last = next((l for l in reversed(log) if l.strip()), "")
    return {"id": str(j["_id"]), "mode": j.get("mode"), "kind": "compilation" if "compilation" in str(j.get("mode")) else "short",
            "scheduled": j.get("source") == "n8n", "status": j.get("status"), "game": game,
            "started": _utc_iso(j.get("created_at")), "finished": _utc_iso(j.get("finished_at")),
            "last_line": last[:160] if owner else job_progress(j)["message"], "error": ((j.get("error") or "")[:200] or None) if owner else friendly_error(j.get("error")),
            "video": ({"id": str(vid["_id"]), "title": vid.get("title"), "status": vid.get("status"),
                       "youtube_url": vid.get("youtube_url")} if vid else None)}


def _me(u: dict) -> dict:
    p = UserPrefs.of(u["_id"])
    from app.services import profile_service
    return {**auth.public(u), "avatar": profile_service.has_avatar(u["_id"]), "prefs": {"tts_voice": p.get("tts_voice", ""), "default_audio": p.get("default_audio", ""), "notify_to": p.get("notify_to", ""), "hold_uploads": bool(p.get("hold_uploads")), "tour": p.get("tour", "")}}
