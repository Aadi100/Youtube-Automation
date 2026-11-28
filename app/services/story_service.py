"""Story videos: from an idea (or the member's own story) to a finished project in the editor, made in the background.

Built for many members at the same time, like the editor's render queue: every story belongs to ONE member; a story is a row in the database (any web process can show its
progress, a restart does not lose it); the WORKER service makes them, oldest first, a limited number at a time; one story per member at once; the queue has a size limit;
a member has a daily limit of stories and of AI-video scenes (the owner sets both; AI video is off for members until the owner allows it, because it costs real money per second);
the tokens are RESERVED when the story starts and what was not used comes back (a failed or cancelled story is free); files are named after their own story.

What comes out is a PROJECT in the Edit projects page (scene by scene on the timeline, with music), so the member can change anything before making the video.
The finished video is marked as AI-made, and as 'realistic' when its art style is realistic, which makes the upload tick YouTube's "altered or synthetic content" box.
"""
import math
import os
import re
import secrets
import shutil
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from app.config import BASE_DIR
from app.engine import edit_project as ep, editor, story_media as SM, story_script as SS, story_trends as ST
from app.models import AiCall, EditSource, StoryJob, System, UsageEvent, User, now, oid
from app.runtime import WORKER_ID
from app.services import token_service as tokens

MAX_QUEUE = 20
STALE_SECONDS = 900
ACTIVE = ("queued", "running")
DEFAULTS = {"daily_limit": 3, "members_video": False, "video_per_day": 16, "max_video_scenes": 8, "parts_discount": 10, "tokens_per_day": 0, "redo_per_story": 5}


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- the owner's rules
def settings() -> Dict:
    d = System.objects(id="story").first()
    s = dict(DEFAULTS)
    for k, v in ((d.to_mongo().to_dict() if d else {}) or {}).items():
        if k in DEFAULTS:
            s[k] = v
    return s


def set_settings(data: Dict) -> Dict:
    upd = {}
    for k, (lo, hi) in (("daily_limit", (0, 50)), ("video_per_day", (0, 200)), ("max_video_scenes", (0, 12)), ("parts_discount", (0, 90)), ("tokens_per_day", (0, 100000)), ("redo_per_story", (0, 50))):
        if k in data and data[k] not in (None, ""):
            try:
                v = int(data[k])
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a whole number")
            if not lo <= v <= hi:
                raise ValueError(f"{k} must be from {lo} to {hi}")
            upd[k] = v
    if "members_video" in data:
        upd["members_video"] = bool(data["members_video"])
    if upd:
        System.objects(id="story").update_one(upsert=True, **{f"set__{k}": v for k, v in upd.items()})
    return settings()


def _owner(uid) -> bool:
    u = User.find_one(id=oid(str(uid)))
    return bool(u and u.get("role") == "owner")


def providers(is_owner: bool) -> List[Dict]:
    """The ways to make the scenes move, and whether this member may use each."""
    out = [{"id": "motion", "name": "Picture with camera movement", "ok": True, "note": "Cheap and always works. The camera moves, the characters do not."}]
    st = settings()
    model = SM.veo_model()
    if not SM.veo_key():
        out.append({"id": "veo", "name": "AI video (the characters move)", "ok": False, "note": "No Gemini key is saved."})
    elif not model:
        out.append({"id": "veo", "name": "AI video (the characters move)", "ok": False, "note": "This Gemini key cannot make video (it needs a paid Google AI plan with video)."})
    elif not (is_owner or st["members_video"]):
        out.append({"id": "veo", "name": "AI video (the characters move)", "ok": False, "note": "The owner has not switched AI video on for members, because it costs real money for every second."})
    else:
        out.append({"id": "veo", "name": "AI video (the characters move)", "ok": True, "note": f"Model: {model}. The most real movement, and the most expensive."})
    return out


def music_available() -> bool:
    """True when the owner has put at least one track in the studio's music library (story videos can then have background music)."""
    from app.services import editor_service
    try:
        return bool(editor_service.music_library())
    except Exception:
        return False


def spent_today(uid) -> int:
    """Tokens a member spent (or has held) on story videos in the last 24 hours."""
    day = now() - timedelta(hours=24)
    return sum(int(j.get("charged") or 0) if j.get("status") == "done" else int(j.get("reserved") or 0)
               for j in StoryJob.find_all(user_id=str(uid), created_at__gte=day, status__in=["queued", "running", "done"]))


