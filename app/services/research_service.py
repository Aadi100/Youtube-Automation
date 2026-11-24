"""Clipping research: Claude, with its web search, finds who allows clipping, what programmes pay for it and what they want,
and whether clips can earn on the member's own YouTube channel.

The rules that keep it honest:
  * a permission only counts when it comes with a web address that Claude really opened in that run, and a short quote from it,
  * "allows clipping" is never turned into "you may monetise" on its own: these are different questions and the answer says which,
  * anything Claude could not prove is shown as "unknown", never guessed.
These are research notes, not legal advice: the creator's or programme's own rules page is what counts.
"""
import json
import os
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from app.engine import claude_util
from app.models import ResearchLead, ResearchRun, now, oid

SCOPES = {
    "world": ("Worldwide", "Creators and programmes anywhere that allow or pay for clipping their content"),
    "game": ("One game", "Who allows clipping of this game or category, and what they want"),
    "creator": ("One creator", "Does this creator allow clipping? Is there a programme?"),
    "marketplace": ("Programmes and marketplaces", "Platforms and campaigns that connect creators with clippers and pay per view"),
}
PLATFORMS = ("twitch", "youtube", "kick", "tiktok", "other")
ALLOWS = ("yes", "conditional", "no", "unknown")
TYPES = ("creator", "programme", "marketplace")
STATUSES = ("new", "saved", "contacted", "approved", "rejected")
DEPTH = {"quick": 6, "normal": 12, "deep": 24}
MAX_LEADS = 14
TOKENS_PER_SEARCH = 4500          # about what one search adds to the conversation (results are read by Claude): used for the estimate only

SYSTEM = (
    "You are a careful research analyst for a YouTube channel that clips gaming and streaming content. You use web search to find which creators and programmes ALLOW "
    "clipping, whether a clipping programme or campaign exists (who runs it, how it pays, how to join), what kind of clips are wanted (which games, categories or video types, "
    "length, rules, which platforms are allowed), and whether clips can earn on the clipper's own YouTube channel.\n"
    "Rules you must follow:\n"
    "- Only state what the pages you opened actually say. If a page does not say it, the answer is \"unknown\". Never guess, never fill gaps from memory.\n"
    "- Every lead needs evidence: the exact web address of a page you opened and a short quote (max 25 words) copied from it. No evidence, no lead.\n"
    "- Permission to clip is NOT permission to monetise. Say separately whether the page allows ads or payouts on a clipper's own channel. YouTube's own rules for reused "
    "content still apply: a clip with no real commentary or editing of your own can be demonetised even with the creator's blessing.\n"
    "- Prefer official pages: the creator's own site, channel About page, Discord rules post, programme page. Note the date of the page when you can see it.\n"
    "- Do not invent payouts, numbers, names or links.")


def clean_url(u: str) -> str:
    """The same page written two ways compares equal (no scheme, no www, no tracking, no trailing slash)."""
    try:
        p = urlparse((u or "").strip())
        host = (p.netloc or "").lower().removeprefix("www.")
        path = (p.path or "").rstrip("/")
        q = "&".join(x for x in (p.query or "").split("&") if x and not x.lower().startswith(("utm_", "ref", "fbclid", "gclid")))
        return f"{host}{path}" + (f"?{q}" if q else "")
    except Exception:
        return ""


def estimate(searches: int, provider: str = "claude") -> Dict:
    """What a run is expected to use. Dollars use the rates the owner typed under Reports (0 when none); only Claude's rates are known to the studio."""
    from app.services import token_service as tk
    r = tk.real_costs()
    tin, tout = 6000 + searches * TOKENS_PER_SEARCH, 5000
    if provider != "claude":
        return {"searches": searches, "tokens": tin + tout, "usd": 0, "rates_entered": False, "other_provider": True}
    usd = tin / 1e6 * r["claude_in_per_1m"] + tout / 1e6 * r["claude_out_per_1m"] + searches * r["claude_search_usd"]
    return {"searches": searches, "tokens": tin + tout, "usd": round(usd, 3), "rates_entered": bool(r["claude_in_per_1m"] or r["claude_out_per_1m"] or r["claude_search_usd"])}


PROVIDERS = {"claude": "Claude", "gemini": "Gemini", "deepseek": "DeepSeek"}


