"""One place to call Gemini for text, with backup models.

Free-tier quotas are per model and per day, so when the main model says 429 (quota) or 503 (busy) we simply try the next
model in the list. Raises RuntimeError only when every model failed - callers then use their built-in fallback.
"""
import os
import threading
import time
from typing import List

import requests

_last = threading.local()   # AI tokens (in, out) of the call this thread just made, as reported by Gemini


def last_usage():
    return getattr(_last, "usage", (0, 0))


BACKUPS = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-3.5-flash-lite"]


def models() -> List[str]:
    first = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
    return list(dict.fromkeys([first] + BACKUPS))


def usage_of(data: dict):
    """(tokens in, tokens out) from a Gemini response; 'out' includes the model's thinking tokens, which are billed too."""
    m = data.get("usageMetadata") or {}
    tin = int(m.get("promptTokenCount") or 0)
    return tin, max(int(m.get("totalTokenCount") or 0) - tin, int(m.get("candidatesTokenCount") or 0))


def generate(prompt: str, timeout: int = 45, json_mode: bool = False) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("no Gemini key")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    if (os.environ.get("AI_GEMINI_THINKING") or "off").strip().lower() in ("off", "0", "no"):    # thinking tokens are billed but not needed to write a title
        body.setdefault("generationConfig", {})["thinkingConfig"] = {"thinkingBudget": 0}
    last = ""
    for m in models():
        for attempt in range(2):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=timeout)
            except requests.RequestException as e:
                last = f"{m}: {type(e).__name__}"
                break
            if r.status_code == 200:
                try:
                    data = r.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if text:
                        _last.usage = usage_of(data)
                        return text
                except (KeyError, IndexError, ValueError):
                    pass
                last = f"{m}: empty answer"
                break
            last = f"{m}: HTTP {r.status_code}"
            if r.status_code == 400 and "thinkingConfig" in (body.get("generationConfig") or {}):          # the newest models answer "invalid argument" to thinking budget 0
                body["generationConfig"].pop("thinkingConfig", None)     # this model cannot switch thinking off: ask the normal way
                continue
            if r.status_code == 429 or r.status_code == 404:   # quota used up / model gone: next model right away
                break
            time.sleep(2)
    raise RuntimeError(f"all Gemini models failed ({last})")