def estimate(script: Dict, provider: str, is_owner: bool, parts: int = 1, captions: bool = True, finish: str = "open", music: bool = True) -> Dict:
    p = tokens.pricing()
    st = settings()
    n = len(script["scenes"])
    keys = set(SS.key_scenes(script, int(st["max_video_scenes"]))) if provider == "veo" else set()
    vid = len(keys)
    mot = n - vid
    voice = p["tts_azure_per_1k_chars"] if SM.narrator_engine() == "azure" else p["tts_per_1k_chars"]
    scene_cost = [p["image_flux"] + (p["story_scene_video"] if i in keys else p["story_scene_motion"]) + len(sc["narration"]) / 1000.0 * voice for i, sc in enumerate(script["scenes"])]
    extras = (p["story_captions"] if captions else 0) + (p["story_render"] if finish == "render" else 0) + (p["story_music"] if music and music_available() else 0)
    disc = int(st["parts_discount"]) if parts > 1 else 0          # a story told in several parts costs a little less for each part
    keep = (100 - disc) / 100.0
    total = (sum(scene_cost) + extras) * keep
    return {"scenes": n, "pictures": n, "video_scenes": vid, "motion_scenes": mot, "discount": disc, "per_scene": [round(c * keep, 2) for c in scene_cost],
            "tokens": 0 if is_owner else max(1, math.ceil(total - 1e-9)), "free": is_owner}


# ---------------------------------------------------------------- trends and the script
def trends_view(force: bool = False) -> Dict:
    return ST.trends(force=force)


def make_ideas(genre_id: str) -> Dict:
    tr = ST.cached() or {}
    titles = []
    for g in tr.get("genres") or []:
        if g["id"] == genre_id:
            titles = [t["title"] for t in g.get("titles") or []]
    return {"genre": genre_id, "ideas": ST.ideas(genre_id, titles)}


def make_script(uid, genre_id: str, premise: str = "", own_text: str = "", seconds: int = 40, style_id: str = "cartoon3d", parts: int = 1) -> Dict:
    """The AI writes the story from an idea, or cuts the member's own story into scenes. Costs the script price (a member who cannot pay is told and nothing is called)."""
    gd = ST.genre(genre_id)
    if not gd:
        raise ValueError("Choose one of the listed genres.")
    why = tokens.small_shortfall(str(uid), "story_script")
    if why:
        raise ValueError(why)
    if str(own_text or "").strip():
        script = SS.split_own(own_text, seconds, style_id, genre_id)
    else:
        if len(str(premise or "").strip()) < 10:
            raise ValueError("Choose one of the ideas, or write a few words about the story you want.")
        parts = max(1, min(SS.MAX_PARTS, int(parts or 1)))
        if parts > 1:
            pr = tokens.pricing()
            extra = float(pr["story_series_extra"]) * (parts - 1)
            need = math.ceil(float(pr["story_script"]) + extra - 1e-9)
            if tokens._is_member(str(uid)) and tokens.balance(str(uid)) < need:
                raise ValueError(f"Not enough tokens: writing {parts} parts costs about {need} and you have {tokens.balance(str(uid))}. Ask the owner for more, or write fewer parts.")
            scripts = SS.write_series(gd[1], premise, parts, seconds, style_id, genre_id)
            for x in scripts:
                SS.auto_mark(x)
            charged = tokens.charge_action(str(uid), "story_script") + tokens.charge_small(str(uid), extra, "Story video: extra parts written", "story", "series", float(parts - 1))
            return {"script": scripts[0], "scripts": scripts, "charged": charged}
        script = SS.write(gd[1], premise, seconds, style_id, genre_id)
    SS.auto_mark(script)
    charged = tokens.charge_action(str(uid), "story_script")
    return {"script": script, "scripts": [script], "charged": charged}


# ---------------------------------------------------------------- starting a story
def _check_script(script) -> Dict:
    s = SS.clean(script, str((script or {}).get("genre") or ""), str((script or {}).get("style") or "cartoon3d"))
    return s


def start(uid, script: Dict, provider: str = "motion", voice: str = "", finish: str = "open", captions: bool = True, music: bool = True) -> Dict:
    return start_series(uid, [script], provider, voice, finish, captions, music)["jobs"][0]


def _first_parts(jobs: List[Dict]) -> int:
    """How many stories these jobs are for the daily limit: a story told in several parts counts once."""
    return sum(1 for j in jobs if int(((j.get("script") or {}).get("series") or {}).get("part") or 1) == 1)