def provider_info() -> List[Dict]:
    """Which AI can do the research now, and which models each offers."""
    from app.engine import web_research as wr
    return [
        {"id": "claude", "name": "Claude", "ready": claude_util.ready(), "why": "" if claude_util.ready() else "Needs the Claude key.", "model": claude_util.research_model(),
         "how": "Claude's own web search reads the pages.", "models": [m["id"] for m in claude_util.list_models()]},
        {"id": "gemini", "name": "Gemini", "ready": wr.gemini_ready(), "why": "" if wr.gemini_ready() else "Needs the Gemini key.", "model": wr.gemini_models()[0],
         "how": "Gemini searches Google and reads the pages.", "models": wr.gemini_models()},
        {"id": "deepseek", "name": "DeepSeek", "ready": wr.deepseek_ready() and wr.search_ready(),
         "why": "" if wr.deepseek_ready() and wr.search_ready() else ("Needs the DeepSeek key." if not wr.deepseek_ready() else "DeepSeek cannot browse: add a free search key (Tavily or Brave Search) in Settings."),
         "model": wr.deepseek_models()[0], "how": "DeepSeek writes the searches, a search service (Tavily or Brave, free key) finds the pages, the studio downloads them and DeepSeek reads them. Gemini is not used.", "models": wr.deepseek_models()},
    ]


def default_provider() -> str:
    p = (os.environ.get("RESEARCH_PROVIDER") or "claude").strip().lower()
    return p if p in PROVIDERS else "claude"


def task_line(scope: str, query: str, platforms: List[str], language: str) -> str:
    what = {"world": "Find creators and clipping programmes from anywhere in the world that allow or pay for clipping gaming / streaming content.",
            "game": f'Find creators and programmes that allow clipping of the game or category "{query}", and what kind of clips they want.',
            "creator": f'Research the creator "{query}": do they allow clipping? Is there an official clipping programme or campaign? What are the rules?',
            "marketplace": "Find clipping programmes, campaigns and marketplaces (places where creators post a campaign and clippers earn per view) that accept gaming or streaming clips."}[scope]
    where = f" Focus on these platforms: {', '.join(platforms)}." if platforms else ""
    lang = f" Prefer sources in {language}." if language else ""
    return f"Today is {datetime.utcnow().strftime('%Y-%m-%d')}. {what}{where}{lang}"


def build_request(scope: str, query: str, platforms: List[str], language: str, searches: int, pages_only: bool = False) -> str:
    use = "Use ONLY the web pages provided above, nothing from memory, then answer." if pages_only else f"Use at most {searches} web searches, then answer."
    return (f"{task_line(scope, query, platforms, language)} {use}\n\n"
            f"Return ONE JSON object and nothing else, in this shape (at most {MAX_LEADS} leads, the best-evidenced first):\n"
            '{"summary": "3 sentences: what you found overall", "leads": [{"name": "creator or programme", "type": "creator|programme|marketplace", "platform": "twitch|youtube|kick|tiktok|other", '
            '"url": "their official page", "games": ["games or categories"], "allows_clipping": "yes|conditional|no|unknown", "permission_text": "what they say, in your own words, max 40 words", '
            '"programme": {"name": "", "where": "where it runs", "pay": "how and how much it pays, only if stated", "how_to_join": ""} or null, "requirements": ["max 6 short rules"], '
            '"content_wanted": ["kinds of clips they want"], "platforms_allowed": ["youtube_shorts", "youtube_long", "tiktok", "instagram"], '
            '"monetization": {"verdict": "yes|conditional|no|unknown", "why": "max 35 words about ads or payouts on the clipper\'s own channel"}, '
            '"evidence": [{"url": "a page you opened", "quote": "max 25 words copied from it", "date": "YYYY-MM or empty"}], "confidence": "high|medium|low"}], '
            '"gaps": ["what you looked for but could not find"]}')


def _objects(s: str, start: int) -> List[str]:
    """Every complete {...} object at the top level of the array that begins at s[start] (string-aware). A half-written last one is dropped."""
    out, depth, ins, esc, a = [], 0, False, False, -1
    for i in range(start, len(s)):
        ch = s[i]
        if ins:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                ins = False
            continue
        if ch == '"':
            ins = True
        elif ch == "{":
            if depth == 0:
                a = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and a >= 0:
                out.append(s[a:i + 1])
                a = -1
        elif ch == "]" and depth == 0:
            break
    return out


