from app.models import Clip, Game, Video
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
        data["video_id"] = Video.save_manifest(data, job_id=os.environ.get("GTA6_JOB_ID"))
    except Exception as e:  # the render is done; a DB outage must not lose it
        data["video_id"] = None
        print(f"[Warning] Could not save to MongoDB: {e}")
    target = Path(os.environ.get("GTA6_MANIFEST") or MANIFEST)   # the server gives every job its own manifest file
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
    }


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
) -> Dict:
    game = game or Game.default_data()
    print(f"\n=== SHORTS PIPELINE [{game['name']}]: {input_video.name} (audio: {audio_mode}) ===")

    # Audio shield first: it may supply the captions (commentary words) too.
    transcript = ""
    if audio_mode == "replace":
        transcript = " ".join(w["word"].strip() for w in transcribe_audio_to_words(input_video, TEMP_DIR))
    audio_path, words, audio_used = build_audio(
        input_video, audio_mode, input_video.stem, transcript, streamer_name, topic, game["name"])

    kwargs = dict(input_video=input_video, with_subtitles=with_subtitles,
                  audio_path=audio_path, words=words)
    rendered = (make_short_split(cam_crop=cam_crop, **kwargs) if layout == "split"
                else make_short_blurred(**kwargs))

    credits = credits or [{"creator": streamer_name}]
    meta = generate_seo_metadata(video_type="short", topic=topic, streamers=[streamer_name], context=f"{hook}. What was said: {transcript[:700]}".strip(". "),
                                 game=game, credits=credits)
    from app.engine.safety import check_final_video
    ok, why = check_final_video(rendered, meta.get("title", ""), meta.get("description", ""))
    if not ok:
        raise SystemExit(f"Blocked by the content-safety check: {why}")
    print(f"[Safety] final video: {why}")
    thumb = generate_thumbnail(video_path=input_video, output_path=rendered.with_name(f"{rendered.stem}_9x16_thumb.jpg"), headline=meta["thumb_headline"],
                               subtext=meta["thumb_subtext"], mode="9:16", game_name=game.get("name"), scene=meta.get("thumb_scene", ""))

    meta_file = rendered.with_suffix(".json")
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Short: {rendered}\nCover: {thumb}\nMeta:  {meta_file}")
    return _write_manifest(_manifest("short", rendered, thumb, meta, audio_used, clip_ids or [], game, credits))


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
    thumb = generate_thumbnail(video_path=video_path, headline=meta["thumb_headline"],
                               subtext=meta["thumb_subtext"], mode="16:9", game_name=game.get("name"), scene=meta.get("thumb_scene", ""))

    meta_file = video_path.with_suffix(".json")
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Video: {video_path} ({total/60:.1f} min)\nThumb: {thumb}\nMeta:  {meta_file}")
    ids = clip_ids if clip_ids is not None else [c["clip_id"] for c in chosen if "clip_id" in c]
    return _write_manifest(_manifest("compilation", video_path, thumb, meta, audio_mode, ids, game, credits))


def main():
    p = argparse.ArgumentParser(description="Clip Studio: clips -> edited videos for any game")
    p.add_argument("--mode", required=True,
                   choices=["short", "compilation", "auto-short", "auto-compilation"],
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
    a = p.parse_args()

    if a.voice and re.fullmatch(r"(random|en-[A-Za-z]{2}-\w+Neural)", a.voice):
        os.environ["TTS_VOICE_OVERRIDE"] = a.voice
    game = resolve(a.game)
    print(f"[Game] {game['name']}")

    if a.mode in ("auto-short", "auto-compilation"):
        from app.engine.discovery import discover_and_download as _discover

        def discover_and_download(count, hours, source, **kw):
            """Nothing new for this game? widen the window; still nothing? try the other enabled games (when Auto)."""
            nonlocal game
            order = [game]
            if a.game == "auto":
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

        if a.mode == "auto-short":
            found = discover_and_download(count=1, hours=a.hours, source=a.source, min_views=1,
                                          min_seconds=15, max_seconds=58, game=game)
            if not found:
                raise SystemExit("No new clips found.")
            c = found[0]
            out = run_short_pipeline(Path(c["path"]), a.layout, a.cam_crop, not a.no_subtitles,
                                     c["streamer"], c["title"], a.audio_mode, [c["clip_id"]],
                                     game=game, credits=[credit_for(c)], hook=c.get("hook", ""))
        else:
            found = discover_and_download(count=a.count, hours=a.hours, source=a.source,
                                          min_seconds=15, max_seconds=60, game=game)
            if not found:
                raise SystemExit("No new clips found.")
            clips = [{**c, "path": Path(c["path"])} for c in found]
            out = run_compilation_pipeline(clips, a.title, audio_mode=a.audio_mode,
                                           target_minutes=a.target_minutes, game=game)
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