def start_series(uid, scripts: List[Dict], provider: str = "motion", voice: str = "", finish: str = "open", captions: bool = True, music: bool = True) -> Dict:
    """One story, or the parts of one story: all are checked, paid for (reserved) and queued together, or none of them is."""
    uid = str(uid)
    owner = _owner(uid)
    if not isinstance(scripts, list) or not 1 <= len(scripts) <= SS.MAX_PARTS:
        raise ValueError(f"A story can have 1 to {SS.MAX_PARTS} parts.")
    cleaned = [_check_script(x) for x in scripts]
    for k, s in enumerate(cleaned, 1):
        if len(cleaned) > 1:
            s["series"] = {"title": ((scripts[k - 1] or {}).get("series") or {}).get("title") or s["title"], "part": k, "parts": len(cleaned)}
    provs = {p["id"]: p for p in providers(owner)}
    if provider not in provs:
        raise ValueError("Choose how the scenes should move.")
    if not provs[provider]["ok"]:
        raise ValueError(provs[provider]["note"])
    if StoryJob.total(user_id=uid, status__in=list(ACTIVE)):
        raise ValueError("You already have a story being made. Wait for it to finish, or cancel it.")
    if StoryJob.total(status="queued") + len(cleaned) > MAX_QUEUE:
        raise ValueError("Story videos are very busy right now. Try again in a few minutes.")
    st = settings()
    day = now() - timedelta(hours=24)
    if not owner:
        if _first_parts(StoryJob.find_all(user_id=uid, created_at__gte=day, status__ne="cancelled")) >= int(st["daily_limit"]):
            raise ValueError(f"You can make {int(st['daily_limit'])} story video{'s' if st['daily_limit'] != 1 else ''} a day. Try again tomorrow.")
        if provider == "veo":
            used = sum(int((j.get("counts") or {}).get("video", 0)) for j in StoryJob.find_all(user_id=uid, created_at__gte=day))
            if used + sum(len(SS.key_scenes(s, int(st["max_video_scenes"]))) for s in cleaned) > int(st["video_per_day"]):
                raise ValueError("You have used your AI video scenes for today. Use camera movement, or try again tomorrow.")
    from app.services import editor_service
    if editor_service.used_bytes(uid) + 400 * 1024 * 1024 * len(cleaned) > editor_service.quota_bytes():
        raise ValueError("Your editor storage is nearly full. Delete videos you no longer need in the editor, then try again.")
    ests = [estimate(s, provider, owner, len(cleaned), bool(captions), "render" if finish == "render" else "open", bool(music)) for s in cleaned]
    total = sum(e["tokens"] for e in ests)
    cap_day = int(st["tokens_per_day"])
    if not owner and cap_day > 0:                                   # the most tokens a member may spend on story videos in a day
        spent = spent_today(uid)
        if spent + total > cap_day:
            raise ValueError(f"You can spend {cap_day} tokens a day on story videos and you have used {spent} today. This story needs about {total}. Make it smaller (fewer scenes, parts or AI video) or try again tomorrow.")
    if not owner and total > 0 and tokens.balance(uid) < total:
        raise ValueError(f"Not enough tokens: this story costs about {total} and you have {tokens.balance(uid)}. Use camera movement, fewer scenes or fewer parts, or ask the owner for more.")
    made, t0, series_id = [], now(), secrets.token_hex(8)
    try:
        for i, (s, est) in enumerate(zip(cleaned, ests)):
            reserved = 0
            if not owner and est["tokens"] > 0:
                try:
                    tokens.adjust(uid, -est["tokens"], "Story video: reserved (you pay only what is used)")
                    reserved = est["tokens"]
                except ValueError:
                    raise ValueError(f"Not enough tokens: this story costs about {total} and you have {tokens.balance(uid)}. Use camera movement, fewer scenes or fewer parts, or ask the owner for more.")
            v = SM.voice_for(s.get("genre"), voice)
            j = StoryJob(user_id=uid, status="queued", step="Waiting in line…", pct=0, created_at=t0 + timedelta(milliseconds=i), script=s, provider=provider, voice=v,
                         finish="render" if finish == "render" else "open", captions=bool(captions), reserved=reserved, estimate=est, discount=int(est.get("discount") or 0), music=bool(music) and music_available(), series_id=series_id,
                         scenes=[{"n": x["n"], "status": "waiting"} for x in s["scenes"]], counts={}, heartbeat=time.time()).save()
            made.append(j)
    except Exception:
        for j in made:                                              # all or nothing: give back what was held for the parts already queued
            d = StoryJob.find_one(id=j.id)
            if d and StoryJob.objects(id=j.id, status="queued").update_one(set__status="cancelled", set__step="Cancelled"):
                _refund(d, 0)
        raise
    return {"jobs": [view(StoryJob.find_one(id=j.id)) for j in made]}


