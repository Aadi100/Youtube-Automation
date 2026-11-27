"""The emotional narrator: Azure Speech (Microsoft's official, paid-for text to speech; commercial use is allowed; a free allowance is included each month).

Each scene has a MOOD (scared, sad, excited ...). It is turned into the voice's speaking STYLE (terrified, sad, excited ...) and a little change of speed and pitch, so the narrator acts the line instead of reading it.
A style the chosen voice does not have is ignored by Azure (the voice then speaks normally), so a wrong guess never breaks a scene.
If Azure is not set up or does not answer, the studio uses the free voice (Kokoro) instead, and the story is still made.
The REST service does not tell the time of each word, so the word times for the captions are worked out from the length of the audio.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from xml.sax.saxutils import escape

import requests

# mood -> (speaking style, how strong 0.01-2, speed change, pitch change)
MOODS = {"calm": (None, 1.0, "-4%", "0%"), "tense": (None, 1.0, "-8%", "-3%"), "scared": ("terrified", 1.2, "+0%", "+2%"), "sad": ("sad", 1.3, "-10%", "-3%"),
         "happy": ("cheerful", 1.2, "+4%", "+3%"), "excited": ("excited", 1.3, "+8%", "+4%"), "angry": ("angry", 1.3, "+3%", "-1%"), "whisper": ("whispering", 1.4, "-6%", "-2%")}
DEFAULT_VOICE = "en-US-GuyNeural"


class Unavailable(RuntimeError):
    pass


def _env(name: str) -> str:
    from app.utils.envfile import read_env
    return (os.environ.get(name) or read_env().get(name) or "").strip()


def configured() -> bool:
    return bool(_env("AZURE_SPEECH_KEY") and re.fullmatch(r"[a-z0-9-]{3,30}", _env("AZURE_SPEECH_REGION").lower()))


def ssml(text: str, voice: str, mood: str = "calm") -> str:
    style, degree, rate, pitch = MOODS.get(mood) or MOODS["calm"]
    voice = voice if re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+Neural", voice or "") else DEFAULT_VOICE
    body = f'<prosody rate="{rate}" pitch="{pitch}">{escape(text)}</prosody>'
    if style:
        body = f'<mstts:express-as style="{style}" styledegree="{degree}">{body}</mstts:express-as>'
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">'
            f'<voice name="{voice}">{body}</voice></speak>')


def _why(r) -> str:
    if r.status_code in (401, 403):
        return "Azure refused the speech key (check the key and the region in Settings)."
    if r.status_code == 429:
        return "Azure says the speech allowance is used up for now."
    return f"Azure said {r.status_code}."


def synthesize(text: str, voice: str, out: Path, mood: str = "calm") -> List[Dict]:
    """Say `text` in the mood and save it as an mp3. Returns the words with start and end seconds. Raises Unavailable (with a plain reason) when Azure cannot do it."""
    from app.engine import kokoro_tts
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise Unavailable("There is nothing to say.")
    if not configured():
        raise Unavailable("Azure Speech is not set up.")
    url = f"https://{_env('AZURE_SPEECH_REGION').lower()}.tts.speech.microsoft.com/cognitiveservices/v1"
    hdr = {"Ocp-Apim-Subscription-Key": _env("AZURE_SPEECH_KEY"), "Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3", "User-Agent": "ClipStudio"}
    try:
        r = requests.post(url, headers=hdr, data=ssml(text, voice, mood).encode("utf-8"), timeout=60)
        if r.status_code == 400 and mood in MOODS and MOODS[mood][0]:   # a voice that rejects the style: say it plainly
            r = requests.post(url, headers=hdr, data=ssml(text, voice, "calm").encode("utf-8"), timeout=60)
    except requests.RequestException as e:
        raise Unavailable(f"Could not reach Azure ({type(e).__name__}).") from e
    if r.status_code != 200 or len(r.content) < 500:
        raise Unavailable(_why(r))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    from app.engine import story_media as SM
    return kokoro_tts._word_times(text, SM.duration(out))
