from app.models import Claim, Clip, Game, Video, now
import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.engine.ai_metadata import generate_seo_metadata
from app.engine.audio_shield import build_audio
from app.config import INPUT_DIR, OUTPUT_DIR, TEMP_DIR
from app.engine.subtitles import transcribe_audio_to_words
from app.engine.thumbnail_generator import generate_thumbnail
from app.engine.video_processor import (
    create_compilation, get_video_info, make_short_blurred, make_short_split,
)

MANIFEST = OUTPUT_DIR / "last_run.json"
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}


def resolve(game_id: Optional[str]) -> Dict:
    """Game for this run. Falls back to the built-in default only if MongoDB is unreachable."""
    try:
        Game.ensure_default()  # first run: seed the starter game
        game = Game.resolve(game_id)
        Game.touch(game["id"])
        return game
    except ValueError:
        raise
    except Exception as e:
        print(f"[Warning] MongoDB unavailable ({e}); using the built-in default game.")
        return Game.default_data()


def credit_for(c: Dict) -> Dict:
    return {"creator": c.get("streamer"), "title": c.get("title"), "platform": c.get("source"),
            "video_url": c.get("url"), "channel_url": c.get("channel_url")}


def _write_manifest(data: Dict) -> Dict:
    """Save the render to MongoDB and to last_run.json (title/description/tags/paths ready for upload)."""
    try:
        data["video_id"] = Video.save_manifest(data, job_id=os.environ.get("CLIPSTUDIO_JOB_ID"))
    except Exception as e:  # the render is done; a DB outage must not lose it
        data["video_id"] = None
        print(f"[Warning] Could not save to MongoDB: {e}")
    target = Path(os.environ.get("CLIPSTUDIO_MANIFEST") or MANIFEST)   # the server gives every job its own manifest file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"MANIFEST: {target}")
    return data


def _manifest(kind: str, video: Path, thumb: Path, meta: Dict, audio_mode: str, clip_ids: List[str],
              game: Dict, credits: List[Dict]) -> Dict:
    return {
        "kind": kind,
        "video_path": str(video),
        "thumbnail_path": str(thumb),
        "title": meta["title"],
        "description": meta["description"],
        "tags": meta["tags"],
        "privacy_status": meta["privacy_status"],
        "audio_mode": audio_mode,
        "clip_ids": clip_ids,
        "game_id": game.get("id"),
        "game_name": game.get("name"),
        "credits": credits,
        "thumb_style": __import__("app.engine.thumbnail_generator", fromlist=["x"]).LAST.get("style"),
        "content_type": meta.get("content_type"),
        "thumb_recipe": __import__("app.engine.thumbnail_generator", fromlist=["x"]).LAST.get("recipe"),
        "thumb_tier": __import__("app.engine.thumbnail_generator", fromlist=["x"]).LAST.get("tier"),
    }


def _usage(kind: str, provider: str, units: float = 1.0) -> None:
    """Write down one thing this run used (priced and charged when the job is settled; failed jobs are never charged). Never raises."""
    try:
        from app.models import UsageEvent
        UsageEvent.record(kind, provider=provider, task=kind, units=units)
    except Exception:
        pass


def _bill_finding(found, mode: str, own: bool) -> None:
    """Finding the clip is used by every automatic run (a clip the member gave themselves is not searched for); a YouTube clip costs a little extra."""
    if own or not found:
        return
    _usage("search", "studio", 1)
    for plat in ("youtube", "twitch", "kick"):                  # every clip found is paid for by the place it was found
        n = sum(1 for c in found if (c.get("source") or "") == plat)
        if n:
            _usage("source", plat, n)


def _bill_trend(mode: str) -> None:
    """Trending mode was used (it really ranked candidates): its fee is recorded and charged when the video is made."""
    from app.engine import trending
    if trending.used():
        _usage("trend", "compilation" if "compilation" in mode else "short", 1)


def _bill_render(mode: str) -> None:
    _usage("render", "compilation" if "compilation" in mode else "short", 1)
    _usage("server", "", 1)                                       # the server's share of every video (also a video made from the member's own clip)


