"""Which AI does which job, chosen by the owner (Settings -> AI models).

Every job that uses an AI has a PRIMARY (provider + model) and an optional FALLBACK (provider + model): for example titles on DeepSeek chat with Gemini flash lite as
the backup. A job that was never set here keeps the built-in order (see llm.py), so nothing changes until the owner chooses. A model left empty means that
provider's default model from Settings -> Accounts & keys.

Text jobs go through llm.generate and can use any of the three providers. The jobs that look at pictures (the safety review, the Best thumbnail plan and its check) are
Gemini only, because DeepSeek and the text side of Claude do not look at frames here: for those the owner picks the Gemini model and a backup Gemini model.
"""
import re
import time
from typing import Dict, List, Optional

PROVIDERS = ("gemini", "deepseek", "claude")
NAMES = {"gemini": "Gemini", "deepseek": "DeepSeek", "claude": "Claude"}
TEXT_TASKS = {   # id -> (what it is, what it does)
    "metadata": ("Titles and descriptions", "Writes the title, description and tags of every video, and the headline ideas in the Thumbnail studio."),
    "commentary": ("Commentary", "Writes the narration that the voice reads."),
    "moments": ("Picking moments", "Reads the captions of a long video and picks the best moments."),
    "scoring": ("Scoring clips", "Quick scores for ready-made clips such as live moments."),
    "thumb-prompt": ("Picture prompt writer", "Writes a new image prompt for every thumbnail (Better and Best)."),
    "thumb-plan-text": ("Best plan from the facts", "Plans the Best thumbnail from the facts when Gemini cannot look at the frames."),
    "social-caption": ("Social captions", "Rewrites the TikTok, Instagram or Facebook caption when someone presses 'Rewrite with AI' (Other platforms page)."),
    "story-ideas": ("Story ideas", "Turns what is trending into original story ideas (Story videos)."),
    "story-script": ("Story script", "Writes (or splits) the script of a story video into scenes, with the picture and the camera for each scene."),
    "trending-theme": ("Trending theme", "Reads the titles of the fastest growing clips of a game and says what is hot right now (Trending mode)."),
}
VISION_TASKS = {   # Gemini only: these look at pictures
    "safety": ("Safety review", "Looks at frames of the clip and of the final video. It always runs; this only chooses the model."),
    "thumb-plan": ("Best thumbnail plan (looks at frames)", "Looks at 3 frames and plans the Best thumbnail."),
    "thumb-review": ("Check of the finished Best thumbnail", "Looks at the finished thumbnail once (only when that option is on)."),
}
KNOWN_MODELS = {
    "gemini": ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "claude": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-2"],
}
_MODEL = re.compile(r"[A-Za-z0-9._:/\-]{0,80}")
_DOC = "ai_routes"
_cache = {"t": 0.0, "v": {}}


def _saved() -> Dict:
    if time.time() - _cache["t"] < 5:
        return _cache["v"]
    try:
        from app.models import System
        v = (System.find_one(id=_DOC) or {}).get("tasks") or {}
    except Exception:
        v = {}
    _cache.update(t=time.time(), v=v)
    return v


def _forget() -> None:
    _cache["t"] = 0.0


def all_tasks() -> Dict[str, tuple]:
    return {**TEXT_TASKS, **VISION_TASKS}


def _ready(provider: str) -> bool:
    import os
    if provider == "gemini":
        return bool((os.environ.get("GEMINI_API_KEY") or "").strip())
    if provider == "deepseek":
        return bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip())
    if provider == "claude":
        from app.engine import claude_util
        return claude_util.ready()
    return False


def _item(d) -> Optional[Dict]:
    if not isinstance(d, dict) or d.get("provider") not in PROVIDERS:
        return None
    return {"provider": d["provider"], "model": str(d.get("model") or "")}


def text_chain(task: str) -> Optional[List[Dict]]:
    """[{provider, model}, ...] for a text job when the owner set it (providers without a key are left out), else None: the built-in order applies."""
    r = _saved().get(task)
    if not r or task not in TEXT_TASKS:
        return None
    items = [i for i in (_item(r.get("primary")), _item(r.get("fallback"))) if i]
    return [i for i in items if _ready(i["provider"])]


def gemini_models(task: str) -> Optional[List[str]]:
    """The Gemini models for a picture job when the owner set them (primary, then backup), else None: the built-in list applies."""
    r = _saved().get(task)
    if not r or task not in VISION_TASKS:
        return None
    import os
    default = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
    out: List[str] = []
    for part in (r.get("primary"), r.get("fallback")):
        it = _item(part)
        if it and it["provider"] == "gemini":
            out.append(it["model"] or default)
    return list(dict.fromkeys(out)) or None


# ------------------------------------------------------------------ what Settings shows and saves
def _default_for(task: str) -> Dict:
    """The built-in choice, in the same shape: [primary, fallback] with an empty model (the provider's default)."""
    if task in VISION_TASKS:
        return {"primary": {"provider": "gemini", "model": ""}, "fallback": None}
    from app.engine import llm
    import os
    order = list(llm.ORDER.get(task, ["gemini", "deepseek"]))
    if task == "metadata":
        pick = (os.environ.get("TITLE_AI") or "auto").strip().lower()
        order = ([pick] if pick in PROVIDERS else ["claude"]) + [p for p in ("claude", "gemini", "deepseek") if p != pick]
    order = [p for p in order if _ready(p)] or order
    return {"primary": {"provider": order[0], "model": ""}, "fallback": {"provider": order[1], "model": ""} if len(order) > 1 else None}