def _json_of(text: str) -> Dict:
    """Claude's answer as a dict. If the answer is broken or was cut off (too long), keep every lead that was finished instead of losing the run."""
    t = text.strip()
    m = re.search(r'\{\s*"(?:summary|leads)"', t)
    a = m.start() if m else t.find("{")
    if a < 0:
        raise ValueError("Claude did not answer in the expected format. Try again.")
    b = t.rfind("}")
    try:
        return json.loads(t[a:b + 1])
    except ValueError:
        pass
    body = t[a:]
    lm = re.search(r'"leads"\s*:\s*\[', body)
    if not lm:
        raise ValueError("Claude's answer was cut off before any creator was listed. Try a narrower search (one platform, Quick depth).")
    leads = []
    for o in _objects(body, lm.end()):
        try:
            x = json.loads(o)
        except ValueError:
            continue
        if isinstance(x, dict):
            leads.append(x)
    sm = re.search(r'"summary"\s*:\s*("(?:[^"\\]|\\.)*")', body)
    gm = re.search(r'"gaps"\s*:\s*(\[(?:[^\]]|\\.)*\])', body)
    try:
        summary = json.loads(sm.group(1)) if sm else ""
    except ValueError:
        summary = ""
    try:
        gaps = json.loads(gm.group(1)) if gm else []
    except ValueError:
        gaps = []
    if not leads:
        raise ValueError("Claude's answer was cut off before any creator was finished. Try a narrower search (one platform, Quick depth).")
    return {"summary": summary, "leads": leads, "gaps": gaps, "_partial": True}