def _auto_cam_crop(video: Path, default: str) -> str:
    """The rectangle around the streamer's face camera for the split layout (face on top, game below), found with the face finder.
    Falls back to `default` (the old fixed guess) when there is no steady face or the finder is not available."""
    try:
        import cv2
        from app.engine import face_signals
        cap = cv2.VideoCapture(str(video))
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        dur = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / (cap.get(cv2.CAP_PROP_FPS) or 30.0)
        cap.release()
        box = face_signals.find_face_box(video, dur) if dur else None
        crop = face_signals.webcam_crop(box, w, h) if box else None
        if crop:
            print(f"[Faces] face camera found: crop {crop} (instead of the fixed guess)", flush=True)
            return crop
    except Exception as e:
        print(f"[Faces] face camera search skipped ({str(e)[:80]})", flush=True)
    return default


def run_short_pipeline(
    input_video: Path,
    layout: str = "blur",
    cam_crop: str = "0:0:640:360",
    with_subtitles: bool = True,
    streamer_name: str = "Streamer",
    topic: str = "Livestream Highlight",
    audio_mode: str = "replace",
    clip_ids: Optional[List[str]] = None,
    game: Optional[Dict] = None,
    credits: Optional[List[Dict]] = None,
    hook: str = "",
    remix: Optional[Dict] = None,
    context: str = "",
) -> Dict:
    game = game or Game.default_data()
    print(f"\n=== SHORTS PIPELINE [{game['name']}]: {input_video.name} (audio: {audio_mode}) ===")
    if layout == "split" and cam_crop == "0:0:640:360":       # the built-in default is a guess: look for the real face camera
        cam_crop = _auto_cam_crop(input_video, cam_crop)

    # Audio shield first: it may supply the captions (commentary words) too.
    transcript = ""
    if audio_mode == "replace":
        transcript = " ".join(w["word"].strip() for w in transcribe_audio_to_words(input_video, TEMP_DIR))
    audio_path, words, audio_used = build_audio(
        input_video, audio_mode, input_video.stem, transcript, streamer_name, topic, game["name"], context=context)

    kwargs = dict(input_video=input_video, with_subtitles=with_subtitles,
                  audio_path=audio_path, words=words)
    rendered = (make_short_split(cam_crop=cam_crop, **kwargs) if layout == "split"
                else make_short_blurred(**kwargs))

    credits = credits or [{"creator": streamer_name}]
    if remix:    # the video keeps its own title, description and thumbnail: no new AI text, no new image
        meta = {"title": remix.get("title") or "", "description": remix.get("description") or ""}
    else:
        meta = generate_seo_metadata(video_type="short", topic=topic, streamers=[streamer_name], context=f"{hook}. What was said: {transcript[:700]}. {context[:700]}".strip(". "),
                                     game=game, credits=credits)
    from app.engine.safety import check_final_video
    ok, why = check_final_video(rendered, meta.get("title", ""), meta.get("description", ""))
    if not ok:
        raise SystemExit(f"Blocked by the content-safety check: {why}")
    print(f"[Safety] final video: {why}")
    if remix:
        return _finish_remix(remix, rendered, audio_used)
    from app.engine import content_ai
    ctype, _conf = content_ai.classify(topic, hook, transcript[:900], meta.get("title", ""))
    meta["content_type"] = ctype
    thumb = generate_thumbnail(video_path=input_video, art_stem=rendered, output_path=rendered.with_name(f"{rendered.stem}_9x16_thumb.jpg"), headline=meta["thumb_headline"],
                               subtext=meta["thumb_subtext"], mode="9:16", game_name=game.get("name"), scene=meta.get("thumb_scene", ""), content_type=ctype,
                               context={"title": meta.get("title", ""), "hook": hook or topic, "topic": topic})

    meta_file = rendered.with_suffix(".json")
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Short: {rendered}\nCover: {thumb}\nMeta:  {meta_file}")
    return _write_manifest(_manifest("short", rendered, thumb, meta, audio_used, clip_ids or [], game, credits))


