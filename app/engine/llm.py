"""Text AI router: DeepSeek + Gemini share the work, each one is the backup for the other.

Which one goes first depends on the task (LLM_SPLIT=balanced, the default):
    commentary  -> DeepSeek, then Gemini      (creative writing: DeepSeek is cheap and good at it)
    moments     -> DeepSeek, then Gemini      (reading long transcripts: lots of text, so it saves Gemini's daily quota)
    metadata    -> Claude, then Gemini, then DeepSeek   (titles / descriptions: TITLE_AI=auto uses the strongest model you have a key for;
                                                       choose claude / gemini / deepseek in Settings -> Accounts & keys to force one)
    scoring     -> Gemini,   then DeepSeek    (quick clip scores)
LLM_SPLIT=deepseek / gemini puts that one first for every task. Without a DeepSeek key everything simply uses Gemini
(which itself tries several models). Images (the safety review) are Gemini-only: DeepSeek cannot look at pictures.
"""
import json
import os
import threading
from typing import List

import requests

from app.engine import ai_saver, gemini_util

ORDER = {"commentary": ["deepseek", "gemini"], "moments": ["deepseek", "gemini"],
         "metadata": ["deepseek", "gemini"], "scoring": ["gemini", "deepseek"], "thumb-prompt": ["deepseek", "gemini"]}


def _log(msg: str) -> None:
    print(f"[AI] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)


_deepseek_usage = threading.local()   # AI tokens (in, out) of the DeepSeek call this thread just made


def deepseek_ready() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def _deepseek(prompt: str, timeout: int, json_mode: bool, max_tokens: int = 0, model_id: str = "") -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("no DeepSeek key")
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = model_id or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "stream": False}
    if max_tokens:
        body["max_tokens"] = int(max_tokens)
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
            u = r.json().get("usage") or {}
            _deepseek_usage.usage = (int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0))
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
    from app.engine import claude_util
    split = (os.environ.get("LLM_SPLIT") or "balanced").strip().lower()
    base = ORDER.get(task, ["gemini", "deepseek"])
    if task == "metadata":      # titles and descriptions decide whether anybody clicks: the strongest writer goes first
        pick = (os.environ.get("TITLE_AI") or "auto").strip().lower()
        if pick not in ("claude", "gemini", "deepseek"):
            pick = split if split in ("deepseek", "gemini") else "claude"      # auto: your overall choice if you made one, else the strongest
        base = [pick] + [p for p in ("claude", "gemini", "deepseek") if p != pick]
    elif split in ("deepseek", "gemini"):
        base = [split] + [p for p in base if p != split]
    return [p for p in base if (p != "deepseek" or deepseek_ready()) and (p != "claude" or claude_util.ready())]


def _record(kind: str, provider: str, task: str, tin: int, tout: int) -> None:
    from app.models import UsageEvent
    UsageEvent.record(kind, provider=provider, task=task, tokens_in=tin, tokens_out=tout)
    ai_saver.spend(tin + tout)


def generate(task: str, prompt: str, json_mode: bool = False, timeout: int = 60) -> str:
    """Run a text task on the preferred AI, falling back to the other. Raises RuntimeError if every provider failed."""
    if (os.environ.get("LLM_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on"):
        raise RuntimeError("AI text is switched off for this video (the member chose to write it themselves)")
    if ai_saver.over_budget(task):       # this video has used its AI budget: the caller falls back to its built-in text
        ai_saver.saved(task, "budget", max(200, len(prompt) // 4))
        raise RuntimeError("the AI token budget for this video is used up")
    errors = []
    for p in order_for(task):
        try:
            if p == "claude":
                from app.engine import claude_util
                raw = claude_util.ask(task, "You write YouTube titles and descriptions." + (" Reply with one JSON object and nothing else." if json_mode else ""),
                                      [{"type": "text", "text": prompt}], max_tokens=ai_saver.max_tokens(task) or 1800, timeout=max(timeout, 60),
                                      model_id=claude_util.title_model() if task == "metadata" else "", temperature=0.8 if task == "metadata" else 0.4)
                if json_mode:
                    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    a, b = raw.find("{"), raw.rfind("}")
                    raw = raw[a:b + 1] if 0 <= a < b else raw
                _log(f"{task}: answered by claude")
                return raw        # claude_util.ask has already recorded the usage and the AI budget
            if p == "deepseek":
                _deepseek_usage.usage = (0, 0)
                text = _deepseek(prompt, timeout, json_mode, ai_saver.max_tokens(task) or 0)
                tin, tout = getattr(_deepseek_usage, "usage", (0, 0))
            else:
                gemini_util._last.usage = (0, 0)
                text = gemini_util.generate(prompt, timeout=timeout, json_mode=json_mode)
                tin, tout = gemini_util.last_usage()
            if not (tin or tout):     # the service did not say: estimate from the size of the text (about 4 characters per token)
                tin, tout = len(prompt) // 4, len(text) // 4
            _record("llm", p, task, tin, tout)
            _log(f"{task}: answered by {p}")
            return text
        except Exception as e:
            errors.append(f"{p}: {str(e)[:90]}")
            _log(f"{task}: {p} unavailable ({str(e)[:80]})")
    raise RuntimeError("; ".join(errors) or "no AI provider configured")
