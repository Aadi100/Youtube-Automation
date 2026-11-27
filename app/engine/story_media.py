"""Story videos: making the pictures, the movement, the voice, and one finished scene.

  picture   FLUX (Cloudflare Workers AI, the same key as the thumbnails) draws ONE picture of the scene in the story's art style, with the same character descriptions in every
            scene so that the story looks like one film.
  movement  Two ways, chosen per story:
            "veo"     an AI VIDEO model (Google Veo, through the Gemini key) turns the picture into a short clip in which the characters really move. It costs real money per second.
            "motion"  no video model: the picture gets camera movement (slow push in, pan, tilt). Cheap, always works, but the characters do not move.
            If Veo refuses a scene or is busy, that scene is made with camera movement instead (and is charged as such).
  voice     edge-tts narration; its word times become the captions.
  scene     the moving picture + the voice + the captions in one 9:16 video file.
Everything here is plain functions on files. Who may do what, and who pays, is decided by story_service.
"""
import asyncio
import base64
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from app.config import FFMPEG_BIN, FFPROBE_BIN, TEMP_DIR
from app.engine import story_script as SS

W, H, FPS = 1080, 1920, 30
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
VEO_SECONDS = (4, 6, 8)
VEO_WAIT = 600                                          # seconds to wait for one clip
VOICES = {"scary": "en-US-ChristopherNeural", "what_if": "en-US-GuyNeural", "mystery": "en-GB-RyanNeural", "funny": "en-AU-WilliamNeural",
          "motivation": "en-US-JennyNeural", "history": "en-GB-RyanNeural"}
_models_cache: Dict = {"t": 0.0, "v": []}


# ---------------------------------------------------------------- the picture
def keyframe_prompt(scene: Dict, script: Dict) -> str:
    chars = {c["id"]: c for c in script.get("characters") or []}
    who = "; ".join(f"{chars[i]['name']}: {chars[i]['look']}" for i in scene.get("characters") or [] if i in chars)
    st = SS.style(script.get("style"))[2]
    return (f"{scene['visual']}. " + (f"Characters (keep their look exactly): {who}. " if who else "") + f"Style: {st}. Vertical 9:16 composition, one clear focal point, "
            "Family-friendly, wholesome, fully clothed characters, safe for all ages. No text, no captions, no watermark, no logos.")[:1800]


_RISKY = re.compile(r"\b(nud\w*|naked|sexy|sexual\w*|seduc\w*|erotic|lingerie|underwear|bikini|topless|bare|undress\w*|strip\w*|breasts?|cleavage|thigh\w*|buttocks?|lust\w*|kiss\w*|beds?|bedroom|bath\w*|shower\w*|blood\w*|gore|gory|corpse|dead body|bleed\w*|wound\w*|torture\w*|kill\w*|murder\w*|stab\w*|gun\w*|weapon\w*)\b", re.I)


def soften(prompt: str) -> str:
    """The same scene with the words that picture filters often mistake for adult or violent content taken out."""
    t = _RISKY.sub("", prompt)
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([.,;:])", r"\1", t)).strip()