# ---------------------------------------------------------------- showing and cancelling
def view(d: Dict) -> Dict:
    ahead = 0
    if d.get("status") == "queued":
        ahead = StoryJob.total(status="queued", created_at__lt=d["created_at"]) + StoryJob.total(status="running")
    return {"id": str(d["_id"]), "status": d.get("status"), "step": d.get("step") or "", "pct": int(d.get("pct") or 0), "ahead": ahead, "title": (d.get("script") or {}).get("title"),
            "provider": d.get("provider"), "series": (d.get("script") or {}).get("series"), "scenes": d.get("scenes") or [], "estimate": d.get("estimate"), "result": d.get("result"), "charged": d.get("charged"), "receipt": d.get("receipt") or ({"lines": [], "held": int(d.get("reserved") or 0), "used": 0, "returned": int(d.get("reserved") or 0), "extra": 0, "free": False} if d.get("status") in ("error", "cancelled") else None), "error": d.get("error"),
            "created_at": d["created_at"].isoformat() if d.get("created_at") else None}


def list_for(uid, limit: int = 10) -> List[Dict]:
    return [view(d) for d in StoryJob.find_all(user_id=str(uid), order=("-created_at",), limit=limit)]


def _series_receipt(d: Dict) -> Optional[Dict]:
    """One receipt for every part of a story told in parts (shown when all the parts are finished)."""
    sid = d.get("series_id")
    if not sid:
        return None
    sibs = sorted(StoryJob.find_all(user_id=d["user_id"], series_id=sid), key=lambda x: int((((x.get("script") or {}).get("series")) or {}).get("part") or 0))
    if len(sibs) < 2:
        return None
    lines: Dict[str, Dict] = {}
    tot = {"held": 0, "used": 0, "returned": 0, "extra": 0, "later": 0.0, "discount_tokens": 0.0}
    finished = 0
    for j in sibs:
        if j.get("status") in ("done", "error", "cancelled"):
            finished += 1
        r = j.get("receipt") or ({"lines": [], "held": int(j.get("reserved") or 0), "used": 0, "returned": int(j.get("reserved") or 0)} if j.get("status") in ("error", "cancelled") else {})
        for l in r.get("lines") or []:
            x = lines.setdefault(l["label"], {"label": l["label"], "unit": l.get("unit", ""), "qty": 0, "tokens": 0.0})
            x["qty"] += l.get("qty", 0)
            x["tokens"] = round(x["tokens"] + float(l.get("tokens") or 0), 2)
        for k in tot:
            tot[k] += r.get(k, 0) or 0
    return {"parts": len(sibs), "finished": finished, "lines": list(lines.values()), **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in tot.items()}}


def get(uid, sid: str) -> Optional[Dict]:
    try:
        d = StoryJob.find_one(id=oid(sid))
    except Exception:
        return None
    if not d or d.get("user_id") != str(uid):
        return None
    v = view(d)
    v["series_receipt"] = _series_receipt(d)
    return v


def frame_path(uid, sid: str, n: int) -> Optional[Path]:
    try:
        d = StoryJob.find_one(id=oid(sid))
    except Exception:
        return None
    if not d or d.get("user_id") != str(uid):
        return None
    p = _dir(str(uid), sid) / f"kf_{int(n):02d}.png"
    return p if p.is_file() else None


def cancel(uid, sid: str) -> Optional[Dict]:
    try:
        d = StoryJob.find_one(id=oid(sid))
    except Exception:
        return None
    if not d or d.get("user_id") != str(uid):
        return None
    if StoryJob.objects(id=d["_id"], status="queued").update_one(set__status="cancelled", set__step="Cancelled"):
        _refund(d, 0)
        return view(StoryJob.find_one(id=d["_id"]))
    StoryJob.objects(id=d["_id"], status="running").update_one(set__cancel=True, set__step="Stopping…")
    return view(StoryJob.find_one(id=d["_id"]))


# ---------------------------------------------------------------- money
def _refund(d: Dict, used_tokens: int) -> None:
    reserved = int(d.get("reserved") or 0)
    back = reserved - int(used_tokens)
    if back > 0:
        try:
            tokens.adjust(d["user_id"], back, "Story video: unused tokens returned", str(d["_id"]))
        except Exception:
            pass
    elif back < 0:
        try:
            tokens.adjust(d["user_id"], back, "Story video: the rest", str(d["_id"]))
        except ValueError:
            pass


