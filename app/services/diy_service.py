"""Do-it-yourself options for members: write the title, the commentary or the thumbnail themselves, choose their own clip,
or choose which AI does the writing. Whatever the AI does not do costs no tokens (billing follows real usage).

The owner can switch each option on or off. The one thing no option can skip is the content-safety review.
"""
import re
from typing import Dict, Optional

from mongoengine import Q

from app.models import Job, System, UsageEvent, raw
from app.services import token_service as tokens

FLAGS = {"own_metadata": "Members may write their own title, description and tags",
         "own_thumbnail": "Members may skip the AI thumbnail and upload their own",
         "own_commentary": "Members may write their own commentary",
         "own_source": "Members may pick their own YouTube clip and the part of it",
         "ai_choice": "Members may choose which AI writes (cheaper or better, or none)",
         "pick_creator": "Members may choose a Twitch or YouTube creator to take clips from",
         "tier_medium": "Members may use the Medium thumbnail level (Gemini redraws the real frame; costs tokens)",
         "tier_high": "Members may use the High thumbnail level (Claude plans it, Gemini draws it; costs more tokens)",
         "research": "Members may use the clipping research (Claude searches the web; the cost is yours, not billed in tokens)"}
DEFAULT_OFF = {"pick_creator", "tier_high", "research"}          # a named creator is a bigger copyright risk than a game search, so the owner switches it on
AI_CHOICES = ("budget", "balanced", "quality", "off")
YT_URL = re.compile(r"^https://(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|live/)|youtu\.be/)[\w\-]{6,15}[\w\-&=%.?/]*$")

# average AI tokens per task in one Short, used for the price estimate until real runs have been measured
DEFAULT_TASK_TOKENS = {"scoring": 900, "moments": 2100, "metadata": 1000, "commentary": 240, "safety": 6800}
DEFAULT_ORDER = {"scoring": "gemini", "moments": "deepseek", "metadata": "deepseek", "commentary": "deepseek", "safety": "gemini"}


def flags() -> Dict:
    doc = raw(System.objects(id="diy").first()) or {}
    return {k: bool(doc.get(k, k not in DEFAULT_OFF)) for k in FLAGS}


def set_flags(data: Dict) -> Dict:
    upd = {k: bool(data[k]) for k in FLAGS if k in data}
    if upd:
        System.objects(id="diy").update_one(upsert=True, **{f"set__{k}": v for k, v in upd.items()})
    return flags()


def clean_options(d: Dict, mode: str, audio: str, owner: bool) -> Dict:
    """Check what a member asked for against the owner's switches. Returns the cleaned options (or raises ValueError)."""
    f = flags()

    def allowed(flag: str, what: str) -> None:
        if not owner and not f[flag]:
            raise ValueError(f"The owner has switched off: {what}.")

    out: Dict = {}
    ai = str(d.get("ai_text") or "").strip().lower()
    if ai:
        if ai not in AI_CHOICES:
            raise ValueError(f"ai_text must be one of {', '.join(AI_CHOICES)}")
        if ai != "balanced":
            allowed("ai_choice", "choosing which AI writes")
        out["ai_text"] = ai
    if str(d.get("own_title") or "").strip():
        allowed("own_metadata", "writing your own title and description")
        out["own_title"] = " ".join(str(d["own_title"]).split())[:90]
        if str(d.get("own_description") or "").strip():
            out["own_description"] = str(d["own_description"]).strip()[:1500]
        if d.get("own_tags"):
            tags = d["own_tags"] if isinstance(d["own_tags"], list) else str(d["own_tags"]).split(",")
            out["own_tags"] = ",".join(str(t).strip().lstrip("#") for t in tags if str(t).strip())[:600]
    if d.get("thumbnail") == "frame":
        allowed("own_thumbnail", "skipping the AI thumbnail")
        out["thumbnail"] = "frame"
    if str(d.get("own_commentary") or "").strip():
        allowed("own_commentary", "writing your own commentary")
        if mode != "auto-short" or audio != "replace":
            raise ValueError("Your own commentary needs a Short with the audio mode 'Replace'.")
        out["own_commentary"] = " ".join(str(d["own_commentary"]).split())[:1200]
    if isinstance(d.get("creator"), dict) and str(d["creator"].get("name") or "").strip():
        allowed("pick_creator", "choosing a creator")
        if str(d.get("own_url") or "").strip():
            raise ValueError("Choose either a creator or your own clip link, not both.")
        from app.engine import discovery
        plat, ident = discovery.parse_creator(d["creator"].get("platform"), d["creator"]["name"])
        out["creator"] = {"platform": plat, "name": ident}
    if str(d.get("own_url") or "").strip():
        allowed("own_source", "choosing your own clip")
        if mode != "auto-short":
            raise ValueError("Your own clip link works for Shorts.")
        url = str(d["own_url"]).strip()
        if len(url) > 300 or not YT_URL.match(url):
            raise ValueError("Paste a normal YouTube link (youtube.com/watch?v=... or youtu.be/...).")
        try:
            start, end = float(d.get("own_start")), float(d.get("own_end"))
        except (TypeError, ValueError):
            raise ValueError("Enter the start and end of the part you want, in seconds.")
        if start < 0 or end - start < 15 or end - start > 58:
            raise ValueError("Choose a part between 15 and 58 seconds long.")
        out.update(own_url=url, own_start=start, own_end=end)
    return out


def estimate() -> Dict:
    """What each part of a Short costs a member at today's prices (tokens), from the last measured Shorts, so the Create page can
    show the price change live. Old full-strength safety reviews (8 large frames, about 9,000 tokens each) are ignored."""
    p = tokens.pricing()
    jobs = Job.find_all(status="done", mode="auto-short", order=("-finished_at",), limit=10, only=("_id",))
    ids = [str(j["_id"]) for j in jobs]
    per_task: Dict[str, float] = {}
    images, n = 0.0, 0
    if ids:
        n = len({e["_id"]["j"] for e in UsageEvent.objects(job_id__in=ids, ok=True).aggregate([{"$group": {"_id": {"j": "$job_id"}}}])})
        q = UsageEvent.objects(Q(job_id__in=ids) & Q(ok=True) & Q(kind="llm") & (Q(task__ne="safety") | Q(tokens_in__lte=8000)))
        for r in q.aggregate([{"$group": {"_id": "$task", "t": {"$sum": {"$add": ["$tokens_in", "$tokens_out"]}}}}]):
            per_task[r["_id"]] = r["t"] / max(1, n)
        images = sum(r["u"] for r in UsageEvent.objects(job_id__in=ids, ok=True, kind="image").aggregate([{"$group": {"_id": None, "u": {"$sum": "$units"}}}])) / max(1, n)
    parts = {}
    for t, dflt in DEFAULT_TASK_TOKENS.items():
        tok = per_task.get(t) or dflt
        d, g = tok / 1000 * p["deepseek_per_1k"], tok / 1000 * p["gemini_per_1k"]
        parts[t] = {"deepseek": round(d, 2), "gemini": round(g, 2), "default": round(g if DEFAULT_ORDER[t] == "gemini" else d, 2)}
    return {"parts": parts, "image": round(max(images, 1.0) * p["image_free"], 2), "upload": tokens.upload_fee("short"), "measured_videos": n}


def options_for(uid_is_owner: bool) -> Dict:
    return {"flags": flags(), "estimate": estimate(), "owner": uid_is_owner}