def _placeholder(scene: Dict, out: Path) -> Path:
    """When no picture AI is set up: a plain dark card with the scene number, so the rest of the film can still be built and tried."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), (24, 28, 40))
    d = ImageDraw.Draw(im)
    for y in range(0, H, 8):
        d.rectangle([0, y, W, y + 8], fill=(24 + y // 60, 28 + y // 90, 40 + y // 50))
    d.text((60, 60), f"Scene {scene.get('n', '')}", fill=(230, 230, 230))
    im.save(out, "PNG")
    return out


def make_keyframe(scene: Dict, script: Dict, out: Path) -> Tuple[Optional[Path], str]:
    """One picture of the scene. Returns (file, "") or (None, the reason in plain words). With no Cloudflare key a plain card is made and the reason says so."""
    from app.engine import thumb_best
    if not thumb_best.cloudflare_ready():
        return _placeholder(scene, out), "The picture AI (Cloudflare) is not set up, so a plain card was used."
    prompt = keyframe_prompt(scene, script)
    raw, why = thumb_best._request(prompt)
    if raw is None and "nsfw" in (why or "").lower():                # a false alarm of the filter: say it again without the risky words, then very plainly
        raw, why = thumb_best._request(soften(prompt))
        if raw is None and "nsfw" in (why or "").lower():
            raw, why = thumb_best._request(f"{SS.style(script.get('style'))[2]}. A calm, wholesome, family-friendly illustration for a story: "
                                           f"{soften(scene.get('visual') or '')[:300]}. Everyone fully clothed, no text, vertical 9:16.")
    if raw is None:
        return None, why
    try:
        thumb_best._fit(raw, "9:16", out)
    except Exception:
        return None, "Cloudflare sent a picture the studio could not read."
    return out, ""


# ---------------------------------------------------------------- movement without a video model
_CAM = {"slow push in": "z='min(1+0.0009*on,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        "slow pull back": "z='max(1.25-0.0009*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        "pan left": "z=1.15:x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-(ih/zoom/2)'",
        "pan right": "z=1.15:x='(iw-iw/zoom)*(on/{n})':y='ih/2-(ih/zoom/2)'",
        "slow tilt up": "z=1.15:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{n})'",
        "static with gentle movement": "z='1.04+0.01*sin(on/18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        "handheld": "z=1.08:x='iw/2-(iw/zoom/2)+6*sin(on/5)+3*sin(on/2.3)':y='ih/2-(ih/zoom/2)+5*cos(on/6)+2*sin(on/1.9)'",
        "push in left": "z='min(1+0.0012*on,1.3)':x='(iw-iw/zoom)*0.25':y='ih/2-(ih/zoom/2)'",
        "push in right": "z='min(1+0.0012*on,1.3)':x='(iw-iw/zoom)*0.75':y='ih/2-(ih/zoom/2)'"}


def motion_clip(image: Path, seconds: float, camera: str, out: Path) -> Path:
    """The picture with camera movement (no AI video model): a 9:16, 30 fps clip without sound."""
    n = max(1, int(round(seconds * FPS)))
    z = _CAM.get(camera, _CAM["slow push in"]).replace("{n}", str(n))
    subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(image), "-vf", f"scale={W * 2}:{H * 2},zoompan={z}:d={n}:s={W}x{H}:fps={FPS},format=yuv420p",
                    "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(out)], check=True, timeout=600)
    return out


# ---------------------------------------------------------------- movement with an AI video model (Google Veo)
def veo_key() -> str:
    from app.utils.envfile import read_env
    return (os.environ.get("GEMINI_API_KEY") or read_env().get("GEMINI_API_KEY") or "").strip()


def veo_models(key: Optional[str] = None, force: bool = False) -> List[str]:
    """The Veo models this Gemini key can use, cheapest kind first (ids like 'veo-3.1-fast-generate-preview'). [] when there are none or Google does not answer."""
    if not force and time.time() - _models_cache["t"] < 3600:
        return _models_cache["v"]
    key = key or veo_key()
    if not key:
        return []
    try:
        r = requests.get(f"{GEMINI}/models", params={"pageSize": 200}, headers={"x-goog-api-key": key}, timeout=30)
        r.raise_for_status()
        found = [m["name"].split("/")[-1] for m in r.json().get("models", []) if "veo" in m.get("name", "").lower()
                 and "predictLongRunning" in (m.get("supportedGenerationMethods") or [])]
    except Exception:
        return _models_cache["v"] or []
    found.sort(key=lambda n: (0 if "lite" in n else 1 if "fast" in n else 2, n))
    _models_cache.update(t=time.time(), v=found)
    return found


def veo_model() -> Optional[str]:
    chosen = (os.environ.get("VEO_MODEL") or "").strip()
    return chosen or (veo_models() or [None])[0]


def veo_seconds(seconds: float) -> int:
    return next((s for s in VEO_SECONDS if seconds <= s), VEO_SECONDS[-1])


def veo_animate(image: Path, prompt: str, seconds: float, out: Path, model: Optional[str] = None, key: Optional[str] = None, wait: int = VEO_WAIT) -> Tuple[bool, str]:
    """Turn the picture into a moving clip with Veo. Returns (True, "") or (False, the reason in plain words). The clip is saved without relying on Veo's own sound."""
    key, model = key or veo_key(), model or veo_model()
    if not key:
        return False, "There is no Gemini key saved."
    if not model:
        return False, "This Gemini key cannot use a Veo video model (it needs a paid Google AI plan)."
    hdr = {"x-goog-api-key": key}
    body = {"instances": [{"prompt": prompt[:1500], "image": {"bytesBase64Encoded": base64.b64encode(Path(image).read_bytes()).decode(), "mimeType": "image/png"}}],
            "parameters": {"aspectRatio": "9:16", "durationSeconds": veo_seconds(seconds), "resolution": "720p"}}
    try:
        r = requests.post(f"{GEMINI}/models/{model}:predictLongRunning", headers=hdr, json=body, timeout=60)
    except requests.RequestException as e:
        return False, f"Could not reach Google ({type(e).__name__})."
    if r.status_code != 200:
        return False, _why(r)
    name = (r.json() or {}).get("name")
    if not name:
        return False, "Google did not start the video."
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(5 if wait > 30 else 0.2)
        try:
            p = requests.get(f"{GEMINI}/{name}", headers=hdr, timeout=60)
        except requests.RequestException:
            continue
        if p.status_code != 200:
            return False, _why(p)
        op = p.json()
        if not op.get("done"):
            continue
        if op.get("error"):
            return False, str((op["error"] or {}).get("message") or "Google could not make this video.")[:200]
        resp = (op.get("response") or {}).get("generateVideoResponse") or op.get("response") or {}
        samples = resp.get("generatedSamples") or resp.get("generatedVideos") or []
        if not samples:
            return False, "Google refused this scene (its safety filter). A picture with camera movement is used instead."
        uri = ((samples[0].get("video") or {}).get("uri")) or ""
        if not uri:
            return False, "Google sent no video."
        try:
            d = requests.get(uri, headers=hdr, timeout=300, stream=True)
            if d.status_code != 200:
                return False, _why(d)
            with open(out, "wb") as f:
                for chunk in d.iter_content(1 << 20):
                    f.write(chunk)
        except requests.RequestException as e:
            return False, f"The video could not be downloaded ({type(e).__name__})."
        return (True, "") if out.is_file() and out.stat().st_size > 1000 else (False, "The downloaded video was empty.")
    return False, "Google took too long to make this video."