def _s(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _list(v, n: int, w: int) -> List[str]:
    return [_s(x, w) for x in (v if isinstance(v, list) else []) if _s(x, w)][:n]


def clean_lead(l: Dict, sources: set) -> Optional[Dict]:
    """One lead as Claude wrote it -> the lead we keep. Everything is checked; a claim without a real source is not kept as a claim."""
    if not isinstance(l, dict) or not _s(l.get("name"), 120):
        return None
    ev = []
    for e in (l.get("evidence") if isinstance(l.get("evidence"), list) else [])[:6]:
        cu = clean_url(e.get("url")) if isinstance(e, dict) else ""
        if isinstance(e, dict) and (cu in sources or ("host:" + cu.split("/")[0].split("?")[0]) in sources) and cu and _s(e.get("quote"), 220):
            ev.append({"url": _s(e["url"], 300), "quote": _s(e["quote"], 220), "date": _s(e.get("date"), 10)})
    ev = ev[:4]
    allows = l.get("allows_clipping") if l.get("allows_clipping") in ALLOWS else "unknown"
    note = ""
    if allows in ("yes", "conditional", "no") and not ev:
        allows, note = "unknown", "Claude named no page it really opened for this, so it is not counted as an answer."
    mon = l.get("monetization") if isinstance(l.get("monetization"), dict) else {}
    verdict = mon.get("verdict") if mon.get("verdict") in ALLOWS else "unknown"
    if allows in ("no", "unknown") and verdict in ("yes", "conditional"):
        verdict = "unknown"                              # no permission to clip means no promise about earning
    if verdict == "yes" and not any(re.search(r"monetiz|monetis|revenue|ad share|payout|paid|license|licence|earn", e["quote"], re.I) for e in ev):
        verdict = "conditional"                          # "yes" needs a source that actually talks about earning
    prog = l.get("programme") if isinstance(l.get("programme"), dict) else None
    conf = l.get("confidence") if l.get("confidence") in ("high", "medium", "low") else "low"
    if not ev:
        conf = "low"
    elif len(ev) < 2 and conf == "high":
        conf = "medium"
    url = _s(l.get("url"), 300)
    return {"name": _s(l.get("name"), 120), "type": l.get("type") if l.get("type") in TYPES else "creator", "platform": l.get("platform") if l.get("platform") in PLATFORMS else "other",
            "url": url if url.startswith(("http://", "https://")) else "", "games": _list(l.get("games"), 8, 60), "allows": allows, "permission_text": _s(l.get("permission_text"), 300),
            "programme": ({k: _s(prog.get(k), 200) for k in ("name", "where", "pay", "how_to_join")} if prog and any(prog.values()) else None),
            "requirements": _list(l.get("requirements"), 6, 160), "content_wanted": _list(l.get("content_wanted"), 6, 80),
            "platforms_allowed": [p for p in _list(l.get("platforms_allowed"), 6, 20) if p in ("youtube_shorts", "youtube_long", "tiktok", "instagram")],
            "monetization": {"verdict": verdict, "why": _s(mon.get("why"), 260)}, "evidence": ev, "confidence": conf, "note": note, "verified": bool(ev)}


def lead_key(name: str, platform: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower()) + ":" + (platform or "other")


# ---------------------------------------------------------------- running a research
def start(uid, scope: str, query: str, platforms: List[str], language: str, depth: str, model_id: str = "", provider: str = "") -> str:
    if scope not in SCOPES:
        raise ValueError("Choose what to research.")
    query = _s(query, 120)
    if scope in ("game", "creator") and len(query) < 2:
        raise ValueError("Type the game or the creator to research.")
    provider = provider if provider in PROVIDERS else default_provider()
    info = next(p for p in provider_info() if p["id"] == provider)
    if not info["ready"]:
        raise ValueError(f"Research with {info['name']}: {info['why']} Add it in Settings -> Accounts & keys, or choose another AI.")
    if ResearchRun.total(user_id=str(uid), status="running"):
        raise ValueError("A research is already running. Wait for it to finish.")
    searches = DEPTH.get(depth, DEPTH["normal"])
    model_id = _s(model_id, 80)
    if model_id and not re.fullmatch(r"[A-Za-z0-9._:\-]+", model_id):
        raise ValueError("That model name is not valid.")
    model_id = model_id or info["model"]
    plats = [p for p in (platforms or []) if p in PLATFORMS][:5]
    run = ResearchRun(user_id=str(uid), scope=scope, query=query, status="running", created_at=now(), platforms=plats, language=_s(language, 30), depth=depth if depth in DEPTH else "normal",
                      searches_allowed=searches, message=f"{info['name']} is searching the web…", estimate=estimate(searches, provider), model=model_id, provider=provider).save()
    threading.Thread(target=_run, args=(str(uid), str(run.id), scope, query, plats, _s(language, 30), searches, model_id, provider), daemon=True).start()
    return str(run.id)


def _set(rid, **f) -> None:
    ResearchRun.objects(id=oid(str(rid))).update(**{f"set__{k}": v for k, v in f.items()})


def _run(uid: str, rid: str, scope: str, query: str, platforms: List[str], language: str, searches: int, model_id: str = "", provider: str = "claude") -> None:
    try:
        from app.engine import web_research as wr
        if provider == "gemini":
            text, sources, used, tin, tout = wr.gemini_search(SYSTEM, build_request(scope, query, platforms, language, searches), model_id, 16000, 420)
        elif provider == "deepseek":
            text, sources, used, tin, tout = wr.deepseek_research(SYSTEM, task_line(scope, query, platforms, language),
                                                                   build_request(scope, query, platforms, language, searches, pages_only=True), searches, model_id, 8000, 420)
        else:
            text, sources, used = claude_util.ask_with_search("research", SYSTEM, build_request(scope, query, platforms, language, searches), max_searches=searches, max_tokens=20000, timeout=600, model_id=model_id)
            tin, tout = claude_util.last_usage()
        known = {clean_url(u) for u in sources}
        n_src = len(known)
        if provider == "gemini":             # Gemini names its pages through redirects and may cite a sibling page of the same site: the site must be one it really used
            known |= {"host:" + clean_url(u).split("/")[0].split("?")[0] for u in sources}
        _set(rid, raw=text[:80000], sources=n_src, searches_used=used, tokens_in=tin, tokens_out=tout)     # kept even if the answer cannot be read, so nothing is lost
        data = _json_of(text)
        leads = [c for c in (clean_lead(l, known) for l in (data.get("leads") or [])[:MAX_LEADS]) if c]
        saved = [_save_lead(uid, rid, c) for c in leads]
        unverified = sum(1 for c in leads if not c["verified"])
        _set(rid, status="done", message=f"{len(leads)} lead{'s' if len(leads) != 1 else ''} found" + (f" ({unverified} without proof, shown as unknown)" if unverified else "")
             + (" - the answer was too long, so only the finished ones are kept; run it again with fewer platforms to see more" if data.get("_partial") else ""),
             summary=_s(data.get("summary"), 700), gaps=_list(data.get("gaps"), 8, 200), searches_used=used, tokens_in=tin, tokens_out=tout, lead_ids=saved, sources=n_src)
    except ValueError as e:
        _set(rid, status="error", message=str(e)[:300])
    except Exception as e:
        _set(rid, status="error", message=str(e)[:300] if isinstance(e, RuntimeError) else f"{type(e).__name__}: {str(e)[:200]}")


def _save_lead(uid: str, rid: str, c: Dict) -> str:
    """Keep the lead (once per creator or programme and platform). A new run refreshes the facts; the member's own status and notes stay."""
    key = lead_key(c["name"], c["platform"])
    old = ResearchLead.objects(user_id=uid, key=key).first()
    facts = {"run_id": rid, "name": c["name"], "allows": c["allows"], "data": c, "checked_at": now()}
    if old:
        ResearchLead.objects(id=old.id).update(**{f"set__{k}": v for k, v in facts.items()})
        return str(old.id)
    return str(ResearchLead(user_id=uid, key=key, status="new", created_at=now(), notes="", **facts).save().id)


# ---------------------------------------------------------------- what the page shows
def run_view(d: Dict) -> Dict:
    created = d["created_at"].replace(tzinfo=None).isoformat() + "Z" if d.get("created_at") else None
    return {"id": str(d["_id"]), "scope": d.get("scope"), "query": d.get("query"), "status": d.get("status"), "message": d.get("message") or "", "summary": d.get("summary") or "",
            "gaps": d.get("gaps") or [], "searches": d.get("searches_used"), "tokens": (d.get("tokens_in") or 0) + (d.get("tokens_out") or 0), "created_at": created,
            "platforms": d.get("platforms") or [], "depth": d.get("depth"), "estimate": d.get("estimate"), "lead_ids": d.get("lead_ids") or [], "model": d.get("model") or "", "provider": d.get("provider") or "claude", "language": d.get("language") or ""}


def export_run(uid, rid: str) -> Optional[Dict]:
    """The whole record of one research: the question, the model, the cost, every lead with its proof, and Claude's answer as received."""
    d = get_run(uid, rid)
    if not d:
        return None
    return {"run": run_view(d), "leads": list_leads(uid, run_id=rid), "claude_answer": d.get("raw") or ""}


def lead_view(d: Dict) -> Dict:
    data = d.get("data") or {}
    return {"id": str(d["_id"]), **data, "status": d.get("status"), "notes": d.get("notes") or "", "run_id": d.get("run_id"),
            "checked_at": d["checked_at"].replace(tzinfo=None).isoformat() + "Z" if d.get("checked_at") else None}


def _lead_counts(uid) -> Dict[str, Dict[str, int]]:
    """For each research: how many leads of each verdict it (last) refreshed."""
    out: Dict[str, Dict[str, int]] = {}
    for d in ResearchLead.find_all(user_id=str(uid), limit=1000):
        c = out.setdefault(d.get("run_id") or "", {"yes": 0, "conditional": 0, "unknown": 0, "no": 0})
        c[d.get("allows") if d.get("allows") in c else "unknown"] += 1
    return out


def list_runs(uid, limit: int = 30) -> List[Dict]:
    counts = _lead_counts(uid)
    rows = []
    for d in ResearchRun.find_all(user_id=str(uid), order=("-created_at",), limit=limit):
        v = run_view(d)
        v["counts"] = counts.get(v["id"], {"yes": 0, "conditional": 0, "unknown": 0, "no": 0})
        v["language"] = d.get("language") or ""
        rows.append(v)
    return rows


def stats(uid) -> Dict:
    """The whole picture over every research: how many, how many leads, what it cost in searches and tokens, and which AI did how many."""
    runs = ResearchRun.find_all(user_id=str(uid), limit=500)
    done = [r for r in runs if r.get("status") == "done"]
    by = {}
    for r in runs:
        k = r.get("provider") or "claude"
        by[k] = by.get(k, 0) + 1
    leads = _lead_counts(uid)
    tot = {"yes": 0, "conditional": 0, "unknown": 0, "no": 0}
    for c in leads.values():
        for k in tot:
            tot[k] += c[k]
    return {"runs": len(runs), "done": len(done), "failed": sum(1 for r in runs if r.get("status") == "error"), "leads": sum(tot.values()), "allowed": tot["yes"], "conditional": tot["conditional"],
            "searches": sum(int(r.get("searches_used") or 0) for r in runs), "tokens": sum(int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0) for r in runs), "by_ai": by,
            "trend": [{"leads": sum((leads.get(str(r["_id"])) or {}).values()), "status": r.get("status")} for r in reversed(runs[:14])]}


