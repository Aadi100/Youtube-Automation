"""Views (the V of MVC): how models are presented to the browser as JSON."""
import re
from pathlib import Path

from app.models import Clip, UserPrefs, clean
from app.services import auth_service as auth


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


def _vid(doc: dict) -> dict:
    out = clean(doc)
    out["twitch"] = {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                     for k, v in (doc.get("twitch") or {"status": "pending"}).items()}
    out["twitch_pack"] = twitch_pack(doc)
    out["file_mb"] = round(Path(doc.get("video_path", "")).stat().st_size / 1e6, 1) if Path(doc.get("video_path", "")).is_file() else None
    return out


def _utc_iso(dt):
    if not dt:
        return None
    from datetime import timezone as dtz
    return (dt.replace(tzinfo=dtz.utc) if dt.tzinfo is None else dt).isoformat()


def _job_view(j, games_by_id, videos_by_id):
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
            "last_line": last[:160], "error": (j.get("error") or "")[:200] or None,
            "video": ({"id": str(vid["_id"]), "title": vid.get("title"), "status": vid.get("status"),
                       "youtube_url": vid.get("youtube_url")} if vid else None)}


def _me(u: dict) -> dict:
    p = UserPrefs.of(u["_id"])
    return {**auth.public(u), "prefs": {"tts_voice": p.get("tts_voice", ""), "default_audio": p.get("default_audio", ""), "notify_to": p.get("notify_to", "")}}