def _why(r) -> str:
    try:
        msg = ((r.json() or {}).get("error") or {}).get("message") or ""
    except Exception:
        msg = ""
    if r.status_code in (401, 403):
        return "Google refused the key for video (a paid plan with video turned on is needed). " + msg[:120]
    if r.status_code == 429:
        return "Google says the video allowance is used up for now (too many requests or the daily limit)."
    if r.status_code == 404:
        return "That Veo model is not available to this key."
    return f"Google said {r.status_code}. {msg[:140]}"


# ---------------------------------------------------------------- the voice
def voice_for(genre: str, chosen: str = "") -> str:
    return chosen if re.fullmatch(r"en-[A-Za-z]{2}-\w+Neural", chosen or "") else VOICES.get(genre, "en-US-GuyNeural")


async def _tts(text: str, voice: str, out: Path) -> List[Dict]:
    import edge_tts
    words: List[Dict] = []
    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append({"word": chunk["text"], "start": s, "end": s + chunk["duration"] / 1e7})
    return words


class Words(list):
    """The words with their times, and which voice made them (`engine`: azure or kokoro, for the usage report) and why the better voice was not used (`note`)."""
    engine = "kokoro"
    note = ""


def speak(text: str, voice: str, out: Path, mood: str = "calm") -> List[Dict]:
    """Narration as an mp3 and the time of every word. With an Azure Speech key the narrator ACTS the scene's mood (scared, sad, excited ...); without one, or if Azure does not answer,
    the free voice on this computer (Kokoro) is used. The Microsoft read-aloud connection is not used (it is refused and not allowed commercially). Raises RuntimeError when no voice works."""
    from app.engine import azure_tts, kokoro_tts
    words, engine, note = None, "kokoro", ""
    if azure_tts.configured() and (os.environ.get("STORY_VOICE_ENGINE") or "auto").lower() != "kokoro":
        try:
            words, engine = azure_tts.synthesize(text, voice, out, mood), "azure"
        except azure_tts.Unavailable as e:
            note = f"The emotional voice was not used ({e}) so the free voice was used."
        except Exception as e:
            note = f"The emotional voice was not used ({type(e).__name__}) so the free voice was used."
    if words is None:
        try:
            words = kokoro_tts.synthesize(text, voice, out)
        except kokoro_tts.Unavailable as e:
            raise RuntimeError(str(e)) from e
        except Exception as e:
            raise RuntimeError(f"The narrator voice could not be made ({type(e).__name__}). Try again in a minute.") from e
    if not out.is_file() or out.stat().st_size < 500 or not words:
        raise RuntimeError("The narrator voice came back empty. Try again.")
    w = Words(words)
    w.engine, w.note = engine, note
    return w


def duration(path: Path) -> float:
    try:
        return float(subprocess.check_output([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], timeout=60).decode().strip() or 0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------- one finished scene
def build_scene(video: Path, narration: Path, words: List[Dict], seconds: float, out: Path, captions: bool = True) -> Path:
    """The moving picture, the voice and the captions as one 9:16 file. The video is cut or its last picture held so that it lasts exactly `seconds`
    (the voice plus a short breath); a video model's own sound is not used."""
    from app.engine.subtitles import generate_ass_from_words
    from app.engine.video_processor import escape_ffmpeg_path, safe_name
    dur = max(1.0, float(seconds))
    vdur = duration(video)
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},noise=alls=6:allf=t"      # a little film grain so it does not look like a clean slideshow
    if vdur and vdur < dur:                                       # a 4 or 6 second clip for a longer scene: hold the last picture
        vf += f",tpad=stop_mode=clone:stop_duration={dur - vdur + 0.1:.2f}"
    ass = None
    if captions and words:
        ass = TEMP_DIR / f"{safe_name(out.stem)}_story.ass"
        ass.parent.mkdir(parents=True, exist_ok=True)
        generate_ass_from_words(words, ass)
        vf += f",ass='{escape_ffmpeg_path(ass)}'"
    try:
        subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(narration), "-vf", vf + ",format=yuv420p",
                        "-af", f"aformat=channel_layouts=stereo,apad=pad_dur={dur:.2f}", "-map", "0:v:0", "-map", "1:a:0", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)], check=True, timeout=900)
    finally:
        if ass:
            ass.unlink(missing_ok=True)
    return out
