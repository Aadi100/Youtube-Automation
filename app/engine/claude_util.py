"""Claude (Anthropic) for the "High" thumbnail level: it LOOKS at frames and plans the thumbnail. Claude cannot draw pictures,
so it acts as the art director; the picture itself is still drawn by Gemini (or the video's own frame is used).

The key is ANTHROPIC_API_KEY (Settings -> Accounts & keys). Every call writes a usage record with the tokens Anthropic reports,
so the bill follows real usage like every other AI call. A failed call is recorded as failed and is never billed.
"""
import base64
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

API = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
_last = threading.local()


def ready() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def model() -> str:
    return (os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL).strip()


KNOWN_MODELS = [("claude-fable-5-2", "Claude Fable 5.2"), ("claude-opus-5-5", "Claude Opus 5.5"), ("claude-sonnet-5-5", "Claude Sonnet 5.5"), ("claude-haiku-5-5", "Claude Haiku 5.5")]
_models_cache: Dict = {"at": 0.0, "key": "", "list": []}


def research_model() -> str:
    return (os.environ.get("ANTHROPIC_RESEARCH_MODEL") or model()).strip()


def list_models(force: bool = False) -> List[Dict]:
    """Every model this Claude key may use, asked live from Anthropic (cached 10 minutes). Without a key, or if Anthropic cannot be reached, the models we know of."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    c = _models_cache
    if not force and c["list"] and c["key"] == key and time.time() - c["at"] < 600:
        return c["list"]
    out: List[Dict] = []
    if key:
        try:
            after = ""
            for _ in range(5):
                r = requests.get("https://api.anthropic.com/v1/models", params={"limit": 100, **({"after_id": after} if after else {})},
                                 headers={"x-api-key": key, "anthropic-version": VERSION}, timeout=20)
                if r.status_code != 200:
                    break
                d = r.json()
                out += [{"id": m["id"], "name": m.get("display_name") or m["id"]} for m in d.get("data") or [] if isinstance(m, dict) and m.get("id")]
                if not d.get("has_more"):
                    break
                after = d.get("last_id") or ""
                if not after:
                    break
        except (requests.RequestException, ValueError):
            out = []
    live = bool(out)
    if not out:
        out = [{"id": i, "name": n} for i, n in KNOWN_MODELS]
    for cur in (os.environ.get("ANTHROPIC_MODEL"), os.environ.get("ANTHROPIC_RESEARCH_MODEL")):      # a model typed earlier stays selectable
        if cur and not any(m["id"] == cur for m in out):
            out.append({"id": cur, "name": cur})
    out = [{**m, "live": live} for m in out]
    if live:
        c.update(at=time.time(), key=key, list=out)
    return out


def last_usage() -> Tuple[int, int]:
    return getattr(_last, "usage", (0, 0))


def image_block(path: Path, longest: int = 512) -> Dict:
    """A picture for Claude, shrunk first (picture tokens grow with size)."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((longest, longest))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}