def _finish_remix(doc: Dict, rendered: Path, audio_used: str) -> Dict:
    """The remade file replaces the old one on the same video (same title, description, thumbnail, same place in the library)."""
    old = doc.get("video_path")
    Video.update_where(id=doc["_id"], fields={"video_path": str(rendered), "audio_mode": audio_used, "remade_at": now()}, unset=("remix_error",))
    if old and Path(old).resolve() != Path(rendered).resolve():
        Path(old).unlink(missing_ok=True)
    data = {"video_id": str(doc["_id"]), "kind": doc.get("kind"), "video_path": str(rendered), "audio_mode": audio_used}
    target = Path(os.environ.get("CLIPSTUDIO_MANIFEST") or MANIFEST)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"MANIFEST: {target}")
    return data


def run_remix(video_id: str, audio_mode: str) -> Dict:
    """Make an existing, not yet uploaded video again with different audio (AI commentary + music, original audio, or original under music),
    from the clips it was made of. Title, description and thumbnail stay as they are."""
    from app.engine.safety import check_final_video
    from app.models import oid
    doc = Video.find_one(id=oid(video_id))
    if not doc:
        raise SystemExit("That video no longer exists.")
    if doc.get("youtube_id"):
        raise SystemExit("This video is already on YouTube, so its audio can no longer be changed.")
    print(f"[Remix] start: new audio '{audio_mode}' for '{(doc.get('title') or '')[:60]}'", flush=True)
    clips = [c for c in (Clip.find_one(id=cid) for cid in (doc.get("clip_ids") or [])) if c]
    if not clips or any(not c.get("path") or not Path(c["path"]).is_file() for c in clips):
        raise SystemExit("The original clip files were already cleaned up, so the audio cannot be changed. Make a new video instead.")
    game = Game.get_for(doc.get("game_id")) or {"id": doc.get("game_id"), "name": doc.get("game_name") or "Gaming"}
    if doc.get("kind") == "short":
        c = clips[0]
        return run_short_pipeline(Path(c["path"]), "blur", "0:0:640:360", True, c.get("streamer") or "Streamer", c.get("title") or doc.get("title") or "Clip",
                                  audio_mode, doc.get("clip_ids"), game=game, credits=doc.get("credits"), hook="", remix=doc)
    chosen = [{**c, "path": Path(c["path"]), "views": c.get("views", 0)} for c in sorted(clips, key=lambda c: c.get("views", 0), reverse=True)]
    print(f"\n=== COMPILATION PIPELINE [{game['name']}]: remaking '{doc.get('title')}' (audio: {audio_mode}) ===", flush=True)
    result = create_compilation(clips=chosen, compilation_title=doc.get("title") or "Compilation", audio_mode=audio_mode, game_name=game["name"])
    ok, why = check_final_video(result["video_path"], doc.get("title") or "", doc.get("description") or "")
    if not ok:
        raise SystemExit(f"Blocked by the content-safety check: {why}")
    print(f"[Safety] final video: {why}", flush=True)
    return _finish_remix(doc, Path(result["video_path"]), audio_mode)


def _clips_from_dir(input_dir: Path) -> List[Dict]:
    clips = []
    for idx, f in enumerate(sorted(p for p in input_dir.iterdir() if p.suffix.lower() in VIDEO_EXT), 1):
        parts = f.stem.split(" - ", 1)
        streamer, title = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (
            f"Creator_{idx}", f.stem.replace("_", " ").title())
        clips.append({"path": f, "title": title, "streamer": streamer, "views": 0})
    return clips