def _record(d: Dict, events: List[Dict]) -> int:
    """Write down what was really made (for the reports) and return the tokens it costs. The owner is recorded but never charged."""
    p = tokens.pricing()
    owner = _owner(d["user_id"])
    total = 0.0
    for e in events:
        c = tokens.price_event({**e, "ok": True}, p)
        total += c
        try:
            UsageEvent(user_id=str(d["user_id"]), video_id=str(d["_id"]), ok=True, cost=float(c), billed=not owner, t=now(), **e).save()
        except Exception:
            pass
    total *= (100 - int(d.get("discount") or 0)) / 100.0
    return 0 if owner else max(0, math.ceil(total - 1e-9))


def _receipt(d: Dict, events: List[Dict], used: int) -> Dict:
    """What was held, what each part cost, what was used and what came back (shown to the member like a shop receipt)."""
    p = tokens.pricing()
    owner = _owner(d["user_id"])
    names = {("image", ""): ("Pictures", "pictures"), ("tts", ""): ("Narrator voice", "characters"), ("story", "captions"): ("Captions", "parts"), ("story", "music"): ("Background music", "parts"), ("story", "render"): ("Finished video made for you", "parts"), ("story", "motion"): ("Scenes with camera movement", "scenes"), ("story", "video"): ("Scenes with AI video", "scenes")}
    lines: Dict[tuple, Dict] = {}
    for e in events:
        key = (e.get("kind"), e.get("provider") if e.get("kind") == "story" else "")
        if e.get("kind") == "tts" and e.get("provider") == "azure":
            key = ("tts", "")
        if key not in names:
            continue
        ln = lines.setdefault(key, {"label": names[key][0], "unit": names[key][1], "qty": 0, "tokens": 0.0})
        ln["qty"] += int(e.get("units") or 0)
        ln["tokens"] += tokens.price_event({**e, "ok": True}, p)
    reserved = int(d.get("reserved") or 0)
    disc = int(d.get("discount") or 0)
    return {"discount": disc, "discount_tokens": round(sum(v["tokens"] for v in lines.values()) * disc / 100.0, 2), "lines": [{**v, "tokens": round(v["tokens"], 2)} for v in lines.values()], "held": reserved, "used": int(used), "returned": max(0, reserved - int(used)), "extra": max(0, int(used) - reserved), "free": bool(owner)}


