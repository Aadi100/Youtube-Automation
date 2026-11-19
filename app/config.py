import os
import shutil
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent      # the project folder (one above app/)
_UID = os.environ.get("GTA6_USER_ID", "")   # set by the server for each job: every member's files live in their own folders
INPUT_DIR = BASE_DIR / "inputs" / _UID if _UID else BASE_DIR / "inputs"
OUTPUT_DIR = BASE_DIR / "outputs"
SHORTS_OUTPUT_DIR = OUTPUT_DIR / "shorts" / _UID if _UID else OUTPUT_DIR / "shorts"
COMPILATIONS_OUTPUT_DIR = OUTPUT_DIR / "compilations" / _UID if _UID else OUTPUT_DIR / "compilations"
TEMP_DIR = BASE_DIR / "temp" / os.environ.get("GTA6_JOB_ID", "") if os.environ.get("GTA6_JOB_ID") else BASE_DIR / "temp"
STATE_DIR = BASE_DIR / "state"
MUSIC_DIR = BASE_DIR / "music"   # put royalty-free .mp3/.wav tracks here (YouTube Audio Library etc.)

for directory in [INPUT_DIR, OUTPUT_DIR, SHORTS_OUTPUT_DIR, COMPILATIONS_OUTPUT_DIR, TEMP_DIR, STATE_DIR, MUSIC_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Secrets / settings come from .env (never hardcode keys)
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "")
TWITCH_GAME_NAME = os.environ.get("TWITCH_GAME_NAME") or "Grand Theft Auto VI"
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_QUERY = os.environ.get("YOUTUBE_QUERY") or "GTA 6 gameplay stream highlights"
CONTACT_EMAIL =os.environ.get("CONTACT_EMAIL", "")
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.environ.get("MONGODB_DB", "gta6_studio")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
TTS_VOICE = os.environ.get("TTS_VOICE") or "en-US-GuyNeural"
# audience region: only clips from creators in these countries / broadcasting in these languages (no Asia)
LIVE_WATCH_MINUTES = float(os.environ.get("LIVE_WATCH_MINUTES") or 8)   # how long live streams are watched per scan
LIVE_STREAMS = int(float(os.environ.get("LIVE_STREAMS") or 4))        # how many live streams are watched at once
CLIP_COUNTRIES = {c.strip().upper() for c in (os.environ.get("CLIP_COUNTRIES") or
                  "US,CA,GB,IE,DE,FR,ES,IT,NL,BE,SE,NO,DK,FI,PL,PT,AT,CH,CZ,RO,GR,HU").split(",") if c.strip()}
CLIP_LANGUAGES = {c.strip().lower() for c in (os.environ.get("CLIP_LANGUAGES") or
                  "en,de,fr,it,nl,sv,da,no,fi,pl,pt,cs,ro,el,hu").split(",") if c.strip()}

# Locate FFmpeg and FFprobe
def get_ffmpeg_path():
    path = shutil.which("ffmpeg")
    if path:
        return path
    
    # Common Windows winget paths
    winget_base = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"))
    if winget_base.exists():
        matches = list(winget_base.glob("**/ffmpeg.exe"))
        if matches:
            return str(matches[0])
            
    # Program Files check
    for p in [r"C:\Program Files\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"]:
        if os.path.exists(p):
            return p
            
    return "ffmpeg"

def get_ffprobe_path():
    path = shutil.which("ffprobe")
    if path:
        return path
        
    winget_base = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"))
    if winget_base.exists():
        matches = list(winget_base.glob("**/ffprobe.exe"))
        if matches:
            return str(matches[0])
            
    for p in [r"C:\Program Files\ffmpeg\bin\ffprobe.exe", r"C:\ffmpeg\bin\ffprobe.exe"]:
        if os.path.exists(p):
            return p
            
    return "ffprobe"

FFMPEG_BIN = get_ffmpeg_path()
FFPROBE_BIN = get_ffprobe_path()

# Video Settings
FPS = 60
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
COMPILATION_WIDTH = 1920
COMPILATION_HEIGHT = 1080

# Audio Settings
YOUTUBE_LUFS_TARGET = -14.0
AUDIO_SAMPLE_RATE = 48000

# Subtitle Styling (Shorts - TikTok/Reels/Shorts High-CTR Style)
SUBTITLE_FONT_NAME = "Arial"
SUBTITLE_FONT_SIZE = int(float(os.environ.get("SUBTITLE_FONT_SIZE") or 80))   # on a 1080x1920 Short (22 was far too small)
PRIMARY_COLOR = "&H00FFFFFF"   # White (ASS format: &HAABBGGRR)
ACCENT_COLOR = "&H0000FFFF"    # Bright Yellow
OUTLINE_COLOR = "&H00000000"   # Black Outline
OUTLINE_WIDTH = 7
SHADOW_WIDTH = 3
