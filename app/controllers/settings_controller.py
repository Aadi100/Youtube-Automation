"""Controller (the C of MVC): settings endpoints."""
import os
import re
from pathlib import Path
from urllib.parse import unquote

from flask import Blueprint

from app.config import MUSIC_DIR, TEMP_DIR
from app.http import OWNER_ONLY, register
from app.runtime import DEFAULTS, MAX_UPLOAD, MUSIC_EXT, SETTINGS
from app.services import notify_service as notify
from app.services.voice_service import list_voices
from app.utils.envfile import read_env, write_env


def h_voices(h):
    h.send_json(200, list_voices())


def h_voice_preview(h):
    vid = h.q.get("voice", "")
    if vid not in {v["id"] for v in list_voices()}:
        return h.send_json(404, {"error": "unknown voice"})
    f = TEMP_DIR / f"voice_preview_{vid}.mp3"
    if not f.exists():
        import asyncio

        import edge_tts
        TEMP_DIR.mkdir(exist_ok=True)
        asyncio.run(edge_tts.Communicate("Wait, did you see that? This is how I would narrate your next clip.", vid).save(str(f)))
    body = f.read_bytes()
    h.send_response(200)
    h.send_header("Content-Type", "audio/mpeg")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def h_email_test(h):
    ok, msg = notify.send_mail("Clip Studio test email",
                               "If you can read this, email notifications work. ✅\n\nClip Studio")
    h.send_json(200 if ok else 400, {"ok": ok, "message": msg} if ok else {"error": msg})


def h_settings(h):
    env = read_env()
    h.send_json(200, {k: ({"secret": True, "set": bool(env.get(k))} if secret
                          else {"secret": False, "value": env.get(k) or DEFAULTS.get(k, "")})
                      for k, secret in SETTINGS.items()})


def h_settings_put(h):
    data, upd = h.body_json(), {}
    for k, v in data.items():
        if k not in SETTINGS:
            raise ValueError(f"unknown setting {k}")
        v = str(v).strip()
        if "\n" in v or "\r" in v:
            raise ValueError("no line breaks allowed")
        if SETTINGS[k] and not v:
            continue  # blank secret field = keep current
        upd[k] = v
    if upd:
        write_env(upd)
        os.environ.update(upd)          # the running studio uses the new keys at once (the file alone is only read at start-up)
        if "YTDLP_PROXY" in upd:
            from app.engine import yt_access
            yt_access.clear_block()     # a new proxy deserves a fresh try
    h_settings(h)


def h_claude_models(h):
    from app.engine import claude_util
    h.send_json(200, {"models": claude_util.list_models(force=h.q.get("refresh") == "1"), "default": claude_util.DEFAULT_MODEL})


# ---- YouTube access: what lets this server download from YouTube (Settings -> YouTube access)
def h_ytaccess(h):
    from app.engine import yt_access
    h.send_json(200, yt_access.status())


def h_ytaccess_proxy_delete(h):
    from app.engine import yt_access
    yt_access.clear_proxy()
    h.send_json(200, yt_access.status())


def h_ytaccess_test(h):
    from app.engine import yt_access
    h.send_json(200, {**yt_access.test(), "status": yt_access.status()})


# ---- Email templates: how the emails members receive look and read (Settings -> Email templates)
def h_tpl(h):
    from app.services import email_template_service as T
    h.send_json(200, T.overview())


def h_tpl_put(h):
    from app.services import email_template_service as T
    b = h.body_json()
    h.send_json(200, T.save(b.get("scope") or "default", b.get("fields") or {}))


def h_tpl_delete(h):
    from app.services import email_template_service as T
    h.send_json(200, T.reset(h.q.get("scope") or "default"))


def h_tpl_preview(h):
    """What an email would look like with the fields typed now (nothing is saved or sent)."""
    from app.services import email_template_service as T
    b = h.body_json()
    kind = b.get("scope") if b.get("scope") not in (None, "", "default") else ""
    T._clean(b.get("fields") or {})
    subject, text, page = T.render(kind, "Your video is ready", "Your Short \"Epic clutch\" was made and is waiting for your check.", "Alex", "https://example.com/app#/videos", b.get("fields") or {})
    h.send_json(200, {"subject": subject, "html": page, "text": text})


def h_tpl_test(h):
    """Send the owner one example email with this template (it is not charged)."""
    from app.models import User
    from app.services import email_template_service as T
    from app.models import oid
    b = h.body_json()
    kind = b.get("scope") if b.get("scope") not in (None, "", "default") else ""
    cfg = notify.get_cfg()
    me = User.find_one(id=oid(h.uid))
    cfg["to"] = (me or {}).get("email") or cfg["to"]
    subject, text, page = T.render(kind, "Your video is ready", "This is an example email.", (me or {}).get("name") or "", cfg["base_url"] + "/app", b.get("fields") or {})
    ok, msg = notify.send_mail(subject, text, page, None, cfg)
    h.send_json(200 if ok else 400, {"ok": ok, "message": msg} if ok else {"error": msg})