def get_run(uid, rid: str) -> Optional[Dict]:
    try:
        d = ResearchRun.find_one(id=oid(rid))
    except ValueError:
        return None
    return d if d and d.get("user_id") == str(uid) else None


def list_leads(uid, status: str = "", allows: str = "", q: str = "", run_id: str = "") -> List[Dict]:
    f = {"user_id": str(uid)}
    if status in STATUSES:
        f["status"] = status
    if allows in ALLOWS:
        f["allows"] = allows
    if run_id:
        f["run_id"] = run_id
    rows = [lead_view(d) for d in ResearchLead.find_all(order=("-checked_at",), limit=300, **f)]
    if q:
        ql = q.lower()
        def hay(r): return r["name"] + " " + " ".join(r.get("games") or []) + " " + " ".join(r.get("content_wanted") or []) + " " + (r.get("permission_text") or "")
        rows = [r for r in rows if ql in hay(r).lower() or (_gkey(q) and _gkey(q) in _gkey(hay(r)))]        # "GTA6" also finds "GTA 6"
    order = {"yes": 0, "conditional": 1, "unknown": 2, "no": 3}
    return sorted(rows, key=lambda r: (order.get(r["allows"], 9), {"high": 0, "medium": 1, "low": 2}.get(r.get("confidence"), 3)))


