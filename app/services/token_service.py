"""Token system: members pay for what a video actually used; the owner (who pays the AI and image services) sets the prices.

How a bill works
  1. When a video is queued, a RESERVE (hold) is taken from the member's balance, so nobody can start something they cannot pay for.
  2. While the pipeline runs it writes a usage record for every AI call, image, voice line, caption run and safety check
     (what the AI service itself reported: tokens in / tokens out ...). Failed calls are recorded as failed and are never billed.
  3. When the video is finished the usage is priced with the owner's price list. The member pays exactly that;
     the unused part of the reserve goes back. If the video fails or is cancelled the whole reserve goes back: nothing is charged.
  4. Every upload to YouTube has its own price (set by the owner): taken before the upload, returned if the upload fails.
  5. The owner is never charged, but gets the very same calculation as a record ("what this would have cost").
Every balance change is in the ledger, and every video keeps an itemised receipt.
"""
import math

LOW_TOKENS = 20          # below this a member is told their balance is running low
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.models import Job, System, TokenLedger, UsageEvent, User, Video, now, oid, raw

# Owner-editable. Prices are in studio tokens. "per_1k" = tokens charged per 1,000 AI tokens as reported by the AI service.
DEFAULT_PRICING = {
    "gemini_per_1k": 2.0,            # Gemini text and image-review calls (input + output)
    "deepseek_per_1k": 1.0,          # DeepSeek text calls (input + output)
    "claude_per_1k": 3.5,            # Claude, the High thumbnail level: it looks at frames and plans the thumbnail (input + output)
    "image_free": 1.0,               # one background image from the free image service
    "image_gemini": 5.0,             # one background image from Gemini
    "tts_per_1k_chars": 0.0,         # narrator voice, per 1,000 characters (free service; raise it if you want to charge for server time)
    "whisper_per_min": 0.0,          # captions: per minute of speech transcribed (runs on your server)
    "safety_local_per_clip": 0.0,    # the local nudity detector, per clip checked (runs on your server)
    "upload_short": 3.0,             # every upload of a Short to YouTube
    "upload_compilation": 8.0,       # every upload of a compilation
    "hold_short": 20.0,              # reserved when a Short is queued (the unused part is returned)
    "hold_compilation": 80.0,        # reserved when a compilation is queued
    "signup_bonus": 0,               # welcome gift for new members
    "daily_uploads": 1,              # uploads per member per day (the default; the owner can set it per member too)
}
INT_KEYS = {"signup_bonus", "daily_uploads"}


def pricing() -> Dict:
    doc = raw(System.objects(id="pricing").first()) or {}
    out = {}
    for k, v in DEFAULT_PRICING.items():
        x = doc.get(k, v)
        out[k] = int(x) if k in INT_KEYS else float(x)
    return out


def set_pricing(data: Dict) -> Dict:
    upd = {}
    for k in DEFAULT_PRICING:
        if k in data and data[k] not in (None, ""):
            try:
                v = float(data[k])
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number")
            if not 0 <= v <= (1000 if k == "daily_uploads" else 100000):
                raise ValueError(f"{k} must be between 0 and {1000 if k == 'daily_uploads' else 100000}")
            upd[k] = int(v) if k in INT_KEYS else round(v, 4)
    if upd:
        System.objects(id="pricing").update_one(upsert=True, **{f"set__{k}": v for k, v in upd.items()})
    return pricing()


# What the services really charge the owner, in US dollars (the owner types these in; 0 = not entered / free tier). Used for records only.
REAL_COST_KEYS = ["gemini_in_per_1m", "gemini_out_per_1m", "deepseek_in_per_1m", "deepseek_out_per_1m", "claude_in_per_1m", "claude_out_per_1m", "claude_search_usd", "image_gemini_usd", "image_free_usd", "token_usd"]
TOKEN_USD_DEFAULT = 0.01      # what one studio token is worth in dollars (the owner sets it: it turns tokens billed into revenue)


