"""Copyright audio shield.

Streamer voice + in-game radio can't be separated, so the only fully safe options are:
  replace    original audio muted -> AI commentary voiceover + royalty-free music  (SAFEST, default)
  bed        original ducked under royalty-free music (radio/voice still faintly present = risk)
  original   untouched (loudness-normalised only)  -> will likely get Content ID claims

Commentary text comes from Gemini (needs GEMINI_API_KEY); voice is edge-tts (free, no key).
Without a Gemini key 'replace' falls back to 'bed'.
"""
import asyncio
import os
import random
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.config import FFMPEG_BIN, MUSIC_DIR, TEMP_DIR, TTS_VOICE, YOUTUBE_LUFS_TARGET

MUSIC_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def pick_music() -> Optional[Path]:
    tracks = [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in MUSIC_EXT]
    return random.choice(tracks) if tracks else None


def video_duration(path: Path) -> float:
    from app.engine.video_processor import get_video_info
    return get_video_info(path)["duration"]


def template_commentary(streamer: str, title: str, game_name: str, max_words: int) -> str:
    """Built-in narration used when no Gemini model is available, so a voice-over always exists."""
    import re
    game = game_name or "this game"
    t = re.sub(r"[^\w\s'!?.,:-]", "", title or "").strip()[:70]
    lines = [f"Check out this moment from {streamer or 'a top creator'} in {game}.", f"{t}." if t else "",
             "Watch closely, because this one escalates fast.", "You can feel the chaos building in real time.",
             "Honestly, nobody saw that coming.", f"This is exactly why people love {game}.",
             "Drop your reaction in the comments, and follow for more."]
    return " ".join(" ".join(x for x in lines if x).split()[:max_words])


def write_commentary(transcript: str, streamer: str, title: str, max_words: int, game_name: str = "", context: str = "") -> Optional[str]:
    """Short original commentary: the member's own text if they wrote it, else Gemini / DeepSeek, else the built-in template. Never returns None."""
    own = " ".join((os.environ.get("DIY_COMMENTARY") or "").split())
    if own:
        return " ".join(own.split()[:max_words])
    try:
        from app.engine import llm
        about = f"\nWHAT THE VIDEO IS AND WHAT CAME BEFORE: {context[:1200]}" if context.strip() else ""
        prompt = (
            f"You write the voice-over for a {game_name or 'gaming'} YouTube Shorts channel. The viewer has NOT seen the rest of this video and the "
            f"creator's own audio is muted, so YOUR words must make the moment make sense on their own.\n"
            f"FACTS (use them; never invent anything beyond them):\n"
            f"- Original video title: '{title}'.{about}\n"
            f"- What is said in the clip itself: \"{transcript[:1200]}\"\n"
            f"Write ORIGINAL narration of at most {max_words} words, in natural spoken English:\n"
            "1. The first sentence sets the scene in plain words: who or what, where, and what is at stake, using the facts above.\n"
            "2. Then say what happens, in order, and why it is funny, tense or surprising.\n"
            "3. End with a short take or a question to the viewer.\n"
            "Stick to the facts: say only what the words in the clip and the facts above support. If you are not sure what exactly happens, describe the mood and what is said instead of inventing events, people, numbers or motives.\n"
            "Rules: talk about the player from outside (he, she, they, the player), never as 'I'. No 'this clip', no 'watch closely', no 'you won't believe', "
            "no stage directions, no emojis, no word-for-word quotes of the creator. Return only the narration text."
        )
        text = llm.generate("commentary", prompt).strip().strip('"')
        text = " ".join(text.split()[:max_words])
        if text:
            return text
    except Exception as e:
        print(f"[Audio] no AI available for commentary ({str(e)[:120]}) - using built-in commentary")
    return template_commentary(streamer, title, game_name, max_words)


