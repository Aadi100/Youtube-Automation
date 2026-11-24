"""What the platforms charge the owner, per model: the catalogue behind Settings -> Pricing & costs.

Prices are US dollars from each platform's own price page, read on CHECKED. They change: the owner can edit every number on the page, and the
catalogue only fills the boxes. `verified` False = the price came from a summary of a long page and should be checked on the live page.
kind: text (dollars per 1M tokens, in / out), image (dollars per picture), search (dollars per search).
"""
from typing import Dict, List, Optional

CHECKED = "2026-11-23"
SOURCES = {
    "claude": "https://platform.claude.com/docs/en/about-claude/pricing",
    "gemini": "https://aistudio.google.com/docs/pricing",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing/",
    "search": "https://help.tavily.com/articles/8816424538-pricing",
}
# DeepSeek is half price outside peak hours (Mon-Fri 01:00-04:00 and 06:00-10:00 UTC are the peak): 35 of the 168 hours of a week
PEAK_SHARE = 35 / 168


def _blend(peak: float, off: float) -> float:
    return round(PEAK_SHARE * peak + (1 - PEAK_SHARE) * off, 3)


def _t(platform, mid, name, pin, pout, note="", verified=True, deprecated=False, nxt=None) -> Dict:
    return {"kind": "text", "platform": platform, "id": mid, "name": name, "in": pin, "out": pout, "note": note, "verified": verified, "deprecated": deprecated, "next": nxt}