def real_costs() -> Dict:
    doc = raw(System.objects(id="costs").first()) or {}
    return {k: float(doc.get(k, TOKEN_USD_DEFAULT if k == "token_usd" else 0)) for k in REAL_COST_KEYS}


def set_real_costs(data: Dict) -> Dict:
    upd = {}
    for k in REAL_COST_KEYS:
        if k in data and data[k] not in (None, ""):
            v = float(data[k])
            if not 0 <= v <= 100000:
                raise ValueError(f"{k} must be between 0 and 100000")
            upd[k] = v
    if upd:
        System.objects(id="costs").update_one(upsert=True, **{f"set__{k}": v for k, v in upd.items()})
    return real_costs()


def usd_of(kind: str, provider: str, tin: int, tout: int, units: float, r: Dict) -> float:
    """What one usage record really cost the owner in dollars, at the rates the owner entered."""
    if kind == "llm":
        a, b = ((r["gemini_in_per_1m"], r["gemini_out_per_1m"]) if provider == "gemini" else (r["claude_in_per_1m"], r["claude_out_per_1m"]) if provider == "claude"
                else (r["deepseek_in_per_1m"], r["deepseek_out_per_1m"]))
        return tin / 1e6 * a + tout / 1e6 * b
    if kind == "image":
        return units * (r["image_gemini_usd"] if provider == "gemini" else r["image_free_usd"])
    if kind == "web_search":
        return units * r["claude_search_usd"]
    return 0.0


def _up(x: float) -> int:
    return int(math.ceil(x - 1e-9)) if x > 0 else 0


def cost(mode: str, source: str = "") -> int:
    """What is reserved when a video of this kind is queued (the member pays only what is really used)."""
    p = pricing()
    return _up(p["hold_compilation"] if "compilation" in mode else p["hold_short"])


def balance(uid) -> int:
    u = User.objects(id=oid(str(uid))).only("tokens").first()
    return int(u.tokens or 0) if u else 0


def _ledger(uid, delta: int, after: int, reason: str, ref: Optional[str]) -> None:
    TokenLedger(user_id=str(uid), delta=delta, balance=after, reason=reason, ref=ref, t=now()).save()


def adjust(uid, delta: int, reason: str, ref: Optional[str] = None) -> int:
    """Add (or remove) tokens atomically. A removal that would go below zero raises ValueError. Returns the new balance."""
    delta = int(delta)
    flt = {"id": oid(str(uid))}
    if delta < 0:
        flt["tokens__gte"] = -delta
    u = User.objects(**flt).modify(inc__tokens=delta, new=True)   # one atomic step: a balance can never go below zero
    if not u:
        raise ValueError("Not enough tokens.")
    _ledger(uid, delta, int(u.tokens), reason, ref)
    if delta < 0 and u.role != "owner" and int(u.tokens) < LOW_TOKENS <= int(u.tokens) - delta:
        from app.services import notification_service as notes
        notes.notify(str(uid), "tokens", "Your token balance is low", f"You have {int(u.tokens)} tokens left. Ask the owner to add more so your videos keep running.", "#/usage", "warn", key="lowtok")
    return int(u.tokens)


# ------------------------------------------------------------------ pricing the usage of one video
def price_event(e: Dict, p: Dict) -> float:
    """Tokens this one usage record costs at the owner's prices (a failed call costs nothing)."""
    if not e.get("ok", True):
        return 0.0
    k, prov = e.get("kind"), e.get("provider")
    if k == "llm":
        per = p["gemini_per_1k"] if prov == "gemini" else p["claude_per_1k"] if prov == "claude" else p["deepseek_per_1k"]
        return (int(e.get("tokens_in") or 0) + int(e.get("tokens_out") or 0)) / 1000.0 * per
    if k == "image":
        return float(e.get("units") or 1) * (p["image_gemini"] if prov == "gemini" else p["image_free"])
    if k == "tts":
        return float(e.get("units") or 0) / 1000.0 * p["tts_per_1k_chars"]
    if k == "whisper":
        return float(e.get("units") or 0) / 60.0 * p["whisper_per_min"]
    if k == "safety_local":
        return float(e.get("units") or 0) * p["safety_local_per_clip"]
    return 0.0