def run_compilation_pipeline(
    clips: List[Dict],
    compilation_title: str = "",
    topic: Optional[str] = None,
    audio_mode: str = "replace",
    target_minutes: float = 8.0,
    max_minutes: float = 10.5,
    clip_ids: Optional[List[str]] = None,
    game: Optional[Dict] = None,
) -> Dict:
    game = game or Game.default_data()
    compilation_title = compilation_title or f"{game['name']} Best Streamer Moments"
    print(f"\n=== COMPILATION PIPELINE [{game['name']}]: '{compilation_title}' (audio: {audio_mode}) ===")
    if not clips:
        raise FileNotFoundError("No clips to compile")

    # Best clips first, stop once we are inside the 8-10 minute window.
    ranked = sorted(clips, key=lambda c: c.get("views", 0), reverse=True)
    chosen, total = [], 0.0
    for c in ranked:
        d = get_video_info(Path(c["path"]))["duration"]
        if total + d > max_minutes * 60:
            continue
        chosen.append(c)
        total += d
        if total >= target_minutes * 60:
            break
    if total < target_minutes * 60:
        print(f"[Warning] Only {total/60:.1f} min of footage (< {target_minutes} min). "
              "Download more clips or lower --target-minutes.")

    result = create_compilation(clips=chosen, compilation_title=compilation_title,
                                audio_mode=audio_mode, game_name=game["name"])
    video_path = result["video_path"]
    streamers = sorted({c["streamer"] for c in chosen})
    credits = [credit_for(c) for c in chosen]

    meta = generate_seo_metadata(video_type="compilation", topic=topic or compilation_title,
                                 streamers=streamers, chapters=result["chapters"], game=game, credits=credits)
    thumb = generate_thumbnail(video_path=video_path, art_stem=video_path, headline=meta["thumb_headline"],
                               subtext=meta["thumb_subtext"], mode="16:9", game_name=game.get("name"), scene=meta.get("thumb_scene", ""))

    meta_file = video_path.with_suffix(".json")
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Video: {video_path} ({total/60:.1f} min)\nThumb: {thumb}\nMeta:  {meta_file}")
    ids = clip_ids if clip_ids is not None else [c["clip_id"] for c in chosen if "clip_id" in c]
    return _write_manifest(_manifest("compilation", video_path, thumb, meta, audio_mode, ids, game, credits))


def own_clip(url: str, start: float, end: float, game: Dict) -> Dict:
    """The member chose the clip: a YouTube link plus the part they want (15-58 s). No search, no AI scoring, no AI moment picking -
    but the same rules as every other clip: uniqueness between members, creator credit, region and content-safety checks."""
    from app.engine import discovery, region, safety
    info = json.loads(discovery._ytdlp("-J", "--no-playlist", url, capture=True, timeout=90))
    vid = info.get("id") or ""
    if not vid:
        raise SystemExit("Could not read that video link.")
    dur = float(info.get("duration") or 0)
    if end - start < 15 or end - start > 58:
        raise SystemExit("Choose a part between 15 and 58 seconds long.")
    if dur and end > dur + 1:
        raise SystemExit(f"That video is only {int(dur)} seconds long.")
    if int(info.get("age_limit") or 0) >= 18 and safety.enabled():
        raise SystemExit("That video is age-restricted, so it cannot be used.")
    ok, why, name, curl = region.check_video(url, info.get("channel_url"), info.get("title", ""), info.get("channel") or info.get("uploader") or "")
    if not ok:
        raise SystemExit(f"That creator is outside the allowed regions: {why}")
    cid = f"yt_{vid}"
    if not Claim.source(cid):
        raise SystemExit("Another member already uses this video, so it cannot be used again (every post must be unique).")
    streamer = name or info.get("channel") or info.get("uploader") or "Creator"
    title = info.get("title") or "Clip"
    out = INPUT_DIR / f"{discovery._safe(streamer)} - {discovery._safe(title)}.mp4"
    try:
        discovery._fetch(url, cid, (start, end), dur, out)
        ok, why = safety.check_clip(out, title, streamer, age_limit=int(info.get("age_limit") or 0))
        if not ok:
            out.unlink(missing_ok=True)
            raise SystemExit(f"Blocked by the content-safety check: {why}")
    except BaseException:
        Claim.release(cid)
        raise
    print(f"[Own clip] {streamer} - {title[:60]} ({int(start)}s-{int(end)}s): {why}", flush=True)
    Clip.save_downloaded({"clip_id": cid, "source": "youtube", "game_id": game.get("id"), "channel_url": curl or info.get("channel_url"),
                          "streamer": streamer, "title": title, "views": int(info.get("view_count") or 0), "url": url, "path": str(out)})
    return {"clip_id": cid, "path": str(out), "streamer": streamer, "title": title, "source": "youtube", "url": url, "channel_url": curl or info.get("channel_url")}


