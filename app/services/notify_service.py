"""Email notifications over SMTP (configured on the dashboard Settings tab).

'Uploaded' emails contain an Approve button: it opens a confirmation page on this computer and,
when confirmed, publishes the video (Unlisted -> Public) through n8n.
"""
import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.utils.envfile import read_env


def get_cfg(env: Optional[Dict[str, str]] = None) -> Dict:
    e = env if env is not None else read_env()
    return {
        "host": e.get("SMTP_HOST", ""), "port": int(e.get("SMTP_PORT") or 587),
        "security": (e.get("SMTP_SECURITY") or "starttls").lower(),
        "user": e.get("SMTP_USER", ""), "password": e.get("SMTP_PASSWORD", ""),
        "from": e.get("SMTP_FROM") or e.get("SMTP_USER", ""), "to": e.get("NOTIFY_TO", ""),
        "base_url": (e.get("PUBLIC_BASE_URL") or "http://localhost:8765").rstrip("/"),
    }


def configured(cfg: Optional[Dict] = None) -> bool:
    c = cfg or get_cfg()
    return bool(c["host"] and c["from"] and c["to"])


def send_mail(subject: str, text: str, html_body: Optional[str] = None, image: Optional[Path] = None,
              cfg: Optional[Dict] = None) -> Tuple[bool, str]:
    """Send one email. Returns (ok, message) - never raises."""
    c = cfg or get_cfg()
    if not configured(c):
        return False, "Email is not configured (host, From and To are required)."
    try:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, formataddr(("Clip Studio", c["from"])), c["to"]
        msg.set_content(text)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
            if image and image.is_file():
                msg.get_payload()[1].add_related(image.read_bytes(), "image", "jpeg", cid="<thumb>")
        ctx = ssl.create_default_context()
        if c["security"] == "ssl":
            s = smtplib.SMTP_SSL(c["host"], c["port"], timeout=25, context=ctx)
        else:
            s = smtplib.SMTP(c["host"], c["port"], timeout=25)
        with s:
            if c["security"] == "starttls":
                s.starttls(context=ctx)
            if c["user"] and c["password"]:
                s.login(c["user"], c["password"])
            s.send_message(msg)
        return True, f"Sent to {c['to']}."
    except smtplib.SMTPAuthenticationError:
        return False, "The mail server rejected the username/password (Gmail needs an App Password)."
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


def _button(url: str, label: str, color: str) -> str:
    return (f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;padding:12px 22px;margin:6px 8px 6px 0;'
            f'background:{color};color:#fff;text-decoration:none;border-radius:8px;font-weight:600">{html.escape(label)}</a>')


def uploaded_email(video: Dict, approve_url: str, cfg: Optional[Dict] = None) -> Tuple[bool, str]:
    title, game = video.get("title", "Video"), video.get("game_name") or ""
    yt = video.get("youtube_url") or ""
    text = (f"Uploaded to YouTube (Unlisted): {title}\nGame: {game}\n\nWatch / check it: {yt}\n"
            f"Copyright notices: open YouTube Studio > Content and look at the video's Checks.\n\n"
            f"Approve and publish (make it Public): {approve_url}\n"
            f"Decline (never publish it): {approve_url}?decline=1\n"
            f"(The Approve link only works on the computer that runs Clip Studio.)\n\n"
            f"Do nothing to keep it Unlisted.")
    body = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;color:#1a2030">
      <h2 style="margin:0 0 6px">Ready to check ✅</h2>
      <p style="margin:0 0 12px;color:#5d6879">{html.escape(game)} · uploaded as <b>Unlisted</b></p>
      <img src="cid:thumb" alt="" style="max-width:260px;border-radius:8px;display:block;margin-bottom:12px">
      <p style="font-size:16px"><b>{html.escape(title)}</b></p>
      <p>{_button(yt, "Watch on YouTube", "#3a4256")}{_button(approve_url, "Approve & publish", "#d6165f")}{_button(approve_url + "?decline=1", "Decline", "#6b7385")}</p>
      <p style="color:#5d6879;font-size:13px">Before approving, open YouTube Studio → Content and check the video's
      <b>Checks</b> for copyright notices. Ignore this email to keep it Unlisted, or press Decline to reject it.<br>
      The Approve button works on the computer that runs Clip Studio.</p></div>"""
    thumb = Path(video.get("thumbnail_path", "")) if video.get("thumbnail_path") else None
    return send_mail(f"✅ Ready to check: {title[:80]}", text, body, thumb, cfg)


def failed_email(what: str, detail: str, cfg: Optional[Dict] = None) -> Tuple[bool, str]:
    return send_mail(f"❌ Clip Studio failed: {what}", f"{what} failed.\n\n{detail}\n\nOpen the dashboard (Create tab) for the full log.",
                     None, None, cfg)
