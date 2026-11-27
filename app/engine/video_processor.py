import subprocess
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from app.config import (
    FFMPEG_BIN,
    FFPROBE_BIN,
    FPS,
    SHORTS_WIDTH,
    SHORTS_HEIGHT,
    COMPILATION_WIDTH,
    COMPILATION_HEIGHT,
    YOUTUBE_LUFS_TARGET,
    TEMP_DIR,
    SHORTS_OUTPUT_DIR,
    COMPILATIONS_OUTPUT_DIR
)
from app.engine.subtitles import transcribe_audio_to_words, generate_ass_from_words

def escape_ffmpeg_path(path: Path) -> str:
    """Escapes a Windows path for FFmpeg filter arguments. It cannot make an apostrophe safe (the filter reads the text twice), so a file that is named
    after a clip's title must never go through here: use safe_name() for the file name."""
    p_str = str(path.resolve()).replace("\\", "/")
    p_str = p_str.replace(":", "\\:")
    return p_str


def safe_name(stem: str) -> str:
    """A file name part that is the same for the same title but has nothing in it that a filter or a list file could trip over
    (apostrophes, brackets, commas, quotes...). Used for the temporary subtitle files that are named after the video."""
    import hashlib
    import re as _re
    return (_re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:60].strip("_") or "clip") + "_" + hashlib.md5(stem.encode("utf-8", "ignore")).hexdigest()[:6]

def get_video_info(video_path: Path) -> Dict:
    """Gets video duration, width, and height using ffprobe."""
    cmd = [
        FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path)
    ]
    try:
        res = subprocess.check_output(cmd)
        data = json.loads(res)
        duration = float(data.get("format", {}).get("duration", 0.0))
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        width = int(video_stream.get("width", 1920)) if video_stream else 1920
        height = int(video_stream.get("height", 1080)) if video_stream else 1080
        return {"duration": duration, "width": width, "height": height}
    except Exception as e:
        print(f"[Probe Error] {e}")
        return {"duration": 15.0, "width": 1920, "height": 1080}

def create_badge_ass(idx: int, streamer: str, title: str, output_file: Path) -> Path:
    """Creates a sleek lower-third badge with fade in/out using ASS format."""
    clean_title = title.replace("{", "").replace("}", "").upper()
    clean_streamer = streamer.replace("{", "").replace("}", "")

    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BadgeStyle,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,3,12,0,1,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:04.50,BadgeStyle,,0,0,0,,{{\\fad(400,400)}}CLIP #{idx}  |  @{clean_streamer} : {clean_title}
