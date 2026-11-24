"""Settings -> Pricing & costs: one place for what the platforms charge the owner, what one studio token is worth, and what members pay.

It reads and writes the same data as the price list on the Users page and the real costs on the Reports page (token_service); nothing new is stored.
The page needs three things from here: the model catalogue with what Settings uses today, the owner's real usage mix (how much of the AI tokens
are input and how much output, because the platforms charge them differently) and a typical Short / compilation, and a helper that turns
"my costs + my margin" into token prices.
"""
import math
import os
from datetime import timedelta
from typing import Dict

from app.models import UsageEvent, now
from app.services import price_catalog as cat
from app.services import token_service as tk

DEFAULT_SHARE_IN = 0.8          # when nothing was measured yet: about 80% of AI tokens are input (the clips and the instructions), 20% output
TYPICAL_DEFAULT = {"short": {"gemini_tokens": 6500, "deepseek_tokens": 1300, "claude_tokens": 0, "images": 1.0},
                   "compilation": {"gemini_tokens": 40000, "deepseek_tokens": 25000, "claude_tokens": 0, "images": 3.0}}


def in_use() -> Dict:
    """Which models Settings uses today, and the catalogue row each one matches (None = an alias or a name the catalogue does not know)."""
    from app.engine import ai_art, claude_util
    rows = {"gemini": os.environ.get("GEMINI_MODEL") or "gemini-flash-latest", "deepseek": os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat",
            "claude": claude_util.model(), "claude_research": claude_util.research_model(), "gemini_image": ai_art.GEMINI_MODEL}
    out = {}
    for k, mid in rows.items():
        plat = "claude" if k.startswith("claude") else "deepseek" if k == "deepseek" else "gemini"
        row = cat.find(mid, plat)
        out[k] = {"model": mid, "match": row["id"] if row else None}
    return out


def usage_mix(days: int = 90) -> Dict:
    """For each AI service: how many tokens were input and how many output, so a blended price per 1,000 tokens can be worked out."""
    since = now() - timedelta(days=days)
    out = {p: {"tin": 0, "tout": 0} for p in ("gemini", "deepseek", "claude")}
    for r in UsageEvent.objects(t__gte=since, ok=True, kind="llm").aggregate([{"$group": {"_id": "$provider", "tin": {"$sum": "$tokens_in"}, "tout": {"$sum": "$tokens_out"}}}]):
        if r["_id"] in out:
            out[r["_id"]] = {"tin": int(r["tin"] or 0), "tout": int(r["tout"] or 0)}
    res = {}
    for p, v in out.items():
        total = v["tin"] + v["tout"]
        res[p] = {"tin": v["tin"], "tout": v["tout"], "share_in": round(v["tin"] / total, 3) if total >= 2000 else DEFAULT_SHARE_IN, "measured": total >= 2000}
    return res


def typical(days: int = 90) -> Dict:
    """What one finished Short and compilation really used (from your own videos), or sensible numbers before there is any history."""
    from app.services import report_service
    avg = {}
    try:
        avg = report_service.build_report(days).get("average") or {}
    except Exception:
        avg = {}
    out = {}
    for k, d in TYPICAL_DEFAULT.items():
        a = avg.get(k)
        out[k] = ({"gemini_tokens": a["gemini_tokens"], "deepseek_tokens": a["deepseek_tokens"], "claude_tokens": 0, "images": a["images"], "videos": a["videos"], "measured": True} if a
                  else {**d, "videos": 0, "measured": False})
    return out


def blended_per_1k(pin: float, pout: float, share_in: float) -> float:
    """Dollars the platform charges per 1,000 AI tokens, given how the tokens split between input and output."""
    return (share_in * pin + (1 - share_in) * pout) / 1000.0


def _ceil(x: float, places: int = 2) -> float:
    f = 10 ** places
    return math.ceil(x * f - 1e-9) / f


def suggest(costs: Dict, token_usd: float, margin_pct: float, mix: Dict) -> Dict:
    """Token prices that give `margin_pct` on top of what the platform charges: price = real cost x (1 + margin) / value of one token.
    Only the AI and picture prices are suggested; uploads and the reserve are the owner's own choice."""
    if token_usd <= 0:
        raise ValueError("One token must be worth more than $0.")
    if not 0 <= margin_pct <= 10000:
        raise ValueError("The margin must be between 0% and 10,000%.")
    m = 1 + margin_pct / 100.0
    out = {}
    for prov, key, kin, kout in (("gemini", "gemini_per_1k", "gemini_in_per_1m", "gemini_out_per_1m"), ("deepseek", "deepseek_per_1k", "deepseek_in_per_1m", "deepseek_out_per_1m"),
                                 ("claude", "claude_per_1k", "claude_in_per_1m", "claude_out_per_1m")):
        c = blended_per_1k(float(costs.get(kin) or 0), float(costs.get(kout) or 0), float((mix.get(prov) or {}).get("share_in", DEFAULT_SHARE_IN)))
        if c > 0:
            out[key] = max(0.01, _ceil(c * m / token_usd))
    if float(costs.get("image_gemini_usd") or 0) > 0:
        out["image_gemini"] = max(0.01, _ceil(float(costs["image_gemini_usd"]) * m / token_usd))
    return out


def overview() -> Dict:
    return {"checked": cat.CHECKED, "sources": cat.SOURCES, "catalog": cat.all_rows(), "in_use": in_use(), "mix": usage_mix(), "typical": typical(),
            "pricing": tk.pricing(), "costs": tk.real_costs(), "defaults": {"pricing": tk.DEFAULT_PRICING, "token_usd": tk.TOKEN_USD_DEFAULT}}


def save(data: Dict) -> Dict:
    """Save the real costs and the member prices together (each is checked first, so a bad value saves nothing)."""
    costs, pricing = data.get("costs") or {}, data.get("pricing") or {}
    if not isinstance(costs, dict) or not isinstance(pricing, dict):
        raise ValueError("Send the costs and the prices as two lists.")
    if "token_usd" in costs and float(costs["token_usd"] or 0) <= 0:
        raise ValueError("One token must be worth more than $0.")
    for k, v in {**costs, **pricing}.items():
        if v not in (None, ""):
            try:
                float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number")
    if costs:
        tk.set_real_costs(costs)
    if pricing:
        tk.set_pricing(pricing)
    return overview()
