"""Owner reports: what was used, what it cost you in real dollars, what members were billed, and what is left over.

Everything is calculated from the usage records the pipeline writes (see token_service): AI calls, images, voice, captions,
safety checks and uploads. Days are UTC days. Real dollars use the rates the owner typed in (token_service.real_costs).
"""
import csv
import io
from datetime import timedelta
from typing import Dict, List

from app.models import Job, TokenLedger, UsageEvent, User, Video, now, oid
from app.services import token_service as tk

SERVICES = {
    ("llm", "gemini"): ("Gemini (AI text and safety review)", "AI tokens"), ("llm", "deepseek"): ("DeepSeek (AI text)", "AI tokens"),
    ("llm", "claude"): ("Claude (thumbnails and research)", "AI tokens"), ("web_search", "claude"): ("Claude web searches (research)", "searches"),
    ("image", "gemini"): ("Images (Gemini)", "images"), ("image", "free"): ("Images (free service)", "images"),
    ("tts", "edge-tts"): ("Narrator voice", "characters"), ("whisper", "whisper"): ("Captions (speech to text)", "minutes"),
    ("safety_local", "nudenet"): ("Local safety check", "clips"), ("upload", "youtube"): ("Uploads to YouTube", "uploads"),
}


def _units(kind: str, tin: int, tout: int, units: float, n: int) -> float:
    if kind == "llm":
        return tin + tout
    if kind == "whisper":
        return units / 60.0
    if kind == "upload":
        return n
    return units


def _usd(kind, prov, tin, tout, units, r) -> float:
    return tk.usd_of(kind, prov, tin, tout, units, r)


def _name(users: Dict, uid: str) -> Dict:
    u = users.get(uid) or {}
    return {"name": u.get("name") or ("(deleted)" if uid else "(system)"), "email": u.get("email", ""), "role": u.get("role", "")}


def job_rows(since, limit: int, users: Dict, rates: Dict, tusd: float) -> List[Dict]:
    """One row per finished or failed video: who, what it used, what it cost, what was billed."""
    jobs = Job.find_all(status__in=["done", "failed"], finished_at__gte=since, order=("-finished_at",), limit=limit)
    by_job: Dict[str, Dict] = {}
    ids = [str(j["_id"]) for j in jobs]
    for r in UsageEvent.objects(job_id__in=ids, ok=True).aggregate([{"$group": {"_id": {"j": "$job_id", "k": "$kind", "p": "$provider"},
                         "tin": {"$sum": "$tokens_in"}, "tout": {"$sum": "$tokens_out"}, "units": {"$sum": "$units"}}}]):
        g, a = r["_id"], by_job.setdefault(r["_id"]["j"], {"usd": 0.0, "gemini": 0, "deepseek": 0, "claude": 0, "images": 0})
        a["usd"] += _usd(g["k"], g.get("p"), r["tin"], r["tout"], r["units"], rates)
        if g["k"] == "llm":
            a["gemini" if g.get("p") == "gemini" else "claude" if g.get("p") == "claude" else "deepseek"] += r["tin"] + r["tout"]
        elif g["k"] == "image":
            a["images"] += int(r["units"])
    out = []
    for j in jobs:
        measured = str(j["_id"]) in by_job     # videos made before usage tracking existed have no records
        a = by_job.get(str(j["_id"]), {"usd": 0.0, "gemini": 0, "deepseek": 0, "claude": 0, "images": 0})
        charged = int(j.get("charged_tokens") or 0)
        out.append({"when": j["finished_at"].isoformat() if j.get("finished_at") else None, "video_id": j.get("video_id"), "kind": "Compilation" if "compilation" in j["mode"] else "Short",
                    "status": j["status"], "measured": measured, "source": j.get("source") or "", **_name(users, j.get("user_id") or ""),
                    "cost_tokens": int(j.get("cost_tokens") or 0), "charged_tokens": charged, "revenue_usd": round(charged * tusd, 4), "real_usd": round(a["usd"], 4),
                    "gemini_tokens": a["gemini"], "deepseek_tokens": a["deepseek"], "claude_tokens": a["claude"], "images": a["images"]})
    return out