_LINES = {
    ("llm", "gemini"): ("AI text and safety review (Gemini)", "AI tokens"), ("llm", "deepseek"): ("AI text (DeepSeek)", "AI tokens"),
    ("llm", "claude"): ("Thumbnail art direction (Claude)", "AI tokens"),
    ("image", "gemini"): ("Images (Gemini)", "images"), ("image", "free"): ("Images (free service)", "images"),
    ("tts", ""): ("Narrator voice", "characters"), ("whisper", ""): ("Captions (speech to text)", "minutes"),
    ("safety_local", ""): ("Local safety check", "clips"),
}


def member_label(label: str) -> Tuple[str, str]:
    """(plain label, unit to show or '') for a receipt line, with no platform or model names. Members see what was done, never which service did it."""
    low = (label or "").lower()
    prefix = "New audio: " if low.startswith("new audio: ") else ""
    if prefix:
        low = low[len(prefix):]
    if "thumbnail art direction" in low:
        return prefix + "Thumbnail design", ""
    if "ai text" in low or "safety review" in low:
        return prefix + "Writing and review", ""
    if low.startswith("images"):
        return prefix + "Pictures", "pictures"
    if "narrator" in low:
        return prefix + "Narrator voice", ""
    if "captions" in low:
        return prefix + "Captions", "minutes"
    if "safety check" in low:
        return prefix + "Safety check", ""
    if "upload" in low:
        return prefix + "Upload to YouTube", "upload"
    return prefix + "Other", ""


def member_receipt(receipt: Optional[List[Dict]]) -> List[Dict]:
    """The itemised receipt as a member sees it: plain labels, lines of the same kind added together, no platform names, no AI token counts,
    and nothing that cost nothing."""
    merged: Dict[str, Dict] = {}
    for r in receipt or []:
        label, unit = member_label(r.get("label", ""))
        m = merged.setdefault(label, {"label": label, "unit": unit, "qty": 0.0, "tokens": 0.0})
        m["tokens"] += float(r.get("tokens") or 0)
        if unit:
            m["qty"] += float(r.get("qty") or 0)
    return [{"label": m["label"], "unit": m["unit"], "qty": round(m["qty"], 1) if m["unit"] else None, "tokens": round(m["tokens"], 2)} for m in merged.values() if round(m["tokens"], 2) > 0]


def price_events(events: List[Dict], p: Optional[Dict] = None) -> Tuple[float, List[Dict], Dict]:
    """(total tokens, itemised receipt, {event id: cost}) for the usage records of one video."""
    p = p or pricing()
    lines: Dict[tuple, Dict] = {}
    per_event: Dict = {}
    total = 0.0
    for e in events:
        c = price_event(e, p)
        per_event[e["_id"]] = c
        if not e.get("ok", True):
            continue
        k, prov = e.get("kind"), e.get("provider")
        key = (k, prov if k in ("llm", "image") else "")
        if key not in _LINES:
            continue
        label, unit = _LINES[key]
        qty = (int(e.get("tokens_in") or 0) + int(e.get("tokens_out") or 0)) if k == "llm" else float(e.get("units") or 0) / (60 if k == "whisper" else 1)
        ln = lines.setdefault(key, {"label": label, "unit": unit, "qty": 0.0, "tokens": 0.0})
        ln["qty"] += qty
        ln["tokens"] += c
        total += c
    receipt = [{"label": v["label"], "unit": v["unit"], "qty": round(v["qty"], 1), "tokens": round(v["tokens"], 2)} for v in lines.values()]
    return total, receipt, per_event


