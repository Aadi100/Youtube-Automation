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
from app.models import EditSource, StoryJob, System, UsageEvent, User, now, oid
from app.runtime import WORKER_ID
from app.services import token_service as tokens

MAX_QUEUE = 20
STALE_SECONDS = 900
ACTIVE = ("queued", "running")
DEFAULTS = {"daily_limit": 3, "members_video": False, "video_per_day": 16, "max_video_scenes": 8}


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
    for k, (lo, hi) in (("daily_limit", (0, 50)), ("video_per_day", (0, 200)), ("max_video_scenes", (0, 12))):
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


def estimate(script: Dict, provider: str, is_owner: bool) -> Dict:
    p = tokens.pricing()
    n = len(script["scenes"])
    vid = min(n, int(settings()["max_video_scenes"])) if provider == "veo" else 0
    mot = n - vid
    chars = sum(len(s["narration"]) for s in script["scenes"])
    total = n * p["image_flux"] + vid * p["story_scene_video"] + mot * p["story_scene_motion"] + chars / 1000.0 * p["tts_per_1k_chars"]
    return {"scenes": n, "pictures": n, "video_scenes": vid, "motion_scenes": mot, "tokens": 0 if is_owner else max(1, math.ceil(total)), "free": is_owner}


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


def make_script(uid, genre_id: str, premise: str = "", own_text: str = "", seconds: int = 40, style_id: str = "cartoon3d") -> Dict:
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
        script = SS.write(gd[1], premise, seconds, style_id, genre_id)
    charged = tokens.charge_action(str(uid), "story_script")
    return {"script": script, "charged": charged}


# ---------------------------------------------------------------- starting a story
def _check_script(script) -> Dict:
    s = SS.clean(script, str((script or {}).get("genre") or ""), str((script or {}).get("style") or "cartoon3d"))
    return s


def start(uid, script: Dict, provider: str = "motion", voice: str = "", finish: str = "open", captions: bool = True) -> Dict:
    uid = str(uid)
    owner = _owner(uid)
    s = _check_script(script)
    provs = {p["id"]: p for p in providers(owner)}
    if provider not in provs:
        raise ValueError("Choose how the scenes should move.")
    if not provs[provider]["ok"]:
        raise ValueError(provs[provider]["note"])
    if StoryJob.total(user_id=uid, status__in=list(ACTIVE)):
        raise ValueError("You already have a story being made. Wait for it to finish, or cancel it.")
    if StoryJob.total(status="queued") >= MAX_QUEUE:
        raise ValueError("Story videos are very busy right now. Try again in a few minutes.")
    st = settings()
    day = now() - timedelta(hours=24)
    if not owner:
        if StoryJob.total(user_id=uid, created_at__gte=day, status__ne="cancelled") >= int(st["daily_limit"]):
            raise ValueError(f"You can make {int(st['daily_limit'])} story video{'s' if st['daily_limit'] != 1 else ''} a day. Try again tomorrow.")
        if provider == "veo":
            used = sum(int((j.get("counts") or {}).get("video", 0)) for j in StoryJob.find_all(user_id=uid, created_at__gte=day))
            if used + min(len(s["scenes"]), int(st["max_video_scenes"])) > int(st["video_per_day"]):
                raise ValueError("You have used your AI video scenes for today. Use camera movement, or try again tomorrow.")
    from app.services import editor_service
    if editor_service.used_bytes(uid) + 400 * 1024 * 1024 > editor_service.quota_bytes():
        raise ValueError("Your editor storage is nearly full. Delete videos you no longer need in the editor, then try again.")
    est = estimate(s, provider, owner)
    reserved = 0
    if not owner and est["tokens"] > 0:
        try:
            tokens.adjust(uid, -est["tokens"], "Story video: reserved (you pay only what is used)")
            reserved = est["tokens"]
        except ValueError:
            raise ValueError(f"Not enough tokens: this story costs about {est['tokens']} and you have {tokens.balance(uid)}. Use camera movement or fewer scenes, or ask the owner for more.")
    voice = SM.voice_for(s.get("genre"), voice)
    j = StoryJob(user_id=uid, status="queued", step="Waiting in line…", pct=0, created_at=now(), script=s, provider=provider, voice=voice, finish="render" if finish == "render" else "open",
                 captions=bool(captions), reserved=reserved, estimate=est, scenes=[{"n": x["n"], "status": "waiting"} for x in s["scenes"]], counts={}, heartbeat=time.time()).save()
    return view(StoryJob.find_one(id=j.id))