def build_report(days: int) -> Dict:
    days = min(365, max(1, int(days)))
    since = now() - timedelta(days=days)
    rates, prices = tk.real_costs(), tk.pricing()
    tusd = rates["token_usd"]

    # ---- usage records grouped by day, member, kind and provider
    per_day: Dict[str, Dict] = {}
    per_member: Dict[str, Dict] = {}
    per_service: Dict[tuple, Dict] = {}
    tot = {"cost_tokens": 0.0, "billed": 0.0, "real_usd": 0.0}
    grp = {"$group": {"_id": {"d": {"$dateToString": {"format": "%Y-%m-%d", "date": "$t"}}, "u": "$user_id", "k": "$kind", "p": "$provider"},
                      "cost": {"$sum": "$cost"}, "billed": {"$sum": {"$cond": ["$billed", "$cost", 0]}}, "units": {"$sum": "$units"},
                      "tin": {"$sum": "$tokens_in"}, "tout": {"$sum": "$tokens_out"}, "n": {"$sum": 1}}}
    for r in UsageEvent.objects(t__gte=since, ok=True).aggregate([grp]):
        g = r["_id"]
        usd = _usd(g["k"], g.get("p"), r["tin"], r["tout"], r["units"], rates)
        uid = g.get("u") or ""
        for bucket, key in ((per_day, g["d"]), (per_member, uid)):
            b = bucket.setdefault(key, {"cost_tokens": 0.0, "billed": 0.0, "real_usd": 0.0, "uploads": 0, "gemini_tokens": 0, "deepseek_tokens": 0, "claude_tokens": 0, "images": 0})
            b["cost_tokens"] += r["cost"]
            b["billed"] += r["billed"]
            b["real_usd"] += usd
            if g["k"] == "upload":
                b["uploads"] += r["n"]
            elif g["k"] == "llm":
                b["gemini_tokens" if g.get("p") == "gemini" else "claude_tokens" if g.get("p") == "claude" else "deepseek_tokens"] += r["tin"] + r["tout"]
            elif g["k"] == "image":
                b["images"] += int(r["units"] or r["n"])
        s = per_service.setdefault((g["k"], g.get("p") or ""), {"units": 0.0, "real_usd": 0.0, "cost_tokens": 0.0, "billed": 0.0})
        s["units"] += _units(g["k"], r["tin"], r["tout"], r["units"], r["n"])
        s["real_usd"] += usd
        s["cost_tokens"] += r["cost"]
        s["billed"] += r["billed"]
        tot["cost_tokens"] += r["cost"]
        tot["billed"] += r["billed"]
        tot["real_usd"] += usd

    # ---- videos made / failed (per day and per member)
    done_by_day = {r["_id"]: r["n"] for r in Job.objects(status="done", finished_at__gte=since).aggregate(
        [{"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$finished_at"}}, "n": {"$sum": 1}}}])}
    made = Job.count_by("user_id", status="done", finished_at__gte=since)
    failed = Job.count_by("user_id", status="failed", finished_at__gte=since)

    # ---- money spent on videos that failed (nobody is billed for these)
    failed_ids = [str(j["_id"]) for j in Job.find_all(status="failed", finished_at__gte=since, only=("_id",), limit=2000)]
    wasted = 0.0
    if failed_ids:
        for r in UsageEvent.objects(job_id__in=failed_ids, ok=True, kind__in=["llm", "image"]).aggregate([{"$group": {"_id": {"k": "$kind", "p": "$provider"},
                             "tin": {"$sum": "$tokens_in"}, "tout": {"$sum": "$tokens_out"}, "units": {"$sum": "$units"}}}]):
            wasted += _usd(r["_id"]["k"], r["_id"].get("p"), r["tin"], r["tout"], r["units"], rates)
    refunded = sum(d.delta for d in TokenLedger.objects(t__gte=since, reason__startswith="Refund", delta__gt=0).only("delta"))

    uids = [x for x in per_member if x]
    users = {str(u["_id"]): u for u in User.find_all(id__in=[oid(x) for x in uids])}

    # ---- averages: what one finished Short / compilation really used
    rows = job_rows(since, 500, users, rates, tusd)
    average = {}
    for label in ("Short", "Compilation"):
        sel = [r for r in rows if r["kind"] == label and r["status"] == "done" and r["measured"]]
        if sel:
            n = len(sel)
            average[label.lower()] = {"label": label, "videos": n, "gemini_tokens": round(sum(r["gemini_tokens"] for r in sel) / n), "deepseek_tokens": round(sum(r["deepseek_tokens"] for r in sel) / n),
                                      "images": round(sum(r["images"] for r in sel) / n, 1), "cost_tokens": round(sum(r["cost_tokens"] for r in sel) / n, 1),
                                      "real_usd": round(sum(r["real_usd"] for r in sel) / n, 4)}

    members = []
    for uid, b in per_member.items():
        rev = b["billed"] * tusd
        members.append({"id": uid, **_name(users, uid), "videos": made.get(uid, 0), "failed": failed.get(uid, 0), "uploads": b["uploads"], "gemini_tokens": b["gemini_tokens"],
                        "deepseek_tokens": b["deepseek_tokens"], "images": b["images"], "cost_tokens": round(b["cost_tokens"], 1), "billed_tokens": round(b["billed"], 1),
                        "revenue_usd": round(rev, 4), "real_usd": round(b["real_usd"], 4), "net_usd": round(rev - b["real_usd"], 4)})
    members.sort(key=lambda m: -m["real_usd"])

    services = []
    for (k, p), s in per_service.items():
        label, unit = SERVICES.get((k, p), (f"{k} {p}".strip(), "units"))
        services.append({"label": label, "unit": unit, "units": round(s["units"], 1), "real_usd": round(s["real_usd"], 4), "cost_tokens": round(s["cost_tokens"], 1),
                         "billed_tokens": round(s["billed"], 1), "revenue_usd": round(s["billed"] * tusd, 4)})
    services.sort(key=lambda s: -s["real_usd"])

    start = (now() - timedelta(days=days - 1)).date()
    daily = []
    for i in range(min(days, 90)):
        d = (start + timedelta(days=i + max(0, days - 90))).isoformat()
        b = per_day.get(d, {"billed": 0.0, "real_usd": 0.0})
        daily.append({"d": d, "videos": done_by_day.get(d, 0), "billed_tokens": round(b["billed"], 1), "revenue_usd": round(b["billed"] * tusd, 4), "real_usd": round(b["real_usd"], 4)})

    revenue = tot["billed"] * tusd
    return {"days": days, "token_usd": tusd, "rates": rates, "prices": prices,
            "totals": {"videos": sum(made.values()), "failed": sum(failed.values()), "uploads": sum(b["uploads"] for b in per_member.values()), "cost_tokens": round(tot["cost_tokens"], 1),
                       "billed_tokens": round(tot["billed"], 1), "revenue_usd": round(revenue, 4), "real_usd": round(tot["real_usd"], 4), "net_usd": round(revenue - tot["real_usd"], 4),
                       "wasted_usd": round(wasted, 4), "refunded_tokens": int(refunded)},
            "daily": daily, "services": services, "members": members, "recent": rows[:40], "average": average}