def _store_costs(job_id: str, video_id, total: float, receipt: List[Dict], per_event: Dict, charged: int, billed: bool, remake: bool = False) -> None:
    amount = _up(total)
    for eid, c in per_event.items():
        UsageEvent.objects(id=eid).update(set__cost=float(c), set__billed=billed)
    Job.update_fields(job_id, cost_tokens=amount, charged_tokens=charged, receipt=receipt)
    if video_id:
        if remake:    # making the video again with new audio: add to its bill, keep the first receipt
            v = Video.find_one(id=oid(str(video_id))) or {}
            fields = {"cost_tokens": int(v.get("cost_tokens") or 0) + amount, "charged_tokens": int(v.get("charged_tokens") or 0) + charged,
                      "receipt": list(v.get("receipt") or []) + [dict(r, label="New audio: " + r["label"]) for r in receipt]}
        else:
            fields = {"cost_tokens": amount, "charged_tokens": charged, "receipt": receipt}
        Video.update_where(id=oid(str(video_id)), fields=fields)


def adhoc_shortfall(uid: str, events: List[Dict]) -> Optional[str]:
    """A message if a member cannot afford a small paid action (a new AI picture, AI headline ideas); None if they can (or are the owner)."""
    user = User.find_one(id=oid(uid))
    if not user or user.get("role") == "owner":
        return None
    p = pricing()
    need = max(1, _up(sum(price_event({**e, "ok": True}, p) for e in events)))
    have = int(user.get("tokens") or 0)
    return None if have >= need else f"Not enough tokens: this costs {need} and you have {have}. Ask the owner for more."


def charge_adhoc(uid: str, video_id: str, events: List[Dict], reason: str) -> int:
    """Charge a small paid action that happens outside a video run. Members pay (at least 1 token); the owner is never charged but it is recorded."""
    p = pricing()
    user = User.find_one(id=oid(uid))
    member = bool(user and user.get("role") != "owner")
    costs = [price_event({**e, "ok": True}, p) for e in events]
    amount = max(1, _up(sum(costs))) if member and sum(costs) > 0 else 0
    if amount:
        adjust(uid, -amount, reason, video_id)
    for e, c in zip(events, costs):
        UsageEvent(user_id=uid, video_id=video_id, ok=True, cost=float(c), billed=member, t=now(), **e).save()
    return amount


def charge_job(user: Dict, mode: str, source: str, job_id: str) -> Tuple[int, Optional[str]]:
    """Reserve the tokens for a queued video. Returns (tokens reserved, error). The owner reserves nothing."""
    if user.get("role") == "owner":
        return 0, None
    c = cost(mode, source)
    if c <= 0:
        return 0, None
    try:
        adjust(user["_id"], -c, f"{'Compilation' if 'compilation' in mode else 'Short'} video: reserved (you pay only what is used)", job_id)
    except ValueError:
        return 0, (f"Not enough tokens: starting this video reserves {c} tokens (you pay only what it really uses, the rest comes back) "
                   f"and you have {balance(user['_id'])}. Ask the owner for more.")
    return c, None


def settle_job(job_id: str) -> int:
    """A video was made: price its real usage, take exactly that from the member, give back the unused reserve. Returns tokens charged."""
    j = Job.objects(id=oid(job_id), settled__ne=True).modify(set__settled=True)   # only one caller settles a job
    if not j:
        return 0
    hold, uid = int(j.tokens or 0), j.user_id
    events = UsageEvent.find_all(job_id=job_id)
    total, receipt, per_event = price_events(events)
    amount = _up(total)
    user = User.find_one(id=oid(str(uid))) if uid else None
    member = bool(user and user.get("role") != "owner")
    charged = 0
    if member:
        if amount <= hold:
            if hold - amount > 0:
                adjust(uid, hold - amount, "Refund: the unused part of the reserve", job_id)
            charged = amount
        else:
            take = min(amount - hold, balance(uid))
            if take > 0:
                adjust(uid, -take, "Extra usage beyond the reserve", job_id)
            charged = hold + take
    _store_costs(job_id, getattr(j, "video_id", None), total, receipt, per_event, charged, billed=member, remake=(getattr(j, "mode", "") == "remix"))
    return charged


