"""Web research with Gemini or DeepSeek (Claude's own search lives in claude_util.ask_with_search).

- Gemini searches the web itself (Google Search grounding). The pages it used come back as sources.
- DeepSeek cannot browse. So DeepSeek writes the search queries, this module runs them through an official search API (Tavily or Brave
  Search: a free key, see Settings), downloads and cleans the pages, and DeepSeek READS them. Gemini is not needed. Every quote DeepSeek
  returns has to be a page that was really downloaded, which the caller checks like it does for Claude. Search engines are not scraped.

Both return (answer text, web addresses really used, searches, tokens in, tokens out) and record the real usage.
"""
import html as _html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

import requests

from app.engine import gemini_util

UA = {"User-Agent": "ClipStudio-research/1.0 (reads public pages for the owner of this studio)", "Accept-Language": "en"}
GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-pro"]
DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-reasoner"]
PAGE_CHARS = 7000
PAGES = {6: 5, 12: 9, 24: 15}        # searches allowed -> pages DeepSeek reads


def gemini_ready() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def deepseek_ready() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def gemini_models() -> List[str]:
    return list(dict.fromkeys([os.environ.get("GEMINI_MODEL") or GEMINI_MODELS[0]] + GEMINI_MODELS))


def deepseek_models() -> List[str]:
    return list(dict.fromkeys([os.environ.get("DEEPSEEK_MODEL") or DEEPSEEK_MODELS[0]] + DEEPSEEK_MODELS))


def _record(provider: str, task: str, tin: int, tout: int, ok: bool = True) -> None:
    try:
        from app.models import UsageEvent
        UsageEvent(user_id=os.environ.get("CLIPSTUDIO_USER_ID") or None, video_id="research", kind="llm", provider=provider, task=task, tokens_in=tin, tokens_out=tout, ok=ok).save()
        from app.models import AiCall
        AiCall.log(provider, "text", task, tin, tout, ok=ok)
    except Exception:
        pass


def _resolve(uri: str) -> str:
    """Gemini names its sources through a Google redirect address; the real page is where it points."""
    if "vertexaisearch.cloud.google.com" not in uri and "grounding-api-redirect" not in uri:
        return uri
    try:
        r = requests.head(uri, allow_redirects=False, timeout=10, headers=UA)
        return r.headers.get("Location") or uri
    except requests.RequestException:
        return uri


def gemini_search(system: str, user_text: str, model_id: str = "", max_tokens: int = 16000, timeout: int = 300) -> Tuple[str, List[str], int, int, int]:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("Research with Gemini needs the Gemini key (Settings -> Accounts & keys).")
    model = (model_id or gemini_models()[0]).strip()
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "tools": [{"google_search": {}}], "generationConfig": {"maxOutputTokens": int(max_tokens)}}
    try:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=timeout)
    except requests.RequestException as e:
        raise RuntimeError(f"Gemini could not be reached ({type(e).__name__})")
    if r.status_code != 200:
        msg = ""
        try:
            msg = (r.json().get("error") or {}).get("message", "")[:200]
        except Exception:
            pass
        raise RuntimeError(f"Gemini failed (HTTP {r.status_code}): {msg}")
    d = r.json()
    cand = (d.get("candidates") or [{}])[0]
    text = "\n".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [] if p.get("text")).strip()
    gm = cand.get("groundingMetadata") or {}
    uris = [(c.get("web") or {}).get("uri") for c in gm.get("groundingChunks") or []]
    uris = [u for u in dict.fromkeys(uris) if u]
    with ThreadPoolExecutor(8) as ex:
        sources = [u for u in ex.map(_resolve, uris[:40]) if u]
    tin, tout = gemini_util.usage_of(d)
    searches = len(gm.get("webSearchQueries") or [])
    _record("gemini", "research", tin, tout)
    if not text:
        raise RuntimeError("Gemini gave no answer" + (f" ({cand.get('finishReason')})" if cand.get("finishReason") else ""))
    return text, list(dict.fromkeys(sources)), searches, tin, tout


# ---------------------------------------------------------------- reading pages for DeepSeek
def page_text(url: str) -> str:
    """The readable text of a page ('' if it cannot be downloaded or is not a web page)."""
    try:
        r = requests.get(url, headers=UA, timeout=15, stream=True)
        ctype = (r.headers.get("Content-Type") or "").lower()
        if r.status_code != 200 or ("html" not in ctype and "text" not in ctype):
            r.close()
            return ""
        raw = r.raw.read(600_000, decode_content=True)
        r.close()
    except (requests.RequestException, OSError):
        return ""
    t = raw.decode("utf-8", "ignore")
    t = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return " ".join(_html.unescape(t).split())[:PAGE_CHARS]


def search_ready() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY") or os.environ.get("BRAVE_API_KEY"))