def build_csv(days: int) -> str:
    """One row per finished or failed video, for a spreadsheet."""
    since = now() - timedelta(days=min(365, max(1, int(days))))
    rates = tk.real_costs()
    users = {str(u["_id"]): u for u in User.find_all()}
    rows = job_rows(since, 5000, users, rates, rates["token_usd"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["finished (UTC)", "member", "email", "type", "status", "cost at token prices", "billed tokens", "revenue USD", "real cost USD", "gemini tokens", "deepseek tokens", "images"])
    for r in rows:
        w.writerow([r["when"], r["name"], r["email"], r["kind"], r["status"], r["cost_tokens"], r["charged_tokens"], r["revenue_usd"], r["real_usd"], r["gemini_tokens"], r["deepseek_tokens"], r["images"]])
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------- one member's own report
def build_member_report(uid: str, days: int) -> Dict:
    """What THIS member used and was billed. No real dollar costs, no prices of the owner, nothing about other members."""
    days = min(365, max(1, int(days)))
    since = now() - timedelta(days=days)
    user = User.find_one(id=oid(uid)) or {}
    is_owner = user.get("role") == "owner"
    per_day: Dict[str, float] = {}
    per_service: Dict[tuple, Dict] = {}
    billed_total = cost_total = 0.0
    uploads = 0
    grp = {"$group": {"_id": {"d": {"$dateToString": {"format": "%Y-%m-%d", "date": "$t"}}, "k": "$kind", "p": "$provider"},
                      "cost": {"$sum": "$cost"}, "billed": {"$sum": {"$cond": ["$billed", "$cost", 0]}}, "units": {"$sum": "$units"},
                      "tin": {"$sum": "$tokens_in"}, "tout": {"$sum": "$tokens_out"}, "n": {"$sum": 1}}}
    for r in UsageEvent.objects(t__gte=since, ok=True, user_id=uid).aggregate([grp]):
        g = r["_id"]
        per_day[g["d"]] = per_day.get(g["d"], 0.0) + r["billed"]
        s = per_service.setdefault((g["k"], g.get("p") or ""), {"units": 0.0, "cost": 0.0, "billed": 0.0})
        s["units"] += _units(g["k"], r["tin"], r["tout"], r["units"], r["n"])
        s["cost"] += r["cost"]
        s["billed"] += r["billed"]
        billed_total += r["billed"]
        cost_total += r["cost"]
        if g["k"] == "upload":
            uploads += r["n"]
    done_by_day = {r["_id"]: r["n"] for r in Job.objects(status="done", user_id=uid, finished_at__gte=since).aggregate(
        [{"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$finished_at"}}, "n": {"$sum": 1}}}])}
    start = (now() - timedelta(days=days - 1)).date()
    daily = []
    for i in range(min(days, 90)):
        d = (start + timedelta(days=i + max(0, days - 90))).isoformat()
        daily.append({"d": d, "videos": done_by_day.get(d, 0), "tokens": round(per_day.get(d, 0.0), 1)})
    merged: Dict[str, Dict] = {}
    for (k, p), s in per_service.items():
        if s["cost"] <= 0 and s["billed"] <= 0 and k not in ("upload",) and s["units"] <= 0:
            continue
        # plain words for members: what was done, never which service or model did it, and no AI token counts
        label, unit = tk.member_label(SERVICES.get((k, p), (f"{k} {p}".strip(), "units"))[0])
        m = merged.setdefault(label, {"label": label, "unit": unit, "units": 0.0, "tokens": 0.0})
        m["tokens"] += s["billed"]
        if unit:
            m["units"] += s["units"]
    services = [{"label": m["label"], "unit": m["unit"], "units": round(m["units"], 1) if m["unit"] else None, "tokens": round(m["tokens"], 1)} for m in merged.values()]
    services.sort(key=lambda x: -x["tokens"])
    jobs = Job.find_all(user_id=uid, status__in=["done", "failed"], finished_at__gte=since, order=("-finished_at",), limit=40)
    vids = {str(v["_id"]): v for v in Video.find_all(id__in=[oid(str(j["video_id"])) for j in jobs if j.get("video_id")], only=("title", "upload_charged", "upload_cost_tokens"))}
    recent = []
    for j in jobs:
        v = vids.get(str(j.get("video_id") or ""), {})
        recent.append({"when": j["finished_at"].isoformat() if j.get("finished_at") else None, "video_id": j.get("video_id"), "title": v.get("title") or "",
                       "kind": "Compilation" if "compilation" in j["mode"] else "Short", "status": j["status"],
                       "tokens": int(j.get("charged_tokens") or 0), "upload_tokens": int(v.get("upload_charged") or 0),
                       "would_cost": int(j.get("cost_tokens") or 0)})
    refunded = sum(d.delta for d in TokenLedger.objects(user_id=uid, t__gte=since, reason__startswith="Refund", delta__gt=0).only("delta"))
    lim = tk.daily_limit(user)
    return {"days": days, "owner": is_owner, "balance": int(user.get("tokens") or 0),
            "totals": {"videos": sum(done_by_day.values()), "failed": Job.total(user_id=uid, status="failed", finished_at__gte=since), "uploads": uploads,
                       "tokens_spent": round(billed_total, 1), "would_cost": round(cost_total, 1), "refunded_tokens": int(refunded),
                       "uploads_today": tk.uploads_today(uid), "daily_uploads": lim},
            "daily": daily, "services": services, "recent": recent, "ledger": tk.ledger(uid, 60)}


