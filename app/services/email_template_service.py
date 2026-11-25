"""Email templates: the owner decides how the emails members receive look and read.

Every notification email is built from a small template: a subject, a heading, the message, the button label, a footer and the button colour.
The owner edits one template for ALL emails and may override any field for one kind of email (a different subject for "video ready", ...).
A field left empty falls back to the template for all emails, and that falls back to the studio's standard wording.
Words in curly brackets are replaced when the email is sent:  {title}  {body}  {name}  {link}.
"""
import html
import re
from typing import Dict, List, Optional, Tuple

FIELDS = [   # key, label, help, longest allowed, big box?
    ("subject", "Subject line", "The line members see in their inbox.", 150, False),
    ("heading", "Heading", "The big line at the top of the email.", 150, False),
    ("message", "Message", "The text under the heading. Keep {body} in it to show what happened.", 1500, True),
    ("button", "Button label", "The text on the button that opens the studio.", 40, False),
    ("footer", "Footer", "Small grey text at the bottom.", 300, True),
    ("color", "Button colour", "A colour like #ff7a18.", 7, False),
]
KEYS = [f[0] for f in FIELDS]
PLACEHOLDERS = ["{title}", "{body}", "{name}", "{link}"]
STANDARD = {"subject": "Clip Studio: {title}", "heading": "{title}", "message": "{body}", "button": "Open Clip Studio",
            "footer": "You can change which emails you get in Profile -> Notifications.", "color": "#ff7a18"}
_DOC = "email_templates"


def _saved() -> Dict:
    try:
        from app.models import System
        return System.find_one(id=_DOC) or {}
    except Exception:
        return {}


def kinds() -> List[Dict]:
    from app.services import notification_service as notes
    return [{"id": k, "name": v[0]} for k, v in notes.KINDS.items()]


def _clean(fields: Dict) -> Dict:
    out = {}
    for key, _label, _help, limit, _big in FIELDS:
        if key not in (fields or {}):
            continue
        v = str(fields.get(key) or "").replace("\r", "").strip()
        if key != "message" and key != "footer":
            v = " ".join(v.split())
        if key == "color" and v and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("The button colour must look like #ff7a18.")
        if len(v) > limit:
            raise ValueError(f"'{key}' is too long (the limit is {limit} characters).")
        out[key] = v
    return out


def overview() -> Dict:
    d = _saved()
    return {"fields": [{"k": k, "label": lb, "help": hp, "max": mx, "big": bg} for k, lb, hp, mx, bg in FIELDS], "standard": STANDARD, "placeholders": PLACEHOLDERS,
            "kinds": kinds(), "default": d.get("default") or {}, "by_kind": d.get("by_kind") or {}}


def _scope_key(scope: str) -> str:
    if scope in ("", "default", None):
        return "default"
    if scope not in {k["id"] for k in kinds()}:
        raise ValueError("That kind of email does not exist.")
    return "by_kind." + scope


def save(scope: str, fields: Dict) -> Dict:
    from app.models import System
    key = _scope_key(scope)
    System.set_fields(_DOC, {key: _clean(fields)}, upsert=True)
    return overview()


def reset(scope: str) -> Dict:
    from app.models import System
    System.set_fields(_DOC, {_scope_key(scope): {}}, upsert=True)
    return overview()


def effective(kind: str, override: Optional[Dict] = None, saved: Optional[Dict] = None) -> Dict:
    """The six fields for one kind of email: its own, else the all-emails template, else the standard wording."""
    d = saved if saved is not None else _saved()
    out = dict(STANDARD)
    for layer in (d.get("default") or {}, (d.get("by_kind") or {}).get(kind) or {}, override or {}):
        for k in KEYS:
            if str(layer.get(k) or "").strip():
                out[k] = str(layer[k]).strip()
    return out


def _fill(text: str, vals: Dict[str, str], escape: bool) -> str:
    def sub(m):
        v = vals.get(m.group(1), m.group(0))
        return html.escape(v) if escape else v
    return re.sub(r"\{(title|body|name|link)\}", sub, text)


def render(kind: str, title: str, body: str, name: str, link: str, override: Optional[Dict] = None) -> Tuple[str, str, str]:
    """(subject, plain text, html) for one email. Member data is always escaped in the HTML."""
    t = effective(kind, override)
    vals = {"title": title or "", "body": body or "", "name": name or "", "link": link or ""}
    subject = " ".join(_fill(t["subject"], vals, False).split())[:200]
    heading, message, footer = (_fill(t[k], vals, False) for k in ("heading", "message", "footer"))
    text = f"{heading}\n\n{message}\n\n{t['button']}: {link}\n\n{footer}"
    color = t["color"] if re.fullmatch(r"#[0-9a-fA-F]{6}", t["color"]) else STANDARD["color"]
    paras = "".join(f'<p style="margin:0 0 12px">{_fill(p, vals, True)}</p>' for p in t["message"].split("\n") if p.strip())
    page = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;color:#1a2030"><h2 style="margin:0 0 8px">{_fill(t["heading"], vals, True)}</h2>'
            f'{paras}<p style="margin:8px 0 16px"><a href="{html.escape(link, quote=True)}" style="display:inline-block;padding:12px 22px;background:{color};color:#fff;'
            f'text-decoration:none;border-radius:8px;font-weight:600">{html.escape(t["button"])}</a></p>'
            f'<p style="color:#8d98ad;font-size:12px;margin-top:20px">{_fill(t["footer"], vals, True)}</p></div>')
    return subject, text, page
