"""One place to call Gemini for text, with backup models.

Free-tier quotas are per model and per day, so when the main model says 429 (quota) or 503 (busy) we simply try the next
model in the list. Raises RuntimeError only when every model failed - callers then use their built-in fallback.
"""
import os
import time
from typing import List

import requests

BACKUPS = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-3.5-flash-lite"]


def models() -> List[str]:
    first = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
    return list(dict.fromkeys([first] + BACKUPS))


def generate(prompt: str, timeout: int = 45, json_mode: bool = False) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("no Gemini key")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
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
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if text:
                        return text
                except (KeyError, IndexError, ValueError):
                    pass
                last = f"{m}: empty answer"
                break
            last = f"{m}: HTTP {r.status_code}"
            if r.status_code == 429 or r.status_code == 404:   # quota used up / model gone: next model right away
                break
            time.sleep(2)
    raise RuntimeError(f"all Gemini models failed ({last})")