def _gkey(g) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(g or "").lower())


def opportunity(l: Dict) -> Dict:
    """How good a lead is for the channel, with the reasons in plain words. Proven permission matters most; a stated way to earn and a paying programme add to it."""
    pts, why = 0.0, []
    a = l.get("allows")
    if a == "yes":
        pts += 3; why.append("clipping allowed")
    elif a == "conditional":
        pts += 1.5; why.append("allowed with conditions")
    else:
        return {"score": 0, "why": ["no proven permission"] if a != "no" else ["clipping not allowed"]}
    m = (l.get("monetization") or {}).get("verdict")
    if m == "yes":
        pts += 2; why.append("earning on your channel is supported")
    elif m == "conditional":
        pts += 1; why.append("earning depends on conditions")
    if l.get("programme"):
        pts += 1.5; why.append("has a clipping programme" + (" that pays" if (l["programme"] or {}).get("pay") else ""))
    conf = l.get("confidence")
    pts += {"high": 1, "medium": 0.5}.get(conf, 0)
    if len(l.get("evidence") or []) >= 2:
        pts += 0.5; why.append("two or more sources")
    if (l.get("platforms_allowed") or []):
        pts += 0.5
    return {"score": round(pts, 1), "why": why}


def insights(uid, run_id: str = "") -> Dict:
    """Everything researched so far, added up so the member can decide what to make: how many leads, which kinds of clips are wanted, which games,
    where clips may be posted, which programmes pay, and the best opportunities. Counted from the saved leads only (nothing is guessed)."""
    from collections import Counter, defaultdict
    leads = list_leads(uid, run_id=run_id)
    usable = [l for l in leads if l["allows"] in ("yes", "conditional")]
    kinds, games, plats = Counter(), Counter(), Counter()
    label: Dict[str, str] = {}
    who_kind, who_game = defaultdict(list), defaultdict(list)
    progs = []
    for l in usable:
        for k in {x.strip().lower() for x in (l.get("content_wanted") or []) if x.strip()}:
            kinds[k] += 1; who_kind[k].append(l["name"])
        for g in {_gkey(x) for x in (l.get("games") or []) if _gkey(x)}:      # "GTA6", "GTA 6" and "Gta 6" are one game
            games[g] += 1; who_game[g].append(l["name"])
            label.setdefault(g, next(x.strip() for x in l["games"] if _gkey(x) == g))
        for p in set(l.get("platforms_allowed") or []):
            plats[p] += 1
        if l.get("programme"):
            progs.append({"id": l["id"], "name": l["name"], "programme": l["programme"], "allows": l["allows"], "platform": l["platform"], "url": l.get("url") or ""})
    ranked = []
    for l in leads:
        o = opportunity(l)
        if o["score"] > 0:
            ranked.append({"id": l["id"], "name": l["name"], "platform": l["platform"], "type": l["type"], "allows": l["allows"], "score": o["score"], "why": o["why"], "games": (l.get("games") or [])[:4],
                           "content_wanted": (l.get("content_wanted") or [])[:4], "platforms_allowed": l.get("platforms_allowed") or [], "pay": ((l.get("programme") or {}).get("pay") or ""), "status": l.get("status")})
    ranked.sort(key=lambda x: -x["score"])
    plan = []
    for k, n in kinds.most_common(6):
        sample = [l for l in usable if k in {x.strip().lower() for x in (l.get("content_wanted") or [])}]
        pl = Counter(p for l in sample for p in (l.get("platforms_allowed") or []))
        gm = Counter(_gkey(g) for l in sample for g in (l.get("games") or []) if _gkey(g))
        plan.append({"kind": k, "creators": n, "who": who_kind[k][:5], "platforms": [p for p, _ in pl.most_common(3)], "games": [label.get(g, g) for g, _ in gm.most_common(3)]})
    verdicts = Counter(l["allows"] for l in leads)
    earn = sum(1 for l in usable if (l.get("monetization") or {}).get("verdict") == "yes")
    return {"total": len(leads), "allowed": verdicts["yes"], "conditional": verdicts["conditional"], "unknown": verdicts["unknown"], "no": verdicts["no"], "programmes": len(progs), "earn_yes": earn,
            "kinds": [{"name": k, "n": n} for k, n in kinds.most_common(12)], "games": [{"name": label[g], "n": n, "who": who_game[g][:4]} for g, n in games.most_common(12)],
            "platforms": [{"name": p, "n": n} for p, n in plats.most_common()], "best": ranked[:8], "plan": plan,
            "programme_list": sorted(progs, key=lambda x: (x["allows"] != "yes", not x["programme"].get("pay")))[:10],
            "avoid": [{"id": l["id"], "name": l["name"], "text": l.get("permission_text") or ""} for l in leads if l["allows"] == "no"][:10]}