def refund_job(job_id: str) -> int:
    """A video failed or was cancelled: the whole reserve goes back (nothing is charged). The usage is still recorded for the owner."""
    j = Job.objects(id=oid(job_id), tokens__gt=0, refunded__ne=True, settled__ne=True).modify(set__refunded=True)   # only one caller wins
    back = 0
    if j:
        adjust(j.user_id, int(j.tokens), "Refund: video was not made", job_id)
        back = int(j.tokens)
    j2 = Job.objects(id=oid(job_id), settled__ne=True).modify(set__settled=True)
    if j2:   # records only: what the failed run used
        total, receipt, per_event = price_events(UsageEvent.find_all(job_id=job_id))
        _store_costs(job_id, None, total, receipt, per_event, 0, billed=False)
    return back


# ------------------------------------------------------------------ uploads
def upload_fee(kind: Optional[str]) -> int:
    p = pricing()
    return _up(p["upload_compilation"] if kind == "compilation" else p["upload_short"])


def charge_upload(video: Dict) -> Tuple[int, Optional[str]]:
    """Take the upload fee before a video goes to YouTube. Returns (tokens charged, error). The owner is never charged."""
    uid = video.get("user_id")
    user = User.find_one(id=oid(str(uid))) if uid else None
    fee = upload_fee(video.get("kind"))
    if not user or user.get("role") == "owner" or fee <= 0:
        return 0, None
    if int(video.get("upload_fee") or 0) > 0:    # already paid for this upload (a retry)
        return int(video["upload_fee"]), None
    try:
        adjust(uid, -fee, f"Upload to YouTube ({video.get('kind') or 'video'})", str(video["_id"]))
    except ValueError:
        return 0, (f"Not enough tokens to upload: it costs {fee} and you have {balance(uid)}. "
                   f"Ask the owner for more; the upload then continues by itself.")
    Video.update_where(id=video["_id"], fields={"upload_fee": fee})
    return fee, None


def refund_upload(video_id) -> int:
    """The upload did not finish: give the fee back (once)."""
    v = Video.objects(id=oid(str(video_id)), upload_fee__gt=0).modify(set__upload_fee=0)
    if not v:
        return 0
    adjust(v.user_id, int(v.upload_fee), "Refund: the upload did not finish", str(video_id))
    return int(v.upload_fee)


def record_upload(video: Dict, charged: int) -> None:
    """An upload succeeded: keep it in the usage records (for the owner this is the 'would have cost' record)."""
    fee = upload_fee(video.get("kind"))
    try:
        UsageEvent(user_id=video.get("user_id"), video_id=str(video["_id"]), kind="upload", provider="youtube", units=1, ok=True,
                   cost=float(fee), billed=bool(charged), t=now()).save(force_insert=True)
        rec = {"label": "Upload to YouTube", "unit": "upload", "qty": 1, "tokens": float(fee)}
        Video.update_where(id=video["_id"], fields={"upload_cost_tokens": fee, "upload_charged": int(charged), "upload_receipt": rec})
    except Exception:
        pass


# ------------------------------------------------------------------ daily upload limit
def daily_limit(user: Optional[Dict]) -> Optional[int]:
    """Uploads per day this member may make; None = no limit (the owner)."""
    if not user or user.get("role") == "owner":
        return None
    lim = user.get("upload_limit")
    return int(lim) if lim is not None else int(pricing()["daily_uploads"])


def day_start() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def uploads_today(uid) -> int:
    u = str(uid)
    return Video.total(user_id=u, uploaded_at__gte=day_start()) + Video.total(user_id=u, upload_status="uploading")


def set_upload_limit(uid: str, limit) -> Optional[int]:
    """Per-member limit; empty / None = use the default."""
    if limit in (None, ""):
        User.objects(id=oid(uid)).update(unset__upload_limit=1)
        return None
    n = int(limit)
    if not 0 <= n <= 1000:
        raise ValueError("Uploads per day must be between 0 and 1000.")
    if not User.objects(id=oid(uid)).update(set__upload_limit=n):
        raise ValueError("user not found")
    return n


def ledger(uid, limit: int = 30) -> List[Dict]:
    return [{"delta": d.delta, "balance": d.balance, "reason": d.reason, "t": d.t.isoformat()}
            for d in TokenLedger.objects(user_id=str(uid)).order_by("-t").limit(limit)]
