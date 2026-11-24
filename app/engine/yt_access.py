"""Getting YouTube to talk to this server.

YouTube refuses many cloud / datacenter addresses with "Sign in to confirm you're not a bot". The studio handles that itself:

  * it recognises the refusal (YouTubeBlocked) instead of treating every clip as a separate failure,
  * it stops the run at once with a clear message (it never quietly switches to another source, and does not waste minutes on
    clips that cannot download), and remembers the refusal (in the database) so Settings can show it,
  * the owner can give yt-dlp what YouTube accepts, from Settings -> YouTube access:
        - cookies of a signed-in browser (saved in state/youtube-cookies.txt, readable only by the studio), and / or
        - a proxy with a home or mobile address (YTDLP_PROXY),
  * a Test button shows whether it works now.
"""
import contextlib
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, Iterator, List

from app.config import STATE_DIR, TEMP_DIR
from app.utils.envfile import read_env

COOKIES = STATE_DIR / "youtube-cookies.txt"
BLOCK_MINUTES = 30                      # how long Settings keeps showing "blocked" after a refusal (every new run still tries YouTube again)
TEST_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # the first video ever uploaded: always there
_BLOCK = re.compile(r"sign in to confirm|not a bot|confirm you.{0,4}re not|HTTP Error 429|Too Many Requests", re.I)
_MAX_COOKIE_BYTES = 2_000_000


class YouTubeBlocked(RuntimeError):
    """YouTube refused this server's download request (not a problem with one particular video)."""


OWNER_MESSAGE = ("YouTube is blocking this server (it asks to sign in to prove it is not a bot). Open Settings -> YouTube access: "
                 "add the cookies of a signed-in browser, or a proxy.")
MEMBER_MESSAGE = "We could not get a clip from YouTube right now. Nothing was charged. Please try again later."


def looks_blocked(stderr: str) -> bool:
    return "[youtube" in (stderr or "").lower() and bool(_BLOCK.search(stderr or ""))


def uses_youtube(args) -> bool:
    return any(isinstance(a, str) and ("youtube.com" in a or "youtu.be" in a or a.startswith("ytsearch")) for a in args)


# --------------------------------------------------------------------------------- what is configured
def proxy() -> str:
    return (os.environ.get("YTDLP_PROXY") or read_env().get("YTDLP_PROXY", "")).strip()


def has_cookies() -> bool:
    try:
        return COOKIES.is_file() and COOKIES.stat().st_size > 50
    except OSError:
        return False


@contextlib.contextmanager
def ytdlp_args() -> Iterator[List[str]]:
    """Extra yt-dlp options. The cookie file is copied for each call: yt-dlp writes to it, and several videos run at once."""
    extra: List[str] = []
    tmp = None
    p = proxy()
    if p:
        extra += ["--proxy", p]
    if has_cookies():
        tmp = TEMP_DIR / f"ytck_{os.getpid()}_{time.time_ns()}.txt"
        try:
            shutil.copyfile(COOKIES, tmp)
            os.chmod(tmp, 0o600)
            extra += ["--cookies", str(tmp)]
        except OSError:
            tmp = None
    try:
        yield extra
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------------- what happened last (shared through the database)
def _doc() -> Dict:
    try:
        from app.models import System
        return System.find_one(id="yt_access") or {}
    except Exception:
        return {}


def _put(**fields) -> None:
    try:
        from app.models import System
        System.set_fields("yt_access", fields, upsert=True)
    except Exception:
        pass


def note_block(why: str = "") -> None:
    _put(blocked_until=time.time() + BLOCK_MINUTES * 60, last_error=(why or "")[:300], blocked_at=time.time())
    _ask_owner()