def search_web(query: str, n: int = 6) -> List[str]:
    """The addresses of the first results of a web search made through an official search API (Tavily or Brave Search, each has a free plan).
    Raises RuntimeError with a plain message when the key is missing or refused."""
    tav, brave = os.environ.get("TAVILY_API_KEY", ""), os.environ.get("BRAVE_API_KEY", "")
    try:
        if tav:
            r = requests.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {tav}"}, json={"query": query, "max_results": n, "search_depth": "basic"}, timeout=30)
            name, pick = "Tavily", lambda d: [x.get("url") for x in d.get("results") or []]
        elif brave:
            r = requests.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": n}, headers={"X-Subscription-Token": brave, "Accept": "application/json"}, timeout=30)
            name, pick = "Brave Search", lambda d: [x.get("url") for x in (d.get("web") or {}).get("results") or []]
        else:
            raise RuntimeError("DeepSeek cannot browse. Add a free search key (Tavily or Brave Search) in Settings -> Accounts & keys.")
    except requests.RequestException as e:
        raise RuntimeError(f"The search service could not be reached ({type(e).__name__})")
    if r.status_code in (401, 403):
        raise RuntimeError(f"{name} refused the key. Check it in Settings -> Accounts & keys.")
    if r.status_code == 429 or r.status_code == 432:
        raise RuntimeError(f"{name}: the search limit of your plan is used up.")
    if r.status_code != 200:
        raise RuntimeError(f"{name} search failed (HTTP {r.status_code}).")
    try:
        urls = pick(r.json())
    except ValueError:
        return []
    return [u for u in dict.fromkeys(urls) if isinstance(u, str) and u.startswith(("http://", "https://"))][:n]


def plan_queries(find_text: str, n: int, model_id: str = "") -> Tuple[List[str], int, int]:
    """DeepSeek decides what to search for: short, specific queries work far better on a plain search engine than a long question."""
    from app.engine import llm
    prompt = (f"{find_text}\n\nWrite {n} different web search queries that would find OFFICIAL pages answering this: a creator's clip policy or FAQ, a clipping programme or campaign page, "
              "a marketplace such as Whop or Clipping campaigns, a Twitch or YouTube help page about clips. Each query is 3 to 8 words, in plain English, no quotation marks. "
              'Vary them: some about creators, some about programmes, some about pay. Return JSON: {"queries": ["...", "..."]}')
    llm._deepseek_usage.usage = (0, 0)
    text = llm._deepseek(prompt, 90, False, 600, model_id)
    tin, tout = getattr(llm._deepseek_usage, "usage", (0, 0))
    m = re.search(r"\[.*?\]", text, re.S)
    try:
        qs = json.loads(m.group(0)) if m else []
    except ValueError:
        qs = []
    qs = [" ".join(str(q).split())[:90] for q in qs if isinstance(q, str) and len(q.strip()) > 3]
    return list(dict.fromkeys(qs))[:n], tin or len(prompt) // 4, tout or len(text) // 4


def deepseek_research(system: str, find_text: str, answer_text: str, searches: int, model_id: str = "", max_tokens: int = 8000, timeout: int = 300) -> Tuple[str, List[str], int, int, int]:
    """DeepSeek on its own: it writes the search queries, this module runs them on Bing and downloads the pages, and DeepSeek reads the pages.
    find_text: what to look for. answer_text: the question plus the JSON shape. No other AI key is needed."""
    from app.engine import llm
    if not llm.deepseek_ready():
        raise RuntimeError("Research with DeepSeek needs the DeepSeek key (Settings -> Accounts & keys).")
    if not search_ready():
        raise RuntimeError("DeepSeek cannot browse the web. Add a free search key (Tavily or Brave Search) in Settings -> Accounts & keys; no Gemini needed.")
    queries, p_in, p_out = plan_queries(find_text, min(searches, 10), model_id)
    if not queries:
        raise RuntimeError("DeepSeek did not write any search queries. Try again.")
    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(search_web, queries))
    n_searches = sum(1 for r in results if r)
    found: List[str] = []
    for i in range(8):                                  # round robin, so every query gets its best pages in before any gets its fifth
        for r in results:
            if i < len(r) and r[i] not in found:
                found.append(r[i])
    if not found:
        raise RuntimeError("The web search returned nothing for these queries. Try again, or use Claude or Gemini.")
    limit = PAGES.get(searches, 9)
    with ThreadPoolExecutor(8) as ex:
        texts = list(ex.map(page_text, found[:limit * 2]))
    pages = [(u, t) for u, t in zip(found, texts) if len(t) > 200][:limit]
    if not pages:
        raise RuntimeError("None of the pages found could be downloaded. Try another search or another AI.")
    block = "\n\n".join(f"[PAGE {i + 1}] {u}\n{t}" for i, (u, t) in enumerate(pages))
    prompt = (f"{system}\n\nYou cannot browse. The ONLY pages you may use are the ones below; each starts with its address. Every evidence url must be one of these addresses "
              f"and every quote must be copied from that page's text.\n\n{block}\n\n---\n{answer_text}")
    llm._deepseek_usage.usage = (0, 0)
    text = llm._deepseek(prompt, timeout, False, max_tokens, model_id)
    d_in, d_out = getattr(llm._deepseek_usage, "usage", (0, 0))
    _record("deepseek", "research", d_in or len(prompt) // 4, d_out or len(text) // 4)
    _record("deepseek", "research-queries", p_in, p_out)
    return text, [u for u, _ in pages], n_searches, p_in + d_in, p_out + d_out