def own_clip_file(path: str, game: Dict) -> Dict:
    """A moment the member chose in the clip finder: the studio already cut it into a file. Same rules as every clip: it is theirs alone
    (one member per moment), the creator is credited, and it goes through the full safety check."""
    from app.engine import safety
    p = Path(path).resolve()
    root = (INPUT_DIR / "finder").resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise SystemExit("That clip file is not one the clip finder made.")
    if not p.is_file():
        raise SystemExit("The chosen clip file is missing. Pick the moment again.")
    meta = json.loads(os.environ.get("CLIP_META") or "{}")
    streamer, title = meta.get("streamer") or "Creator", meta.get("title") or "Clip"
    cid = meta.get("claim") or f"fc_{p.stem}"
    if not Claim.source(cid):
        p.unlink(missing_ok=True)
        raise SystemExit("Another member already uses this moment, so it cannot be used again (every post must be unique).")
    try:
        ok, why = safety.check_clip(p, title, streamer)
        if not ok:
            p.unlink(missing_ok=True)
            raise SystemExit(f"Blocked by the content-safety check: {why}")
    except BaseException:
        Claim.release(cid)
        raise
    print(f"[Finder clip] {streamer} - {title[:60]}: {why}", flush=True)
    Clip.save_downloaded({"clip_id": cid, "source": meta.get("source") or "youtube", "game_id": game.get("id"), "channel_url": meta.get("channel_url"),
                          "streamer": streamer, "title": title, "views": 0, "url": meta.get("url"), "path": str(p)})
    return {"clip_id": cid, "path": str(p), "streamer": streamer, "title": title, "source": meta.get("source") or "youtube", "url": meta.get("url"), "channel_url": meta.get("channel_url")}


