"""Getting YouTube to talk to this server.

YouTube refuses many cloud / datacenter addresses with "Sign in to confirm you're not a bot". The studio handles that itself:

  * it recognises the refusal (YouTubeBlocked) and stops the run at once with a clear message (it never quietly switches to another
    source, and does not waste minutes on clips that cannot download); the refusal is remembered in the database so Settings can show it,
  * the owner sets a PROXY in Settings -> YouTube access: an HTTP proxy with a home-type address (an "ISP" / residential proxy). YouTube
    trusts such an address, so nothing has to be signed in and nothing expires,
  * a Test button shows whether it works now, and the owner is told (dashboard + email, at most every 6 hours) when it stops working.

"""
import contextlib
import os
import re
import time
from typing import Dict, Iterator, List, Optional

from app.utils.envfile import read_env

BLOCK_MINUTES = 30                      # how long Settings keeps showing "blocked" after a refusal (every new run still tries YouTube again)
TEST_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # the first video ever uploaded: always there
_BLOCK = re.compile(r"sign in to confirm|not a bot|confirm you.{0,4}re not|HTTP Error 429|Too Many Requests", re.I)


class YouTubeBlocked(RuntimeError):
    """YouTube refused this server's download request (not a problem with one particular video)."""


OWNER_MESSAGE = ("YouTube is blocking this server (it asks to sign in to prove it is not a bot). Open Settings -> YouTube access and add or check "
                 "the proxy (an http:// residential / ISP proxy).")
MEMBER_MESSAGE = "We could not get a clip from YouTube right now. Nothing was charged. Please try again later."


def looks_blocked(stderr: str) -> bool:
    return "[youtube" in (stderr or "").lower() and bool(_BLOCK.search(stderr or ""))


def uses_youtube(args) -> bool:
    return any(isinstance(a, str) and ("youtube.com" in a or "youtu.be" in a or a.startswith("ytsearch")) for a in args)


# --------------------------------------------------------------------------------- the proxy
def proxy() -> str:
    return (os.environ.get("YTDLP_PROXY") or read_env().get("YTDLP_PROXY", "")).strip()


@contextlib.contextmanager
def ytdlp_args() -> Iterator[List[str]]:
    """Extra yt-dlp options for a YouTube call: the proxy, when there is one."""
    p = proxy()
    yield ["--proxy", p] if p else []


def ffmpeg_proxy_args() -> List[str]:
    """ffmpeg reads YouTube live streams itself (yt-dlp only finds the link), and a YouTube link only works from the address that asked for it:
    so ffmpeg must use the same proxy. ffmpeg understands HTTP proxies only (not SOCKS), so an http:// proxy is the one to rent."""
    p = proxy()
    return ["-http_proxy", p] if p.lower().startswith(("http://", "https://")) else []


def requests_proxies() -> Optional[Dict[str, str]]:
    p = proxy()
    return {"http": p, "https": p} if p.lower().startswith(("http://", "https://")) else None


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
        from app.engine import clipcfg
        if "youtube" not in clipcfg.sources():       # the running account switched YouTube off: a refusal is not news to anyone
            return
        from app.models import System, User, UserPrefs
        sent = float(((System.find_one(id="alerts") or {}).get("sent") or {}).get("ytaccess", 0))
        if time.time() - sent < 6 * 3600:
            return
        System.set_fields("alerts", {"sent.ytaccess": time.time()}, upsert=True)
        if proxy():
            title, text = ("YouTube is refusing the server",
                           "YouTube refused the server even through the proxy. The proxy may have expired, run out of data, or been blocked. "
                           "Open Settings -> YouTube access, check it with the Test button and renew or replace it. "
                           "Videos that need YouTube clips fail until then.")
        else:
            title, text = ("YouTube is refusing the server",
                           "YouTube is asking this server to sign in (a bot check), so videos that need YouTube clips fail. "
                           "Open Settings -> YouTube access, add a proxy (an http:// residential / ISP proxy) and press Test.")
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
    """Seconds until Settings stops showing 'blocked' (0 = not blocked)."""
    left = float(_doc().get("blocked_until") or 0) - time.time()
    return int(left) if left > 0 else 0


def status() -> Dict:
    d = _doc()
    px = proxy()
    return {"blocked": blocked_seconds() > 0, "blocked_minutes": (blocked_seconds() + 59) // 60,
            "last_error": d.get("last_error") or "", "last_ok": d.get("last_ok") or 0,
            "has_proxy": bool(px), "proxy_host": re.sub(r"^[a-z0-9+]+://([^@/]*@)?", "", px).split("/")[0] if px else "",
            "proxy_ok_type": (not px) or px.lower().startswith(("http://", "https://"))}


# --------------------------------------------------------------------------------- the owner's controls
def clear_proxy() -> None:
    from app.utils.envfile import write_env
    write_env({"YTDLP_PROXY": ""})
    os.environ.pop("YTDLP_PROXY", None)
    clear_block()


def test() -> Dict:
    """Is the proxy reachable, and does YouTube answer through it? Says what happened in plain words."""
    from app.engine import discovery
    px = proxy()
    seen_ip = ""
    if px:
        if not px.lower().startswith(("http://", "https://")):
            return {"ok": False, "blocked": False, "message": "The proxy must be an http:// address (SOCKS does not work for cutting clips)."}
        try:                                  # first the proxy itself: a wrong password or an address that is not allowed gives a clear answer here
            import requests
            r = requests.get("https://api.ipify.org", proxies={"http": px, "https": px}, timeout=20)
            if r.status_code != 200:
                raise RuntimeError(f"answered {r.status_code}")
            seen_ip = r.text.strip()[:45]
        except Exception as e:
            why = "wrong user name or password" if "407" in str(e) else "no answer"
            return {"ok": False, "blocked": False,
                    "message": f"The proxy did not answer ({why}). Check the address, port, user name and password, that this server's IP is allowed in your "
                               f"proxy account, and that it has not expired. ({type(e).__name__})"}
    try:
        discovery._ytdlp("-J", "--no-playlist", "--skip-download", TEST_VIDEO, capture=True, timeout=75)
    except YouTubeBlocked:
        if px:
            msg = ("YouTube refuses this server even through the proxy" + (f" ({seen_ip})" if seen_ip else "") +
                   ". Try another address from the provider, or ask them for a residential address in another city.")
        else:
            msg = "YouTube refuses this server. Add a proxy below, then test again."
        return {"ok": False, "blocked": True, "message": msg}
    except Exception as e:
        return {"ok": False, "blocked": False, "message": "The test could not finish: " + str(e)[:240]}
    note_ok()
    return {"ok": True, "message": "YouTube answered" + (f" through your proxy ({seen_ip})." if px else ": downloads from this server work.")}
