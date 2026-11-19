"""Token system: members spend tokens to make videos; the owner (who pays for the AI and image services) hands tokens out.

Pricing (owner can change it on the Users page): a Short, a Compilation, and an extra for live-stream scanning.
The owner's own account is free. A job is charged when it is queued and refunded in full if it fails or is cancelled.
Every change is written to a ledger, so balances can always be explained.
"""
from typing import Dict, List, Optional, Tuple

from app.models import Job, System, TokenLedger, User, now, oid, raw

DEFAULT_PRICING = {"short": 10, "compilation": 40, "live_extra": 5, "signup_bonus": 0}


def pricing() -> Dict:
    doc = raw(System.objects(id="pricing").first()) or {}
    return {k: int(doc.get(k, v)) for k, v in DEFAULT_PRICING.items()}


def set_pricing(data: Dict) -> Dict:
    upd = {}
    for k in DEFAULT_PRICING:
        if k in data:
            v = int(data[k])
            if not 0 <= v <= 100000:
                raise ValueError(f"{k} must be between 0 and 100000")
            upd[k] = v
    if upd:
        System.objects(id="pricing").update_one(upsert=True, **{f"set__{k}": v for k, v in upd.items()})
    return pricing()


def cost(mode: str, source: str) -> int:
    p = pricing()
    base = p["compilation"] if "compilation" in mode else p["short"]
    return base + (p["live_extra"] if source in ("live", "all") else 0)


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
    return int(u.tokens)


def charge_job(user: Dict, mode: str, source: str, job_id: str) -> Tuple[int, Optional[str]]:
    """Charge for a job. Returns (tokens charged, error). The owner is never charged."""
    if user.get("role") == "owner":
        return 0, None
    c = cost(mode, source)
    if c <= 0:
        return 0, None
    try:
        adjust(user["_id"], -c, f"{'Compilation' if 'compilation' in mode else 'Short'} video", job_id)
    except ValueError:
        return 0, f"Not enough tokens: this video costs {c} and you have {balance(user['_id'])}. Ask the owner for more."
    return c, None


def refund_job(job_id: str) -> int:
    """Give the tokens of a failed / cancelled job back, exactly once."""
    j = Job.objects(id=oid(job_id), tokens__gt=0, refunded__ne=True).modify(set__refunded=True)   # only one caller wins
    if not j:
        return 0
    adjust(j.user_id, int(j.tokens), "Refund: video was not made", job_id)
    return int(j.tokens)


def ledger(uid, limit: int = 30) -> List[Dict]:
    return [{"delta": d.delta, "balance": d.balance, "reason": d.reason, "t": d.t.isoformat()}
            for d in TokenLedger.objects(user_id=str(uid)).order_by("-t").limit(limit)]
