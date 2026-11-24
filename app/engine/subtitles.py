import subprocess
from pathlib import Path
from app.config import (
    FFMPEG_BIN,
    SUBTITLE_FONT_NAME,
    SUBTITLE_FONT_SIZE,
    PRIMARY_COLOR,
    ACCENT_COLOR,
    OUTLINE_COLOR,
    OUTLINE_WIDTH,
    SHADOW_WIDTH
)

def format_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp format: H:MM:SS.cs"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"

def create_ass_header(play_res_x=1080, play_res_y=1920) -> str:
    """Creates the ASS header with TikTok/Shorts styling."""
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ShortsDefault,{SUBTITLE_FONT_NAME},{SUBTITLE_FONT_SIZE},{PRIMARY_COLOR},{ACCENT_COLOR},{OUTLINE_COLOR},&H80000000,-1,0,0,0,100,100,1,0,1,{OUTLINE_WIDTH},{SHADOW_WIDTH},2,50,50,330,1
Style: ShortsHighlight,{SUBTITLE_FONT_NAME},{SUBTITLE_FONT_SIZE},{ACCENT_COLOR},{PRIMARY_COLOR},{OUTLINE_COLOR},&H80000000,-1,0,0,0,105,105,1,0,1,{OUTLINE_WIDTH + 1},{SHADOW_WIDTH + 1},2,50,50,330,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def generate_ass_from_words(words_list, output_file: Path, words_per_chunk: int = 3):
    """
    Groups words into short, punchy 2-4 word phrases (Shorts style)
    and writes out an .ass subtitle file with highlighted words.
    
    words_list format: [{'word': 'HEY', 'start': 0.1, 'end': 0.5}, ...]
    """
    lines = [create_ass_header()]
    
    # Chunk words into small segments (max 3-4 words for fast retention)
    for i in range(0, len(words_list), words_per_chunk):
        chunk = words_list[i : i + words_per_chunk]
        if not chunk:
            continue
            
        start_time = chunk[0]['start']
        end_time = chunk[-1]['end']
        
        # Micro-animations: highlight current word in accent color while others are white
        for w_idx, active_word in enumerate(chunk):
            w_start = active_word['start']
            w_end = active_word['end']
            
            # Format text with the active word in yellow
            text_parts = []
            for other_word in chunk:
                clean_w = other_word['word'].strip().upper()
                if other_word == active_word:
                    text_parts.append(f"{{\\c{ACCENT_COLOR}}}{clean_w}{{\\c{PRIMARY_COLOR}}}")
                else:
                    text_parts.append(clean_w)
                    
            event_text = " ".join(text_parts)
            line = f"Dialogue: 0,{format_timestamp(w_start)},{format_timestamp(w_end)},ShortsDefault,,0,0,0,,{event_text}"
            lines.append(line)
            
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    return output_file

def transcribe_audio_to_words(video_path: Path, temp_dir: Path):
    """
    Extracts audio from video and transcribes using faster-whisper or whisper.
    If neither is installed, falls back to generating timed placeholder captions.
    """
    audio_path = temp_dir / f"{video_path.stem}_audio.wav"
    
    # 1. Extract audio
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    words = []
    
    # Try faster-whisper first
    try:
        from faster_whisper import WhisperModel
        print("[Subtitles] Using faster-whisper model for transcription...")
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), word_timestamps=True)
        for seg in segments:
            if seg.words:
                for w in seg.words:
                    words.append({"word": w.word, "start": w.start, "end": w.end})
            else:
                words.append({"word": seg.text, "start": seg.start, "end": seg.end})
        from app.models import UsageEvent
        UsageEvent.record("whisper", provider="whisper", task="captions", units=float(getattr(info, "duration", 0) or 0))
        return words
    except ImportError:
        pass
        
    # Try standard whisper
    try:
        import whisper
        print("[Subtitles] Using openai-whisper for transcription...")
        model = whisper.load_model("base")
        result = model.transcribe(str(audio_path), word_timestamps=True)
        for seg in result.get("segments", []):
            if "words" in seg:
                for w in seg["words"]:
                    words.append({"word": w["word"], "start": w["start"], "end": w["end"]})
            else:
                words.append({"word": seg["text"], "start": seg["start"], "end": seg["end"]})
        return words
    except ImportError:
        pass
        
    print("[Subtitles] No Whisper installed (pip install faster-whisper) - rendering without captions.")
    return []