# ---------------------------------------------------------------- the worker
def _dir(uid: str, sid: str) -> Path:
    d = BASE_DIR / "inputs" / str(uid) / "story" / str(sid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def claim() -> Optional[Dict]:
    for cand in StoryJob.objects(status="queued").order_by("created_at").limit(5):
        got = StoryJob.objects(id=cand.id, status="queued").modify(new=True, set__status="running", set__worker=WORKER_ID, set__started_at=now(), set__heartbeat=time.time(), set__step="Starting…")
        if got:
            return StoryJob.find_one(id=cand.id)
    return None


def recover_stale(mine_only: bool = False) -> int:
    q = {"status": "running"}
    if mine_only:
        q["worker"] = WORKER_ID
    else:
        q["heartbeat__lt"] = time.time() - STALE_SECONDS
    n = 0
    for d in StoryJob.find_all(**q):
        if StoryJob.objects(id=d["_id"], status="running").update_one(set__status="error", set__error="The server was restarted while this story was being made. Nothing was charged. Start it again."):
            _refund(d, 0)
            n += 1
    return n


def run(d: Dict) -> None:
    AiCall.set_who(str(d["user_id"]), str(d["_id"]))               # every AI call made for this story is written under this member and story
    try:
        _run_story(d)
    finally:
        AiCall.set_who(None)


def _run_story(d: Dict) -> None:
    sid, uid = str(d["_id"]), str(d["user_id"])
    script, provider, voice = d["script"], d.get("provider") or "motion", d.get("voice") or SM.voice_for(d["script"].get("genre"))
    work = _dir(uid, sid)
    scenes_state = [dict(x) for x in d.get("scenes") or []]
    events: List[Dict] = []
    made_sources: List[str] = []
    counts = {"video": 0, "motion": 0, "pictures": 0}
    cap = int(settings()["max_video_scenes"]) if provider == "veo" else 0
    video_at = set(SS.key_scenes(script, cap))                       # only the key scenes become AI video; the rest move with the camera
    n_total = len(script["scenes"])

    def save(pct: float, step: str) -> None:
        cur = StoryJob.objects(id=d["_id"]).modify(new=True, set__pct=int(max(0, min(99, pct))), set__step=step, set__heartbeat=time.time(), set__scenes=scenes_state, set__counts=counts)
        if cur is None or cur.status != "running" or getattr(cur, "cancel", False):
            raise Cancelled()

    try:
        for i, sc in enumerate(script["scenes"]):
            base = 100.0 * i / n_total
            st = scenes_state[i]
            save(base + 1, f"Scene {i + 1} of {n_total}: drawing the picture…")
            kf = work / f"kf_{sc['n']:02d}.png"
            pic, why = SM.make_keyframe(sc, script, kf)
            if pic is None:
                pic, why = SM.make_keyframe(sc, script, kf)             # one more try (Cloudflare can be busy for a moment)
            if pic is None:
                raise RuntimeError(f"Scene {i + 1}: the picture could not be drawn. {why}")
            if not why:
                counts["pictures"] += 1
                events.append({"kind": "image", "provider": "flux", "task": "story", "units": 1})
                AiCall.log("flux", "image", "story-picture", units=1, unit="images")
            st["note"] = why
            save(base + 25 / n_total, f"Scene {i + 1} of {n_total}: recording the narrator…")
            mp3 = work / f"nar_{sc['n']:02d}.mp3"
            words = SM.speak(sc["narration"], voice, mp3, mood=sc.get("mood") or "calm")
            seconds = max(float(sc["seconds"]), SM.duration(mp3) + 0.5)
            events.append({"kind": "tts", "provider": getattr(words, "engine", "kokoro"), "task": "story", "units": len(sc["narration"])})
            AiCall.log(getattr(words, "engine", "kokoro"), "voice", "story-narration", units=len(sc["narration"]), unit="characters")
            if getattr(words, "note", ""):
                st["note"] = ((st.get("note") or "") + " " + words.note).strip()
            clip = work / f"clip_{sc['n']:02d}.mp4"
            kind = "motion"
            if provider == "veo" and i in video_at:
                save(base + 45 / n_total, f"Scene {i + 1} of {n_total}: the AI is making the video (this takes a few minutes)…")
                ok, vwhy = SM.veo_animate(kf, f"{sc['visual']}. Camera: {sc['camera']}. Smooth, natural movement of the characters. No text, no logos, no speech.", seconds, clip)
                if ok:
                    kind = "video"
                else:
                    st["note"] = (st.get("note") or "") + f" AI video did not work for this scene ({vwhy}), so camera movement was used."
            if kind == "motion":
                save(base + 55 / n_total, f"Scene {i + 1} of {n_total}: adding camera movement…")
                SM.motion_clip(kf, seconds, sc["camera"], clip)
            counts[kind] += 1
            events.append({"kind": "story", "provider": kind, "task": "story", "units": 1})
            save(base + 80 / n_total, f"Scene {i + 1} of {n_total}: putting the scene together…")
            scene_file = work / f"scene_{sc['n']:02d}.mp4"
            SM.build_scene(clip, mp3, words, seconds, scene_file, captions=bool(d.get("captions", True)))
            info = editor.probe(scene_file)
            src = EditSource(user_id=uid, title=f"{script['title'][:60]} - scene {sc['n']}", origin="generated", path=str(scene_file), created_at=now(), duration=info["duration"], width=info["width"],
                             height=info["height"], has_audio=info["has_audio"]).save()
            made_sources.append(str(src.id))
            st.update(status="done", kind=kind, source=str(src.id), seconds=round(info["duration"], 1))
            for tmp in (clip, mp3):
                tmp.unlink(missing_ok=True)
        save(96, "Building your project in the editor…")
        music_on = bool(d.get("music", True)) and music_available()
        project = _make_project(uid, script, made_sources, scenes_state, music_on)
        result = {"project_id": project["id"], "scenes": n_total, "video_scenes": counts["video"], "motion_scenes": counts["motion"], "synthetic": True, "realistic": bool(script.get("realistic"))}
        if d.get("finish") == "render":
            try:
                from app.services import edit_project_service as eps
                result["render_id"] = eps.enqueue(uid, project["id"], script["title"], script.get("description") or "")["id"]
            except ValueError as e:
                result["render_note"] = str(e)
        if d.get("captions", True):
            events.append({"kind": "story", "provider": "captions", "task": "story", "units": 1})
        if music_on:
            events.append({"kind": "story", "provider": "music", "task": "story", "units": 1})
        if result.get("render_id"):
            events.append({"kind": "story", "provider": "render", "task": "story", "units": 1})
        used = _record(d, events)
        _refund(d, used)
        StoryJob.objects(id=d["_id"]).update_one(set__status="done", set__pct=100, set__step="Done", set__result=result, set__scenes=scenes_state, set__counts=counts, set__charged=used, set__receipt=_receipt(d, events, used))
        try:
            from app.services import notification_service as notes
            notes.notify(uid, "story", "Your story video is ready", f"'{script['title']}' is in Edit projects, scene by scene. Change anything you like, then make the video.", f"#/projects/{project['id']}", "success")
        except Exception:
            pass
    except Cancelled:
        _cleanup(made_sources, work)
        _refund(d, 0)
        StoryJob.objects(id=d["_id"]).update_one(set__status="cancelled", set__step="Cancelled", set__charged=0)
    except (ValueError, RuntimeError) as e:
        _cleanup(made_sources, work)
        _refund(d, 0)
        StoryJob.objects(id=d["_id"]).update_one(set__status="error", set__error=str(e)[:300], set__step="It did not work", set__charged=0)
    except Exception as e:
        print(f"[studio] story {sid} failed: {type(e).__name__}: {str(e)[:200]}")
        _cleanup(made_sources, work)
        _refund(d, 0)
        StoryJob.objects(id=d["_id"]).update_one(set__status="error", set__error=f"The story could not be made ({type(e).__name__}). Nothing was charged.", set__step="It did not work", set__charged=0)


def _cleanup(source_ids: List[str], work: Path) -> None:
    for sid in source_ids:
        try:
            doc = EditSource.find_one(id=oid(sid))
            if doc:
                Path(doc.get("path") or "").unlink(missing_ok=True)
                EditSource.objects(id=doc["_id"]).delete()
        except Exception:
            pass
    shutil.rmtree(work, ignore_errors=True)


def redo_scene(uid, sid: str, n: int) -> Dict:
    """Make ONE picture of a finished story again (new picture, same words, same place in the project). Costs the redo price; a failed try costs nothing."""
    try:
        d = StoryJob.find_one(id=oid(sid))
    except Exception:
        d = None
    if not d or d.get("user_id") != str(uid):
        raise LookupError("story")
    n = int(n)
    st = next((x for x in d.get("scenes") or [] if int(x.get("n") or 0) == n), None)
    sc = next((x for x in (d.get("script") or {}).get("scenes") or [] if int(x.get("n") or 0) == n), None)
    if d.get("status") != "done" or not st or not sc or not st.get("source"):
        raise ValueError("Only a scene of a finished story can be made again.")
    if st.get("kind") not in ("motion", "video"):
        raise ValueError("Only a scene of a finished story can be made again.")
    video = st.get("kind") == "video"
    owner = _owner(uid)
    vprice = float(tokens.pricing().get("story_scene_video") or 0)
    if video:                                                       # a scene made by the AI video model: the same price as when it was made, and the same daily limit
        prov = {x["id"]: x for x in providers(owner)}.get("veo")
        if not prov or not prov["ok"]:
            raise ValueError((prov or {}).get("note") or "AI video is not available.")
        if not owner:
            day = now() - timedelta(hours=24)
            used = sum(int((j.get("counts") or {}).get("video", 0)) for j in StoryJob.find_all(user_id=str(uid), created_at__gte=day)) + UsageEvent.total(user_id=str(uid), kind="story", provider="redo_video", t__gte=day)
            if used + 1 > int(settings()["video_per_day"]):
                raise ValueError("You have used your AI video scenes for today. Try again tomorrow.")
            if vprice > 0 and tokens.balance(str(uid)) < math.ceil(vprice - 1e-9):
                raise ValueError(f"Not enough tokens: an AI video scene costs {vprice:g} and you have {tokens.balance(str(uid))}. Ask the owner for more.")
    cap = int(settings()["redo_per_story"])
    if int(d.get("redos") or 0) >= cap:
        raise ValueError(f"You can make pictures again {cap} time{'s' if cap != 1 else ''} for one story.")
    why = None if video else tokens.small_shortfall(str(uid), "story_redo_scene")
    if why:
        raise ValueError(why)
    work = _dir(str(uid), sid)
    kf, new = work / f"kf_{n:02d}.png", work / f"kf_{n:02d}_new.png"
    pic, why = SM.make_keyframe(sc, d["script"], new)
    if pic is None or why:
        new.unlink(missing_ok=True)
        raise ValueError(f"The picture could not be made again. {why or ''} Nothing was charged.".replace("  ", " "))
    AiCall.log("flux", "image", "story-picture", units=1, unit="images", user_id=str(uid), ref=sid)
    mp3, clip, tmp = work / f"nar_{n:02d}.mp3", work / f"clip_{n:02d}.mp4", work / f"scene_{n:02d}_new.mp4"
    try:
        words = SM.speak(sc["narration"], d.get("voice") or SM.voice_for(d["script"].get("genre")), mp3, mood=sc.get("mood") or "calm")
        AiCall.log(getattr(words, "engine", "kokoro"), "voice", "story-narration", units=len(sc["narration"]), unit="characters", user_id=str(uid), ref=sid)
        seconds = max(float(st.get("seconds") or sc["seconds"]), SM.duration(mp3) + 0.5)
        if video:
            ok, vwhy = SM.veo_animate(new, f"{sc['visual']}. Camera: {sc['camera']}. Smooth, natural movement of the characters. No text, no logos, no speech.", seconds, clip, wait=420)
            if not ok:
                raise ValueError(f"The AI video could not be made again ({vwhy}). Nothing was charged.")
        else:
            SM.motion_clip(new, seconds, sc["camera"], clip)
        SM.build_scene(clip, mp3, words, seconds, tmp, captions=bool(d.get("captions", True)))
        os.replace(tmp, work / f"scene_{n:02d}.mp4")
        os.replace(new, kf)
        info = editor.probe(work / f"scene_{n:02d}.mp4")
        EditSource.objects(id=st["source"]).update_one(set__duration=info["duration"])
    finally:
        for f in (new, clip, mp3, tmp):
            f.unlink(missing_ok=True)
    if video:
        price = 0.0 if owner else vprice
        tokens.charge_small(str(uid), vprice, "Story video: an AI video scene made again", "story", "redo_video", 1.0, sid)
    else:
        price = 0.0 if owner else float(tokens.pricing().get("story_redo_scene") or 0)
        tokens.charge_action(str(uid), "story_redo_scene", sid)
    r = dict(d.get("receipt") or {})
    lines = [dict(x) for x in r.get("lines") or []]
    ln = next((x for x in lines if x.get("label") == "Scenes made again"), None)
    if ln is None:
        ln = {"label": "Scenes made again", "unit": "scenes", "qty": 0, "tokens": 0.0}
        lines.append(ln)
    ln["qty"] += 1
    ln["tokens"] = round(ln["tokens"] + price, 2)
    r["lines"], r["later"] = lines, round(float(r.get("later") or 0) + price, 2)
    StoryJob.objects(id=d["_id"]).update_one(inc__redos=1, set__receipt=r)
    return view(StoryJob.find_one(id=d["_id"]))


def _make_project(uid: str, script: Dict, source_ids: List[str], scenes: List[Dict], music: bool = True) -> Dict:
    from app.services import edit_project_service as eps, editor_service
    pj = eps.create(uid, script["title"][:100])
    data = ep.empty()
    cycle = ["dissolve", "fade", "dissolve", "slideleft"]          # a smooth cut between scenes, a quick slide now and then, so it is not one hard cut after another
    data["clips"] = [{"id": f"s{n + 1}", "source": sid, "start": 0, "end": float(scenes[n].get("seconds") or 3), "fit": "crop", "captions": False,
                      "transition": {"type": cycle[n % len(cycle)] if n else "none", "duration": 0.3},
                      "look": {"preset": "cinematic", "brightness": 0, "contrast": 1, "saturation": 1}} for n, sid in enumerate(source_ids)]
    data["story"] = {"synthetic": True, "realistic": bool(script.get("realistic"))}
    data["export"] = {"preset": "yt_short", "quality": "standard"}
    lib = editor_service.music_library() if music else []
    if lib:
        data["audio"] = {"music": {"ref": lib[sum(map(ord, script["title"])) % len(lib)]["ref"], "start": 0, "volume": 0.14, "fade_in": 1, "fade_out": 2, "loop": True, "duck": True}}
    return eps.save(uid, pj["id"], pj["version"], script["title"][:100], data)


def worker_loop() -> None:
    idle = 0.0
    while True:
        try:
            d = claim()
            if d:
                run(d)
                continue
            if time.time() - idle > 60:
                idle = time.time()
                recover_stale()
        except Exception as e:
            print(f"[studio] story queue error: {type(e).__name__}: {str(e)[:150]}")
            time.sleep(5)
        time.sleep(3)


def start_workers() -> None:
    recover_stale(mine_only=True)
    try:
        n = max(1, int(os.environ.get("STORY_WORKERS") or 1))
    except ValueError:
        n = 1
    for _ in range(n):
        threading.Thread(target=worker_loop, daemon=True).start()