def default_models() -> Dict[str, str]:
    import os
    return {"gemini": os.environ.get("GEMINI_MODEL") or "gemini-flash-latest", "deepseek": os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat",
            "claude": os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"}


def _claude_models() -> List[str]:
    try:
        from app.engine import claude_util
        ms = claude_util.list_models(force=False)
        got = [m["id"] if isinstance(m, dict) else str(m) for m in (ms or [])]
        return got or KNOWN_MODELS["claude"]
    except Exception:
        return KNOWN_MODELS["claude"]


def overview() -> Dict:
    saved = _saved()
    rows = []
    for tid, (label, desc) in all_tasks().items():
        r = saved.get(tid)
        cur = {"primary": _item((r or {}).get("primary")), "fallback": _item((r or {}).get("fallback"))} if r else _default_for(tid)
        rows.append({"id": tid, "label": label, "desc": desc, "vision": tid in VISION_TASKS, "custom": bool(r), "primary": cur["primary"], "fallback": cur["fallback"]})
    return {"tasks": rows, "providers": [{"id": p, "name": NAMES[p], "ready": _ready(p)} for p in PROVIDERS], "defaults": default_models(),
            "models": {**KNOWN_MODELS, "claude": _claude_models()}}


def _clean_item(d, task: str, required: bool) -> Optional[Dict]:
    if d in (None, "", {}) or (isinstance(d, dict) and d.get("provider") in (None, "", "none")):
        if required:
            raise ValueError("Choose a primary AI for every job.")
        return None
    it = _item(d)
    if not it:
        raise ValueError("Choose Gemini, DeepSeek or Claude.")
    if task in VISION_TASKS and it["provider"] != "gemini":
        raise ValueError(f"'{VISION_TASKS[task][0]}' looks at pictures, so only Gemini can do it.")
    if not _MODEL.fullmatch(it["model"]):
        raise ValueError("A model name can only have letters, numbers and . _ : / -")
    return it


def save(routes: Dict) -> Dict:
    """Save the owner's choices ({task: {primary: {provider, model}, fallback: {provider, model} | null}}). Everything is checked before anything is saved."""
    from app.models import System
    tasks = all_tasks()
    clean = {}
    for tid, r in (routes or {}).items():
        if tid not in tasks:
            raise ValueError("That job does not exist.")
        p = _clean_item((r or {}).get("primary"), tid, True)
        f = _clean_item((r or {}).get("fallback"), tid, False)
        if f and p and f == p:
            f = None                      # the same thing twice is no backup
        clean[tid] = {"primary": p, "fallback": f}
    if clean:
        System.set_fields(_DOC, {f"tasks.{k}": v for k, v in clean.items()}, upsert=True)
    _forget()
    return overview()


def reset(task: str = "") -> Dict:
    from app.models import System
    if task:
        if task not in all_tasks():
            raise ValueError("That job does not exist.")
        System.set_fields(_DOC, {}, unset=(f"tasks.{task}",), upsert=True)
    else:
        System.set_fields(_DOC, {"tasks": {}}, upsert=True)
    _forget()
    return overview()


def probe(provider: str, model: str) -> Dict:
    """Ask one provider and model for the single word OK, to see that the key and the model name work. Nothing is billed or recorded."""
    t0 = time.time()
    try:
        if provider == "gemini":
            from app.engine import gemini_util
            out = gemini_util.generate("Reply with the single word OK.", timeout=40, model=model)
        elif provider == "deepseek":
            from app.engine import llm
            out = llm._deepseek("Reply with the single word OK.", 40, False, 8, model)
        elif provider == "claude":
            from app.engine import claude_util
            out = claude_util.ask("route-test", "Reply with the single word OK.", [{"type": "text", "text": "Reply with the single word OK."}], max_tokens=8, timeout=40, model_id=model)
        else:
            return {"ok": False, "message": "Unknown provider."}
        return {"ok": True, "message": f"answered in {time.time() - t0:.1f} s", "answer": str(out)[:40]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


def test(task: str) -> List[Dict]:
    """Probe what this job would use: its primary, then its fallback."""
    if task not in all_tasks():
        raise ValueError("That job does not exist.")
    r = _saved().get(task)
    cur = {"primary": _item((r or {}).get("primary")), "fallback": _item((r or {}).get("fallback"))} if r else _default_for(task)
    out = []
    for role in ("primary", "fallback"):
        it = cur.get(role)
        if not it:
            continue
        res = probe(it["provider"], it["model"]) if _ready(it["provider"]) else {"ok": False, "message": f"The {NAMES[it['provider']]} key is not saved."}
        out.append({"role": role, "provider": it["provider"], "model": it["model"] or default_models()[it["provider"]], **res})
    return out