def ask(task: str, system: str, content: List[Dict], max_tokens: int = 700, timeout: int = 60) -> str:
    """One Claude call. Returns the answer text; raises RuntimeError with a plain message. Records the real token usage."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("no Claude key")
    body = {"model": model(), "max_tokens": int(max_tokens), "temperature": 0.4, "system": system, "messages": [{"role": "user", "content": content}]}
    last = ""
    for attempt in range(2):
        try:
            r = requests.post(API, headers={"x-api-key": key, "anthropic-version": VERSION, "content-type": "application/json"}, json=body, timeout=timeout)
        except requests.RequestException as e:
            last = type(e).__name__
            continue
        if r.status_code == 200:
            d = r.json()
            u = d.get("usage") or {}
            tin, tout = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
            _last.usage = (tin, tout)
            try:
                from app.engine import ai_saver
                from app.models import UsageEvent
                UsageEvent.record("llm", provider="claude", task=task, tokens_in=tin, tokens_out=tout)
                ai_saver.spend(tin + tout)
            except Exception:
                pass
            text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()
            if not text:
                raise RuntimeError("Claude gave an empty answer")
            return text
        last = f"HTTP {r.status_code}"
        if r.status_code in (400, 401, 403, 404):           # a wrong key / model name will not get better by trying again
            try:
                last += ": " + (r.json().get("error") or {}).get("message", "")[:120]
            except Exception:
                pass
            break
        time.sleep(3)
    raise RuntimeError(f"Claude failed ({last})")


def ask_json(task: str, system: str, content: List[Dict], max_tokens: int = 700) -> Dict:
    text = ask(task, system + " Reply with one JSON object and nothing else.", content, max_tokens)
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise RuntimeError("Claude did not answer in the expected format")
    return json.loads(text[a:b + 1])


SEARCH_TOOL = "web_search_20250305"


def ask_with_search(task: str, system: str, user_text: str, max_searches: int = 10, max_tokens: int = 6000, timeout: int = 240, model_id: str = "") -> Tuple[str, List[str], int]:
    """Claude researching on the open web with Anthropic's web search tool. Returns (answer text, the web addresses it really opened or cited, searches made).
    The sources are returned so the caller can check every claim against pages that were really read. Records the real usage (tokens and searches)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("no Claude key")
    messages = [{"role": "user", "content": user_text}]
    tools = [{"type": SEARCH_TOOL, "name": "web_search", "max_uses": int(max_searches)}]
    tin = tout = searches = 0
    sources: List[str] = []
    texts: List[str] = []
    for turn in range(6):                                   # a long research turn is paused by the service and has to be continued
        body = {"model": (model_id or research_model()).strip(), "max_tokens": int(max_tokens), "system": system, "messages": messages, "tools": tools}
        try:
            r = requests.post(API, headers={"x-api-key": key, "anthropic-version": VERSION, "content-type": "application/json"}, json=body, timeout=timeout)
        except requests.RequestException as e:
            raise RuntimeError(f"Claude could not be reached ({type(e).__name__})")
        if r.status_code != 200:
            msg = ""
            try:
                msg = (r.json().get("error") or {}).get("message", "")[:200]
            except Exception:
                pass
            raise RuntimeError(f"Claude failed (HTTP {r.status_code}): {msg}")
        d = r.json()
        u = d.get("usage") or {}
        tin += int(u.get("input_tokens") or 0)
        tout += int(u.get("output_tokens") or 0)
        searches += int((u.get("server_tool_use") or {}).get("web_search_requests") or 0)
        content = d.get("content") or []
        for b in content:
            t = b.get("type")
            if t == "text":
                texts.append(b.get("text", ""))
                for c in b.get("citations") or []:
                    if c.get("url"):
                        sources.append(c["url"])
            elif t == "web_search_tool_result":
                res = b.get("content")
                if isinstance(res, list):
                    sources += [x["url"] for x in res if isinstance(x, dict) and x.get("url")]
                elif isinstance(res, dict) and res.get("error_code"):
                    raise RuntimeError("Web search is not available for this Claude account (" + str(res.get("error_code")) + "). Enable it in the Anthropic console.")
        if d.get("stop_reason") == "pause_turn":
            messages.append({"role": "assistant", "content": content})
            continue
        break
    _last.usage = (tin, tout)
    try:
        from app.models import UsageEvent
        UsageEvent(user_id=os.environ.get("CLIPSTUDIO_USER_ID") or None, video_id="research", kind="llm", provider="claude", task=task, tokens_in=tin, tokens_out=tout, ok=True).save()
        if searches:
            UsageEvent(user_id=os.environ.get("CLIPSTUDIO_USER_ID") or None, video_id="research", kind="web_search", provider="claude", task=task, units=float(searches), ok=True).save()
    except Exception:
        pass
    text = chr(10).join(t for t in texts if t).strip()
    if not text:
        raise RuntimeError("Claude gave no answer")
    return text, list(dict.fromkeys(sources)), searches

