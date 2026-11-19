"""Text AI router: DeepSeek + Gemini share the work, each one is the backup for the other.

Which one goes first depends on the task (LLM_SPLIT=balanced, the default):
    commentary  -> DeepSeek, then Gemini      (creative writing: DeepSeek is cheap and good at it)
    moments     -> DeepSeek, then Gemini      (reading long transcripts: lots of text, so it saves Gemini's daily quota)
    metadata    -> DeepSeek, then Gemini      (titles / descriptions / thumbnail text: creative writing)
    scoring     -> Gemini,   then DeepSeek    (quick clip scores)
LLM_SPLIT=deepseek / gemini puts that one first for every task. Without a DeepSeek key everything simply uses Gemini
(which itself tries several models). Images (the safety review) are Gemini-only: DeepSeek cannot look at pictures.
"""
import json
import os
from typing import List

import requests

from app.engine import gemini_util

ORDER = {"commentary": ["deepseek", "gemini"], "moments": ["deepseek", "gemini"],
         "metadata": ["deepseek", "gemini"], "scoring": ["gemini", "deepseek"]}


def _log(msg: str) -> None:
    print(f"[AI] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)


def deepseek_ready() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def _deepseek(prompt: str, timeout: int, json_mode: bool) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("no DeepSeek key")
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "stream": False}
    if json_mode:
        # DeepSeek's JSON mode returns an object, so lists are wrapped and unwrapped again below
        body["messages"] = [{"role": "user", "content": prompt + '\n\nReturn your answer as a JSON object of the form {"result": <the JSON you were asked for>}.'}]
        body["response_format"] = {"type": "json_object"}
        body["temperature"] = 0.2
    last = ""
    for attempt in range(2):
        try:
            r = requests.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                              json=body, timeout=timeout)
        except requests.RequestException as e:
            last = type(e).__name__
            continue
        if r.status_code == 200:
            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
            if not text:
                last = "empty answer"
                continue
            if json_mode:
                data = json.loads(text)
                return json.dumps(data["result"] if isinstance(data, dict) and "result" in data else data)
            return text
        last = f"HTTP {r.status_code}"
        if r.status_code in (401, 402, 403):   # bad key / no balance: retrying will not help
            break
    raise RuntimeError(f"DeepSeek failed ({last})")


def order_for(task: str) -> List[str]:
    split = (os.environ.get("LLM_SPLIT") or "balanced").strip().lower()
    base = ORDER.get(task, ["gemini", "deepseek"])
    if split in ("deepseek", "gemini"):
        base = [split] + [p for p in base if p != split]
    return [p for p in base if p != "deepseek" or deepseek_ready()]


def generate(task: str, prompt: str, json_mode: bool = False, timeout: int = 60) -> str:
    """Run a text task on the preferred AI, falling back to the other. Raises RuntimeError if every provider failed."""
    errors = []
    for p in order_for(task):
        try:
            text = _deepseek(prompt, timeout, json_mode) if p == "deepseek" else gemini_util.generate(prompt, timeout=timeout, json_mode=json_mode)
            _log(f"{task}: answered by {p}")
            return text
        except Exception as e:
            errors.append(f"{p}: {str(e)[:90]}")
            _log(f"{task}: {p} unavailable ({str(e)[:80]})")
    raise RuntimeError("; ".join(errors) or "no AI provider configured")