def _ask_owner() -> None:
    """Tell the owner (in the dashboard and by email) that YouTube is refusing the server and what to do. At most once every 6 hours,
    so a scheduled run that fails ten times does not send ten emails."""
    try:
        from app.models import System, User, UserPrefs
        sent = float(((System.find_one(id="alerts") or {}).get("sent") or {}).get("ytaccess", 0))
        if time.time() - sent < 6 * 3600:
            return
        System.set_fields("alerts", {"sent.ytaccess": time.time()}, upsert=True)
        if has_cookies():
            title, text = ("YouTube cookies need updating",
                           "YouTube is refusing this server again, so the saved cookies have expired. Sign in to YouTube in your browser with the same spare account, "
                           "export the cookies again (Get cookies.txt LOCALLY), and upload the new file in Settings -> YouTube access, then press Test. "
                           "Videos that need YouTube clips fail until then.")
        else:
            title, text = ("YouTube is refusing the server",
                           "YouTube is asking this server to sign in (a bot check), so videos that need YouTube clips fail. Open Settings -> YouTube access, "
                           "upload the cookies of a signed-in browser (or add a proxy) and press Test.")
        from app.services import notification_service as notes
        notes.notify_owner("system", title, text, "#/settings", "warn", key="sys-ytaccess")
        from app.services import notify_service as notify
        owner = User.find_one(role="owner")
        if owner and notify.configured():
            cfg = notify.get_cfg()
            cfg["to"] = UserPrefs.of(owner["_id"]).get("notify_to") or cfg["to"] or owner["email"]
            notify.send_mail("Clip Studio: " + title, text, None, None, cfg)
    except Exception as e:                   # an alert must never break the run that found the problem
        print(f"[YouTube access] could not alert the owner: {e}", flush=True)


def note_ok() -> None:
    _put(blocked_until=0, last_ok=time.time(), last_error="")


def clear_block() -> None:
    _put(blocked_until=0)


def blocked_seconds() -> int:
    """Seconds until YouTube is tried again (0 = not blocked)."""
    left = float(_doc().get("blocked_until") or 0) - time.time()
    return int(left) if left > 0 else 0


def status() -> Dict:
    d = _doc()
    age = None
    if has_cookies():
        age = int((time.time() - COOKIES.stat().st_mtime) // 86400)
    px = proxy()
    return {"blocked": blocked_seconds() > 0, "blocked_minutes": (blocked_seconds() + 59) // 60,
            "last_error": d.get("last_error") or "", "last_ok": d.get("last_ok") or 0,
            "has_cookies": has_cookies(), "cookies_age_days": age,
            "has_proxy": bool(px), "proxy_host": re.sub(r"^[a-z0-9+]+://([^@/]*@)?", "", px).split("/")[0] if px else ""}


# --------------------------------------------------------------------------------- the owner's controls
def save_cookies(text: str) -> None:
    text = (text or "").replace("\r\n", "\n").strip() + "\n"
    if len(text.encode("utf-8")) > _MAX_COOKIE_BYTES:
        raise ValueError("that file is too large to be a cookie file")
    rows = [l for l in text.splitlines() if l.strip() and (not l.startswith("#") or l.startswith("#HttpOnly_"))]
    good = [l for l in rows if len(l.split("\t")) >= 7]
    if not good:
        raise ValueError("this is not a cookies.txt file (it must be the Netscape format that the 'Get cookies.txt LOCALLY' extension saves)")
    if not any(re.search(r"(^|\.)youtube\.com\t|(^|\.)google\.com\t", l.split("\t")[0] + "\t") for l in good):
        raise ValueError("this file has no youtube.com / google.com cookies. Export them while you are on youtube.com and signed in")
    if not any(l.split("\t")[5] in ("SID", "__Secure-3PSID", "LOGIN_INFO", "SAPISID", "__Secure-1PSID") for l in good if len(l.split("\t")) >= 6):
        raise ValueError("the file has no signed-in cookies. Sign in to YouTube in that browser first, then export again")
    COOKIES.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOKIES.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(COOKIES)
    clear_block()


def delete_cookies() -> None:
    COOKIES.unlink(missing_ok=True)


def clear_proxy() -> None:
    from app.utils.envfile import write_env
    write_env({"YTDLP_PROXY": ""})
    os.environ.pop("YTDLP_PROXY", None)
    clear_block()


def test() -> Dict:
    """Ask YouTube for one public video the way the studio does, and say what happened in plain words."""
    from app.engine import discovery
    try:
        discovery._ytdlp("-J", "--no-playlist", "--skip-download", TEST_VIDEO, capture=True, timeout=75)
    except YouTubeBlocked:
        return {"ok": False, "blocked": True,
                "message": "YouTube still refuses this server" + (" even with your cookies." if has_cookies() else ".")
                           + (" Try fresh cookies (they expire), or a different proxy." if has_cookies() or proxy() else " Add cookies or a proxy below, then test again.")}
    except Exception as e:
        return {"ok": False, "blocked": False, "message": "The test could not finish: " + str(e)[:240]}
    note_ok()
    return {"ok": True, "message": "YouTube answered: downloads from this server work."}