def update_lead(uid, lid: str, status: Optional[str], notes: Optional[str]) -> Optional[Dict]:
    try:
        d = ResearchLead.find_one(id=oid(lid))
    except ValueError:
        return None
    if not d or d.get("user_id") != str(uid):
        return None
    upd = {}
    if status is not None:
        if status not in STATUSES:
            raise ValueError("Choose a status from the list.")
        upd["status"] = status
    if notes is not None:
        upd["notes"] = _s(notes, 1000)
    if upd:
        ResearchLead.objects(id=d["_id"]).update(**{f"set__{k}": v for k, v in upd.items()})
    return lead_view(ResearchLead.find_one(id=d["_id"]))


def delete_lead(uid, lid: str) -> bool:
    d = update_lead(uid, lid, None, None)
    if not d:
        return False
    ResearchLead.objects(id=oid(lid)).delete()
    return True


def creator_of(lead: Dict) -> Optional[Dict]:
    """The Twitch or YouTube creator behind a lead, when its page shows one (so it can go into the studio's creator list)."""
    u = lead.get("url") or ""
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]{3,25})(?:[/?#]|$)", u)
    if m and m.group(1).lower() not in ("videos", "directory", "downloads", "p", "jobs"):
        return {"platform": "twitch", "name": m.group(1).lower()}
    m = re.match(r"^(https://(?:www\.)?youtube\.com/(?:@[\w.\-]{3,60}|channel/UC[\w\-]{20,24}))", u)
    if m:
        return {"platform": "youtube", "name": m.group(1)}
    return None