CATALOG: List[Dict] = [
    # ---- Claude (the page lists models by name only; the ids are the ones the Claude API accepts for them)
    _t("claude", "claude-fable-5-2", "Fable 5.2", 8, 40),
    _t("claude", "claude-opus-5-5", "Opus 5.5", 4, 20),
    _t("claude", "claude-sonnet-5-5", "Sonnet 5.5", 2, 10),
    _t("claude", "claude-haiku-5-5", "Haiku 5.5", 0.10, 0.50, "Prompts over 100K tokens cost $0.50 in / $2.50 out."),
    _t("claude", "claude-fable-5-1", "Fable 5.1", 10, 50),
    _t("claude", "claude-fable-5", "Fable 5", 10, 50),
    _t("claude", "claude-opus-5", "Opus 5", 5, 25),
    _t("claude", "claude-opus-4-8", "Opus 4.8", 5, 25),
    _t("claude", "claude-opus-4-7", "Opus 4.7", 5, 25),
    _t("claude", "claude-opus-4-6", "Opus 4.6", 5, 25),
    _t("claude", "claude-opus-4-5", "Opus 4.5", 5, 25),
    _t("claude", "claude-sonnet-5", "Sonnet 5", 2, 10),
    _t("claude", "claude-sonnet-4-6", "Sonnet 4.6", 3, 15),
    _t("claude", "claude-haiku-4-5", "Haiku 4.5", 1, 5),
    # ---- Gemini text
    _t("gemini", "gemini-3.8-flash", "3.8 Flash", 0.75, 3.75, "Introductory price until Dec 31, 2026.", nxt={"in": 1.5, "out": 7.5, "from": "2027-01-01"}),
    _t("gemini", "gemini-3.6-flash", "3.6 Flash", 0.75, 3.75, "Introductory price until Dec 31, 2026.", nxt={"in": 1.5, "out": 7.5, "from": "2027-01-01"}),
    _t("gemini", "gemini-3.5-flash-lite", "3.5 Flash-Lite", 0.30, 2.50),
    _t("gemini", "gemini-4-hydrogen", "4 Hydrogen", 1.5, 7.5),
    _t("gemini", "gemini-4-neon", "4 Neon", 3, 15),
    _t("gemini", "gemini-4-carbon", "4 Carbon", 2, 10, "Price changes on Dec 1, 2026.", nxt={"in": 4, "out": 20, "from": "2026-12-01"}),
    _t("gemini", "gemini-4-argon", "4 Argon", 2, 10, "Price changes on Dec 1, 2026.", nxt={"in": 4, "out": 20, "from": "2026-12-01"}),
    _t("gemini", "gemini-3.1-pro-preview", "3.1 Pro (preview)", 2, 12, "Above 200K tokens: $4 in / $18 out.", verified=False),
    _t("gemini", "gemini-3-flash-preview", "3 Flash (preview)", 0.50, 3, verified=False),
    _t("gemini", "gemini-3.1-flash-lite", "3.1 Flash-Lite", 0.25, 1.50, verified=False),
    _t("gemini", "gemini-2.5-pro", "2.5 Pro", 1.25, 10, "Deprecated; moves to Gemini 3.8 Flash on Dec 1, 2026.", verified=False, deprecated=True),
    _t("gemini", "gemini-2.5-flash", "2.5 Flash", 0.30, 2.50, "Deprecated; moves to 3.5 Flash-Lite on Dec 1, 2026.", verified=False, deprecated=True),
    _t("gemini", "gemini-2.5-flash-lite", "2.5 Flash-Lite", 0.10, 0.40, verified=False),
    # ---- DeepSeek (off-peak is half of peak; "average" is the week's mix of both)
    _t("deepseek", "deepseek-flash", "deepseek-flash, average of peak and off-peak", _blend(0.30, 0.15), _blend(1.20, 0.60), "Peak $0.30 / $1.20, off-peak $0.15 / $0.60. Peak hours: Mon-Fri 01-04 and 06-10 UTC."),
    _t("deepseek", "deepseek-flash@peak", "deepseek-flash, peak hours", 0.30, 1.20),
    _t("deepseek", "deepseek-flash@off", "deepseek-flash, off-peak", 0.15, 0.60),
    _t("deepseek", "deepseek-v4-pro", "deepseek-v4-pro, average of peak and off-peak", _blend(1.32, 0.66), _blend(3.96, 1.98), "Peak $1.32 / $3.96, off-peak $0.66 / $1.98."),
    _t("deepseek", "deepseek-v4-pro@peak", "deepseek-v4-pro, peak hours", 1.32, 3.96),
    _t("deepseek", "deepseek-v4-pro@off", "deepseek-v4-pro, off-peak", 0.66, 1.98),
]
IMAGES: List[Dict] = [
    {"kind": "image", "platform": "gemini", "id": "gemini-2.5-flash-image", "name": "2.5 Flash Image", "per": 0.039, "note": "Deprecated: shuts down March 15, 2027.", "verified": True, "deprecated": True},
    {"kind": "image", "platform": "gemini", "id": "gemini-3.1-flash-lite-image", "name": "3.1 Flash Lite Image", "per": 0.0336, "note": "At 1K size. Cheapest.", "verified": False, "deprecated": False},
    {"kind": "image", "platform": "gemini", "id": "gemini-3.1-flash-image", "name": "3.1 Flash Image", "per": 0.067, "note": "At 1K size ($0.101 at 2K, $0.151 at 4K).", "verified": False, "deprecated": False},
    {"kind": "image", "platform": "gemini", "id": "gemini-3-pro-image", "name": "3 Pro Image", "per": 0.134, "note": "At 1K or 2K size ($0.24 at 4K).", "verified": False, "deprecated": False},
]
SEARCHES: List[Dict] = [
    {"kind": "search", "platform": "claude", "id": "claude-web-search", "name": "Claude web search", "per": 0.01, "note": "$10 per 1,000 searches, plus the tokens of the pages it reads.", "verified": True, "deprecated": False},
    {"kind": "search", "platform": "tavily", "id": "tavily-basic", "name": "Tavily search (for DeepSeek research)", "per": 0.008, "note": "1,000 free searches a month. A third-party figure.", "verified": False, "deprecated": False},
    {"kind": "search", "platform": "brave", "id": "brave-search", "name": "Brave Search (for DeepSeek research)", "per": 0.005, "note": "$5 per 1,000, with $5 free credit a month. A third-party figure.", "verified": False, "deprecated": False},
]


def all_rows() -> List[Dict]:
    return CATALOG + IMAGES + SEARCHES


def find(model_id: str, platform: str = "") -> Optional[Dict]:
    """The catalogue row for a model id as typed in Settings: an exact id, or the id plus a date / suffix (claude-haiku-4-5-20251001)."""
    mid = (model_id or "").strip().lower()
    if not mid:
        return None
    rows = [r for r in all_rows() if not platform or r["platform"] == platform]
    for r in rows:
        if r["id"].lower() == mid:
            return r
    best = None
    for r in rows:
        rid = r["id"].lower().split("@")[0]
        if mid.startswith(rid) and (best is None or len(rid) > len(best["id"].split("@")[0])):
            best = r
    return best