def main():
    p = argparse.ArgumentParser(description="Clip Studio: clips -> edited videos for any game")
    p.add_argument("--mode", required=True,
                   choices=["short", "compilation", "auto-short", "auto-compilation", "remix"],
                   help="short/compilation = use local files; auto-* = download fresh clips first")
    p.add_argument("--game", default="auto",
                   help="game id from the Games tab; 'auto' = the enabled game used longest ago")
    p.add_argument("--input", help="Input video (short mode)")
    p.add_argument("--input-dir", help="Folder of clips (compilation mode)")
    p.add_argument("--layout", choices=["blur", "split"], default="blur")
    p.add_argument("--cam-crop", default="0:0:640:360", help="Facecam x:y:w:h for split layout")
    p.add_argument("--no-subtitles", action="store_true")
    p.add_argument("--title", default="", help="Compilation title (default: '<game> Best Streamer Moments')")
    p.add_argument("--streamer", default="Streamer")
    p.add_argument("--voice", default="", help="narrator voice id, or random (default: the Settings choice)")
    p.add_argument("--audio-mode", choices=["replace", "bed", "original"], default="replace",
                   help="replace=AI commentary+music, original muted (safest) | bed=original ducked under music | original=untouched")
    p.add_argument("--source", choices=["twitch", "youtube", "both", "live", "all"], default="both",
                   help="auto modes: where to find clips")
    p.add_argument("--hours", type=int, default=24, help="auto modes: look back this many hours")
    p.add_argument("--count", type=int, default=14, help="auto-compilation: clips to download")
    p.add_argument("--target-minutes", type=float, default=8.0)
    p.add_argument("--video-id", default="", help="remix: the video to make again with a different audio mode")
    p.add_argument("--url", default="", help="auto-short: use this YouTube video instead of searching (with --start and --end)")
    p.add_argument("--creator", default="", help="auto modes: only use clips from this creator (Twitch name or YouTube channel)")
    p.add_argument("--creator-platform", choices=["", "twitch", "youtube"], default="")
    p.add_argument("--clip-file", default="", help="auto-short: use this clip file made by the clip finder")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=0.0)
    a = p.parse_args()

    if a.voice and re.fullmatch(r"(random|en-[A-Za-z]{2}-\w+Neural)", a.voice):
        os.environ["TTS_VOICE_OVERRIDE"] = a.voice
    if a.mode == "remix":
        run_remix(a.video_id, a.audio_mode)
        return
    game = resolve(a.game)
    print(f"[Game] {game['name']}")

    if a.mode in ("auto-short", "auto-compilation"):
        from app.engine.discovery import discover_and_download as _discover

        def discover_and_download(count, hours, source, **kw):
            """Nothing new for this game? widen the window; still nothing? try the other enabled games (when Auto)."""
            nonlocal game
            order = [game]
            if a.game == "auto" and not a.creator:
                try:
                    order += [g for g in sorted((g for g in Game.list_for() if g.get("enabled", True)), key=lambda g: g.get("last_used_at") or "")
                              if g["id"] != game["id"]]
                except Exception:
                    pass
            err = None
            for g_try in order:
                kw["game"] = g_try
                try:
                    found = _discover_one_game(count, hours, source, g_try, **{k: v for k, v in kw.items() if k != "game"})
                except RuntimeError as e:
                    err, found = e, []
                if found:
                    if g_try is not game:
                        print(f"[Game] nothing usable for {game['name']} - using {g_try['name']} instead")
                        game = g_try
                    return found
            if err:
                raise err
            return []

        def _discover_one_game(count, hours, source, game, **kw):
            last_err = None
            for hrs, src in ((hours, source), (max(hours, 72), "both" if source in ("all", "live") else source),
                             (168, "both" if source in ("all", "live") else source)):
                try:
                    found = _discover(count=count, hours=hrs, source=src, game=game, **kw)
                except RuntimeError as e:
                    last_err, found = e, []
                if found:
                    return found
                print(f"[Discovery] nothing new for {game['name']} in the last {hrs} h" + (", widening the search" if hrs < 168 else ""))
            if last_err:
                raise last_err
            return []

        creator = {"platform": a.creator_platform, "name": a.creator} if a.creator else None
        if creator:
            print(f"[Creator] only clips from {a.creator} ({a.creator_platform or 'from the link'})", flush=True)
        if a.mode == "auto-short" and a.clip_file:
            found = [own_clip_file(a.clip_file, game)]
        elif a.mode == "auto-short" and a.url:
            found = [own_clip(a.url, a.start, a.end, game)]
        elif a.mode == "auto-short":
            found = discover_and_download(count=1, hours=a.hours, source=a.source, min_views=1,
                                          min_seconds=15, max_seconds=58, game=game, creator=creator)
            if not found:
                raise SystemExit("No new clips found.")
        _bill_finding(found, a.mode, own=bool(a.clip_file or a.url))        # what this run used besides AI: finding the clip (and the YouTube extra)
        _bill_trend(a.mode)                                                   # Trending mode, when it was used
        if creator and a.game == "auto" and found and found[0].get("game_name"):
            game = {**game, "name": found[0]["game_name"]}       # a creator's clip knows its game: use it for the title and thumbnail
        if a.mode == "auto-short":
            c = found[0]
            out = run_short_pipeline(Path(c["path"]), a.layout, a.cam_crop, not a.no_subtitles,
                                     c["streamer"], c["title"], a.audio_mode, [c["clip_id"]],
                                     game=game, credits=[credit_for(c)], hook=c.get("hook", ""), context=c.get("context", ""))
        else:
            found = discover_and_download(count=a.count, hours=a.hours, source=a.source,
                                          min_seconds=15, max_seconds=60, game=game, creator=creator)
            if not found:
                raise SystemExit("No new clips found.")
            clips = [{**c, "path": Path(c["path"])} for c in found]
            out = run_compilation_pipeline(clips, a.title, audio_mode=a.audio_mode,
                                           target_minutes=a.target_minutes, game=game)
        _bill_render(a.mode)                                                  # the video was made: the render is used
        try:
            Clip.mark_used(out["clip_ids"], out.get("video_id"))
        except Exception as e:
            print(f"[Warning] Could not mark clips used: {e}")
    elif a.mode == "short":
        if not a.input:
            p.error("--input is required for short mode")
        run_short_pipeline(Path(a.input), a.layout, a.cam_crop, not a.no_subtitles,
                           a.streamer, a.title or "Livestream Highlight", a.audio_mode, game=game)
    else:
        run_compilation_pipeline(_clips_from_dir(Path(a.input_dir) if a.input_dir else INPUT_DIR),
                                 a.title, audio_mode=a.audio_mode, target_minutes=a.target_minutes, game=game)


if __name__ == "__main__":
    main()