async def _tts(text: str, out_mp3: Path) -> List[Dict]:
    import edge_tts
    words: List[Dict] = []
    comm = edge_tts.Communicate(text, _voice(), boundary="WordBoundary")
    with open(out_mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append({"word": chunk["text"], "start": s, "end": s + chunk["duration"] / 1e7})
    return words


VOICE_POOL = ["en-US-GuyNeural", "en-US-ChristopherNeural", "en-US-AriaNeural", "en-US-JennyNeural",
              "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-AU-WilliamNeural", "en-CA-LiamNeural"]
_chosen: Optional[str] = None


def _voice() -> str:
    """Narrator for this video: the one picked on the Create page, else the Settings default; 'random' picks one voice per video."""
    global _chosen
    v = os.environ.get("TTS_VOICE_OVERRIDE") or os.environ.get("TTS_VOICE") or TTS_VOICE
    if v.strip().lower() in ("random", "mix"):
        if not _chosen:
            _chosen = random.choice(VOICE_POOL)
            print(f"[Audio] narrator (random): {_chosen}", flush=True)
        return _chosen
    return v


def synthesize(text: str, out_mp3: Path) -> List[Dict]:
    """TTS to mp3. Returns word timings (for captions)."""
    words = asyncio.run(_tts(text, out_mp3))
    from app.models import UsageEvent
    UsageEvent.record("tts", provider="edge-tts", task="commentary", units=len(text))
    return words


def build_audio(video: Path, mode: str, stem: str, transcript: str = "",
                streamer: str = "", title: str = "", game_name: str = "", context: str = "") -> Tuple[Optional[Path], List[Dict], str]:
    """Create the final audio track for `video`.

    Returns (audio_path or None to keep original, caption_words or [] to transcribe original, mode_used).
    """
    if mode == "original":
        return None, [], "original"

    dur = video_duration(video)
    music = pick_music()
    if not music and mode != "replace":
        print("[Audio] No tracks in music/ - add royalty-free music there. Keeping original audio.")
        return None, [], "original"
    if not music:
        print("[Audio] No music tracks - voice-over only (original audio stays muted).")

    from app.engine import clean_cuts
    _f = clean_cuts.fade_filter(dur)
    FADE = ("," + _f) if _f else ""                 # a 30 ms fade at both ends: no click at the cut
    voice_path, words, vol = None, [], 0.25
    if mode == "replace":
        text = write_commentary(transcript, streamer, title, max_words=max(8, int(dur * 2.4)), game_name=game_name, context=context)
        if text:
            voice_path = TEMP_DIR / f"{stem}_voice.mp3"
            words = synthesize(text, voice_path)
        else:
            print("[Audio] No commentary available -> falling back to 'bed' mode.")
            mode = "bed"

    out = TEMP_DIR / f"{stem}_mix.m4a"
    if voice_path and not music:   # voice-over only
        cmd = [FFMPEG_BIN, "-y", "-i", str(video), "-i", str(voice_path), "-filter_complex",
               f"[1:a]volume=1.4,apad,atrim=0:{dur:.2f},loudnorm=I={YOUTUBE_LUFS_TARGET}:LRA=11:TP=-1.5{FADE}[out]",
               "-map", "[out]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out, words, mode
    cmd = [FFMPEG_BIN, "-y", "-i", str(video), "-stream_loop", "-1", "-i", str(music)]
    if voice_path:
        cmd += ["-i", str(voice_path)]
        fc = (f"[1:a]volume=0.22,atrim=0:{dur:.2f},afade=t=out:st={max(dur-1,0):.2f}:d=1[m];"
              f"[2:a]volume=1.4,apad[v];[m][v]amix=inputs=2:duration=first:normalize=0,"
              f"atrim=0:{dur:.2f},loudnorm=I={YOUTUBE_LUFS_TARGET}:LRA=11:TP=-1.5{FADE}[out]")
    else:  # bed
        fc = (f"[0:a]volume=0.35[o];[1:a]volume=0.2,atrim=0:{dur:.2f}[m];"
              f"[o][m]amix=inputs=2:duration=first:normalize=0,"
              f"loudnorm=I={YOUTUBE_LUFS_TARGET}:LRA=11:TP=-1.5{FADE}[out]")
    cmd += ["-filter_complex", fc, "-map", "[out]", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out, words, mode