# ---------------------------------------------------------------- showing and cancelling
def view(d: Dict) -> Dict:
    ahead = 0
    if d.get("status") == "queued":
        ahead = StoryJob.total(status="queued", created_at__lt=d["created_at"]) + StoryJob.total(status="running")
    return {"id": str(d["_id"]), "status": d.get("status"), "step": d.get("step") or "", "pct": int(d.get("pct") or 0), "ahead": ahead, "title": (d.get("script") or {}).get("title"),
            "provider": d.get("provider"), "scenes": d.get("scenes") or [], "estimate": d.get("estimate"), "result": d.get("result"), "charged": d.get("charged"), "error": d.get("error"),
            "created_at": d["created_at"].isoformat() if d.get("created_at") else None}


def list_for(uid, limit: int = 10) -> List[Dict]:
    return [view(d) for d in StoryJob.find_all(user_id=str(uid), order=("-created_at",), limit=limit)]


def get(uid, sid: str) -> Optional[Dict]:
    try:
        d = StoryJob.find_one(id=oid(sid))
    except Exception:
        return None
    return view(d) if d and d.get("user_id") == str(uid) else None


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
    return 0 if owner else max(0, math.ceil(total - 1e-9))


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
    sid, uid = str(d["_id"]), str(d["user_id"])
    script, provider, voice = d["script"], d.get("provider") or "motion", d.get("voice") or SM.voice_for(d["script"].get("genre"))
    work = _dir(uid, sid)
    scenes_state = [dict(x) for x in d.get("scenes") or []]
    events: List[Dict] = []
    made_sources: List[str] = []
    counts = {"video": 0, "motion": 0, "pictures": 0}
    cap = int(settings()["max_video_scenes"]) if provider == "veo" else 0
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
            st["note"] = why
            save(base + 25 / n_total, f"Scene {i + 1} of {n_total}: recording the narrator…")
            mp3 = work / f"nar_{sc['n']:02d}.mp3"
            words = SM.speak(sc["narration"], voice, mp3)
            seconds = max(float(sc["seconds"]), SM.duration(mp3) + 0.5)
            events.append({"kind": "tts", "provider": "edge-tts", "task": "story", "units": len(sc["narration"])})
            clip = work / f"clip_{sc['n']:02d}.mp4"
            kind = "motion"
            if provider == "veo" and counts["video"] < cap:
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
        project = _make_project(uid, script, made_sources, scenes_state)
        result = {"project_id": project["id"], "scenes": n_total, "video_scenes": counts["video"], "motion_scenes": counts["motion"], "synthetic": True, "realistic": bool(script.get("realistic"))}
        if d.get("finish") == "render":
            try:
                from app.services import edit_project_service as eps
                result["render_id"] = eps.enqueue(uid, project["id"], script["title"], script.get("description") or "")["id"]
            except ValueError as e:
                result["render_note"] = str(e)
        script_events = []
        used = _record(d, events + script_events)
        _refund(d, used)
        StoryJob.objects(id=d["_id"]).update_one(set__status="done", set__pct=100, set__step="Done", set__result=result, set__scenes=scenes_state, set__counts=counts, set__charged=used)
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


def _make_project(uid: str, script: Dict, source_ids: List[str], scenes: List[Dict]) -> Dict:
    from app.services import edit_project_service as eps, editor_service
    pj = eps.create(uid, script["title"][:100])
    data = ep.empty()
    data["clips"] = [{"id": f"s{n + 1}", "source": sid, "start": 0, "end": float(scenes[n].get("seconds") or 3), "fit": "crop", "captions": False} for n, sid in enumerate(source_ids)]
    data["story"] = {"synthetic": True, "realistic": bool(script.get("realistic"))}
    data["export"] = {"preset": "yt_short", "quality": "standard"}
    lib = editor_service.music_library()
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