def build_member_csv(uid: str, days: int) -> str:
    """The member's own videos, for a spreadsheet."""
    rep = build_member_report(uid, days)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["finished (UTC)", "title", "type", "status", "tokens charged for the video", "tokens charged for the upload"])
    for r in rep["recent"]:
        w.writerow([r["when"], r["title"], r["kind"], r["status"], r["tokens"], r["upload_tokens"]])
    return buf.getvalue()


KIND_LABEL = {"lowres": "Pictures read at low resolution", "cache": "Answers reused (the same question was never paid for twice)", "budget": "Stopped by a video's token budget", "local": "Done by code instead of AI"}


def ai_savings(days: int = 7) -> Dict:
    """How many AI tokens the studio spent, and how many it did NOT spend (and why), over the last `days` days."""
    from app.models import AiSaving
    since = now() - timedelta(days=max(1, min(365, int(days))))
    spent_by_task: Dict[str, int] = {}
    for r in UsageEvent.objects(kind="llm", ok=True, t__gte=since).aggregate([{"$group": {"_id": "$task", "n": {"$sum": {"$add": ["$tokens_in", "$tokens_out"]}}}}]):
        spent_by_task[r["_id"] or "?"] = int(r["n"])
    by_kind: Dict[str, int] = {}
    by_task: Dict[str, Dict[str, int]] = {}
    for r in AiSaving.objects(t__gte=since).aggregate([{"$group": {"_id": {"k": "$kind", "t": "$task"}, "n": {"$sum": "$tokens"}}}]):
        k, t = r["_id"]["k"], r["_id"]["t"] or "?"
        by_kind[k] = by_kind.get(k, 0) + int(r["n"])
        by_task.setdefault(t, {})[k] = int(r["n"])
    spent, saved = sum(spent_by_task.values()), sum(by_kind.values())
    tasks = sorted(set(spent_by_task) | set(by_task), key=lambda t: -(spent_by_task.get(t, 0) + sum(by_task.get(t, {}).values())))
    return {"days": days, "spent": spent, "saved": saved, "percent": round(100 * saved / (spent + saved), 1) if spent + saved else 0.0,
            "by_kind": [{"kind": k, "label": KIND_LABEL.get(k, k), "tokens": n} for k, n in sorted(by_kind.items(), key=lambda x: -x[1])],
            "by_task": [{"task": t, "spent": spent_by_task.get(t, 0), "saved": sum(by_task.get(t, {}).values())} for t in tasks]}

