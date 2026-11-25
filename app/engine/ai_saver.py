"""The AI saver: one set of rules that every AI call of the studio follows, so the same result costs fewer tokens.

  * small output limits per task (a model cannot ramble on at your expense),
  * a token budget for each video (a run can never run away),
  * pictures are read at low resolution (the same answer for about a quarter of the tokens),
  * a cache: the same question about the same video / clip file is paid for once, for everybody,
  * a record of every token that was NOT spent, so Reports can show the saving.

Nothing here weakens the safety check: it is cheaper, never skipped.

It is OFF until the account turns it on (Settings -> AI saver; every member and the owner choose for their own videos). While it is off every
function below does nothing: no answer limits, no budget, normal picture resolution, no cache and no savings record.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

# answer limits (in AI tokens) per task: enough for the real answer, not for waffle
LIMITS = {"commentary": 360, "metadata": 1300, "moments": 1100, "scoring": 900, "thumbnail-headlines": 450, "thumb-plan": 800, "thumb-review": 300, "thumb-prompt": 500, "safety": 160}
EXEMPT = {"safety"}                     # the safety review is never refused because of a budget
LOW_RES_RATIO = 3.1                     # measured: 6,628 tokens at default resolution vs 1,612 at low (the saving is 3.1 times what is still spent)
_spent = 0


def enabled() -> bool:
    """Has the account that is running (CLIPSTUDIO_USER_ID) switched the AI saver on? Off by default."""
    try:
        from app.engine import clipcfg
        return clipcfg.ai_saver_on()
    except Exception:
        return False


def max_tokens(task: str) -> Optional[int]:
    if not enabled():
        return None
    v = os.environ.get("AI_MAX_TOKENS_" + task.upper().replace("-", "_"))
    try:
        return int(v) if v else LIMITS.get(task)
    except ValueError:
        return LIMITS.get(task)


def media_resolution() -> Optional[str]:
    """How closely Gemini looks at each picture: low (about 280 tokens a picture, the default here), medium, high, or 'default' (about 1,100)."""
    if not enabled():
        return None
    v = (os.environ.get("AI_MEDIA_RESOLUTION") or "low").strip().lower()
    return {"low": "MEDIA_RESOLUTION_LOW", "medium": "MEDIA_RESOLUTION_MEDIUM", "high": "MEDIA_RESOLUTION_HIGH"}.get(v)


# ---------------------------------------------------------------- the budget of this video
def budget() -> int:
    try:
        return int(os.environ.get("AI_JOB_BUDGET") or 60000)
    except ValueError:
        return 60000


def spend(tokens: int) -> None:
    global _spent
    _spent += max(0, int(tokens or 0))


def spent() -> int:
    return _spent


def over_budget(task: str) -> bool:
    return enabled() and task not in EXEMPT and _spent >= budget()


def reset() -> None:
    global _spent
    _spent = 0


# ---------------------------------------------------------------- what was saved
def saved(task: str, kind: str, tokens: int) -> None:
    if not enabled():
        return
    from app.models import AiSaving
    AiSaving.record(task, kind, tokens)


# ---------------------------------------------------------------- the cache
def key_of(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def fingerprint(path: Path) -> str:
    """Identifies a video file by its size and three pieces of it (fast, and the same file always gets the same answer)."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with open(p, "rb") as f:
        for pos in (0, max(0, size // 2 - 131072), max(0, size - 262144)):
            f.seek(pos)
            h.update(f.read(262144))
    return h.hexdigest()


def cache_get(task: str, key: str) -> Optional[Any]:
    if not enabled():
        return None
    try:
        from app.models import AiCache
        d = AiCache.objects(id=key).first()
        if not d:
            return None
        AiCache.objects(id=key).update(inc__hits=1)
        saved(task, "cache", int(d.tokens or 0))
        return json.loads(d.payload)
    except Exception:
        return None


def cache_put(task: str, key: str, value: Any, tokens: int = 0) -> None:
    if not enabled():
        return
    try:
        from app.models import AiCache
        from app.models.base import now
        AiCache.objects(id=key).update_one(upsert=True, set__task=task, set__payload=json.dumps(value, default=str), set__tokens=int(tokens or 0), set_on_insert__created_at=now())
    except Exception:
        pass