"""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(ass_content)
    return output_file

def _fade_tail(duration: float) -> str:
    """',afade=...' (a 30 ms fade in and out) to add after an audio filter, or '' when the length is unknown."""
    from app.engine import clean_cuts
    f = clean_cuts.fade_filter(duration)
    return ("," + f) if f else ""


def _audio_inputs(audio_path: Optional[Path]) -> list:
    return ["-i", str(audio_path)] if audio_path else []


def _audio_map(audio_path: Optional[Path], audio_filter: str) -> list:
    """Pre-mixed shield audio is already normalised; original audio is normalised here."""
    return ["-map", "1:a"] if audio_path else ["-map", "0:a?", "-af", audio_filter]


def make_short_blurred(
    input_video: Path,
    output_video: Optional[Path] = None,
    with_subtitles: bool = True,
    audio_path: Optional[Path] = None,
    words: Optional[list] = None,
    card: Optional[str] = None
) -> Path:
    """Creates a 9:16 YouTube Short with blurred background and centered gameplay."""
    if not output_video:
        output_video = SHORTS_OUTPUT_DIR / f"{input_video.stem}_short.mp4"

    ass_path = None
    if with_subtitles or card:
        if with_subtitles and not words:
            words = transcribe_audio_to_words(input_video, TEMP_DIR)
        ass_path = TEMP_DIR / f"{safe_name(input_video.stem)}_subs.ass"
        generate_ass_from_words(words if with_subtitles else [], ass_path, card=card)

    filtergraph = [
        "[0:v]split=2[bg][fg];",
        f"[bg]scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=increase,crop={SHORTS_WIDTH}:{SHORTS_HEIGHT},boxblur=25:5[bgblur];",
        f"[fg]scale={SHORTS_WIDTH}:-1:force_original_aspect_ratio=decrease[fgscaled];",
        "[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2[base]"
    ]

    if ass_path and ass_path.exists():
        escaped_ass = escape_ffmpeg_path(ass_path)
        filtergraph.append(f";[base]ass='{escaped_ass}'[vout]")
        v_map = "[vout]"
    else:
        v_map = "[base]"

    audio_filter = f"loudnorm=I={YOUTUBE_LUFS_TARGET}:LRA=11:TP=-1.5,aformat=channel_layouts=stereo"

    cmd = [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_video),
        *_audio_inputs(audio_path),
        "-filter_complex", "".join(filtergraph),
        "-map", v_map,
        *_audio_map(audio_path, audio_filter + ("" if audio_path else _fade_tail(get_video_info(input_video).get("duration", 0)))),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-r", str(FPS),
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_video)
    ]

    print(f"[Shorts] Rendering blurred-background Short: {output_video.name}...")
    subprocess.run(cmd, check=True)
    print(f"[Shorts] Successfully created: {output_video}")
    return output_video

def make_short_split(
    input_video: Path,
    cam_crop: str = "0:0:640:360",
    output_video: Optional[Path] = None,
    with_subtitles: bool = True,
    audio_path: Optional[Path] = None,
    words: Optional[list] = None,
    card: Optional[str] = None
) -> Path:
    """Creates a 9:16 Short with Streamer Facecam on Top and Gameplay on Bottom."""
    if not output_video:
        output_video = SHORTS_OUTPUT_DIR / f"{input_video.stem}_split_short.mp4"

    ass_path = None
    if with_subtitles or card:
        if with_subtitles and not words:
            words = transcribe_audio_to_words(input_video, TEMP_DIR)
        ass_path = TEMP_DIR / f"{safe_name(input_video.stem)}_split_subs.ass"
        generate_ass_from_words(words if with_subtitles else [], ass_path, card=card)

    cam_x, cam_y, cam_w, cam_h = cam_crop.split(":")

    filtergraph = [
        f"[0:v]split=2[cam_in][game_in];",
        f"[cam_in]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},scale={SHORTS_WIDTH}:720[top_cam];",
        f"[game_in]crop=in_w:in_h:0:0,scale={SHORTS_WIDTH}:1200:force_original_aspect_ratio=increase,crop={SHORTS_WIDTH}:1200[bot_game];",
        f"[top_cam][bot_game]vstack=inputs=2[base]"
    ]

    if ass_path and ass_path.exists():
        escaped_ass = escape_ffmpeg_path(ass_path)
        filtergraph.append(f";[base]ass='{escaped_ass}'[vout]")
        v_map = "[vout]"
    else:
        v_map = "[base]"

    audio_filter = f"loudnorm=I={YOUTUBE_LUFS_TARGET}:LRA=11:TP=-1.5,aformat=channel_layouts=stereo"

    cmd = [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_video),
        *_audio_inputs(audio_path),
        "-filter_complex", "".join(filtergraph),
        "-map", v_map,
        *_audio_map(audio_path, audio_filter + ("" if audio_path else _fade_tail(get_video_info(input_video).get("duration", 0)))),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-r", str(FPS),
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_video)
    ]

    print(f"[Shorts] Rendering split-cam Short: {output_video.name}...")
    subprocess.run(cmd, check=True)
    return output_video

def create_compilation(
    clips: List[Dict],
    compilation_title: str = "Best Moments",
    output_video: Optional[Path] = None,
    audio_mode: str = "original",
    game_name: str = ""
) -> Dict:
    """Creates a full 8-10 minute long-form compilation with normalized audio and lower-third credits."""
    if not output_video:
        safe_title = "".join(c for c in compilation_title if c.isalnum() or c in (" ", "_", "-")).rstrip()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # unique per run: never overwrite an older video
        output_video = COMPILATIONS_OUTPUT_DIR / f"{safe_title.replace(' ', '_').lower()}_{stamp}.mp4"

    normalized_clips = []
    chapter_markers = ["00:00 - Intro & Highlights"]
    current_timestamp = 0.0

    print(f"[Compilation] Processing {len(clips)} clips for compilation: '{compilation_title}'...")

    for idx, clip_info in enumerate(clips, 1):
        c_path = Path(clip_info['path'])
        c_title = clip_info.get('title', f'Epic Moment #{idx}')
        c_streamer = clip_info.get('streamer', 'Featured Creator')

        info = get_video_info(c_path)
        clip_duration = info['duration']

        mins = int(current_timestamp // 60)
        secs = int(current_timestamp % 60)
        chapter_markers.append(f"{mins:02d}:{secs:02d} - Clip #{idx}: {c_title} (@{c_streamer})")
        current_timestamp += clip_duration

        badge_ass = TEMP_DIR / f"badge_{idx}.ass"
        create_badge_ass(idx, c_streamer, c_title, badge_ass)
        escaped_badge = escape_ffmpeg_path(badge_ass)

        norm_output = TEMP_DIR / f"norm_clip_{idx}.mp4"

        v_filter = f"scale={COMPILATION_WIDTH}:{COMPILATION_HEIGHT}:force_original_aspect_ratio=decrease,pad={COMPILATION_WIDTH}:{COMPILATION_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,ass='{escaped_badge}'"
        a_filter = f"loudnorm=I={YOUTUBE_LUFS_TARGET}:LRA=11:TP=-1.5,aformat=channel_layouts=stereo:sample_rates=48000" + _fade_tail(clip_duration)

        mix = None
        if audio_mode != "original":
            from app.engine.audio_shield import build_audio
            transcript = ""
            if audio_mode == "replace":
                transcript = " ".join(w["word"].strip() for w in transcribe_audio_to_words(c_path, TEMP_DIR))
            mix, _, _ = build_audio(c_path, audio_mode, f"comp_{idx}", transcript, c_streamer, c_title, game_name)

        cmd = [
            FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(c_path),
            *_audio_inputs(mix),
            "-vf", v_filter,
            *(["-map", "0:v", "-map", "1:a"] if mix else ["-af", a_filter]),
            "-r", str(FPS),
            "-c:v", "libx264",
            "-preset", "faster",
            "-crf", "19",
            "-c:a", "aac",
            "-b:a", "192k",
            str(norm_output)
        ]
        print(f"  -> Prepping Clip {idx}/{len(clips)}: {c_title}...")
        subprocess.run(cmd, check=True)
        normalized_clips.append(norm_output)

    concat_list_file = TEMP_DIR / "concat_list.txt"
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for p in normalized_clips:
            escaped_p = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")      # an apostrophe in a file name must not end the quote
            f.write(f"file '{escaped_p}'\n")

    concat_cmd = [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_file),
        "-c", "copy",
        str(output_video)
    ]
    print(f"[Compilation] Stitching into final compilation: {output_video.name}...")
    subprocess.run(concat_cmd, check=True)

    chapters_file = output_video.with_suffix(".txt")
    with open(chapters_file, "w", encoding="utf-8") as f:
        f.write("\n".join(chapter_markers))

    print(f"[Compilation] Created successfully! Output: {output_video}")
    return {
        "video_path": output_video,
        "chapters": chapter_markers,
        "chapters_file": chapters_file
    }