# ---- Best thumbnails: is Cloudflare (FLUX) + Gemini working? (Settings -> Accounts & keys -> Best thumbnails)
def h_thumbbest(h):
    from app.engine import thumb_best
    h.send_json(200, thumb_best.status())


def h_thumbbest_test(h):
    from app.engine import thumb_best
    h.send_json(200, {**thumb_best.test(), "status": thumb_best.status()})


# ---- AI models: which AI does which job, and its backup (Settings -> AI models)
def h_airoutes(h):
    from app.engine import ai_routes
    h.send_json(200, ai_routes.overview())


def h_airoutes_put(h):
    from app.engine import ai_routes
    h.send_json(200, ai_routes.save(h.body_json().get("routes") or {}))


def h_airoutes_delete(h):
    from app.engine import ai_routes
    h.send_json(200, ai_routes.reset(h.q.get("task") or ""))


def h_airoutes_test(h):
    from app.engine import ai_routes
    h.send_json(200, {"results": ai_routes.test(h.body_json().get("task") or "")})


def h_music(h):
    h.send_json(200, [{"name": p.name, "mb": round(p.stat().st_size / 1e6, 1)}
                      for p in sorted(MUSIC_DIR.iterdir()) if p.suffix.lower() in MUSIC_EXT])


def _music_name(raw: str) -> str:
    name = Path(unquote(raw or "")).name
    if Path(name).suffix.lower() not in MUSIC_EXT or not re.fullmatch(r"[\w .()\-]+", name):
        raise ValueError("file must be mp3/wav/m4a/ogg/flac with a plain name")
    return name


def h_music_upload(h):
    name = _music_name(h.q.get("name", ""))
    n = int(h.headers.get("Content-Length") or 0)
    if not 0 < n <= MAX_UPLOAD:
        raise ValueError("file empty or larger than 60 MB")
    with open(MUSIC_DIR / name, "wb") as f:
        left = n
        while left > 0 and (chunk := h.rfile.read(min(1 << 20, left))):
            f.write(chunk)
            left -= len(chunk)
    h.send_json(200, {"ok": True, "name": name})


def h_music_delete(h):
    p = MUSIC_DIR / _music_name(h.q.get("name", ""))
    p.unlink(missing_ok=True)
    h.send_json(200, {"ok": True})


ROUTES = [
    (r"/api/voices", "GET", h_voices),
    (r"/api/voices/preview", "GET", h_voice_preview),
    (r"/api/email/test", "POST", h_email_test),
    (r"/api/settings", "GET", h_settings),
    (r"/api/settings", "PUT", h_settings_put),
    (r"/api/claude/models", "GET", h_claude_models),
    (r"/api/yt-access", "GET", h_ytaccess),
    (r"/api/yt-access/proxy", "DELETE", h_ytaccess_proxy_delete),
    (r"/api/yt-access/test", "POST", h_ytaccess_test),
    (r"/api/email-templates", "GET", h_tpl),
    (r"/api/email-templates", "PUT", h_tpl_put),
    (r"/api/email-templates", "DELETE", h_tpl_delete),
    (r"/api/email-templates/preview", "POST", h_tpl_preview),
    (r"/api/email-templates/test", "POST", h_tpl_test),
    (r"/api/thumb-best", "GET", h_thumbbest),
    (r"/api/thumb-best/test", "POST", h_thumbbest_test),
    (r"/api/ai-routes", "GET", h_airoutes),
    (r"/api/ai-routes", "PUT", h_airoutes_put),
    (r"/api/ai-routes", "DELETE", h_airoutes_delete),
    (r"/api/ai-routes/test", "POST", h_airoutes_test),
    (r"/api/music", "GET", h_music),
    (r"/api/music", "POST", h_music_upload),
    (r"/api/music", "DELETE", h_music_delete),
]
OWNER_ONLY.update({h_claude_models, h_settings,h_settings_put, h_email_test, h_music_upload, h_music_delete,
                   h_ytaccess, h_ytaccess_proxy_delete, h_ytaccess_test, h_tpl, h_tpl_put, h_tpl_delete, h_tpl_preview, h_tpl_test, h_thumbbest, h_thumbbest_test, h_airoutes, h_airoutes_put, h_airoutes_delete, h_airoutes_test})
bp = Blueprint("settings", __name__)
register(bp, ROUTES)
