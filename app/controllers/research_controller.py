"""Controller (the C of MVC): clipping research (Claude + web search)."""
import re

from flask import Blueprint

from app.engine import claude_util
from app.http import register
from app.services import creator_service, diy_service
from app.services import research_service as rs


def _allowed(h) -> bool:
    if h.is_owner() or diy_service.flags()["research"]:
        return True
    h.send_json(403, {"error": "The owner has not switched on the clipping research for members."})
    return False


def _safe(fn):
    def wrap(h, *a):
        try:
            return fn(h, *a)
        except ValueError as e:
            h.send_json(400, {"error": str(e)})
    wrap.__name__ = fn.__name__
    return wrap


def h_options(h):
    if not _allowed(h):
        return
    owner = h.is_owner()
    provs = rs.provider_info() if owner else []
    dflt = rs.default_provider()
    ready = next((p["ready"] for p in rs.provider_info() if p["id"] == dflt), False) if not owner else any(p["ready"] for p in provs)
    h.send_json(200, {"ready": ready, "providers": provs, "provider": dflt, "model": claude_util.research_model(), "scopes": [{"id": k, "name": v[0], "desc": v[1]} for k, v in rs.SCOPES.items()],
                      "platforms": list(rs.PLATFORMS), "depth": [{"id": k, "searches": n, "estimate": rs.estimate(n)} for k, n in rs.DEPTH.items()], "statuses": list(rs.STATUSES)})


@_safe
def h_run(h):
    if not _allowed(h):
        return
    d = h.body_json()
    h.send_json(202, {"run": rs.start(h.uid, str(d.get("scope") or ""), str(d.get("query") or ""), d.get("platforms") if isinstance(d.get("platforms"), list) else [],
                                      str(d.get("language") or ""), str(d.get("depth") or "normal"), str(d.get("model") or "") if h.is_owner() else "", str(d.get("provider") or "") if h.is_owner() else "")})


def h_run_export(h, rid):
    if not _allowed(h):
        return
    d = rs.export_run(h.uid, rid)
    if not d:
        return h.send_json(404, {"error": "not found"})
    h.send_json(200, d)


def h_runs(h):
    if _allowed(h):
        h.send_json(200, {"runs": rs.list_runs(h.uid), "stats": rs.stats(h.uid)})


def h_run_get(h, rid):
    if not _allowed(h):
        return
    d = rs.get_run(h.uid, rid)
    if not d:
        return h.send_json(404, {"error": "not found"})
    h.send_json(200, {"run": rs.run_view(d), "leads": rs.list_leads(h.uid, run_id=rid)})


def h_insights(h):
    if _allowed(h):
        h.send_json(200, rs.insights(h.uid, h.q.get("run", "") if re.fullmatch(r"[0-9a-f]{24}", h.q.get("run", "")) else ""))


def h_leads(h):
    if _allowed(h):
        run = h.q.get("run", "")
        h.send_json(200, {"leads": rs.list_leads(h.uid, h.q.get("status", ""), h.q.get("allows", ""), h.q.get("q", ""), run if re.fullmatch(r"[0-9a-f]{24}", run) else "")})


@_safe
def h_lead_patch(h, lid):
    if not _allowed(h):
        return
    d = h.body_json()
    lead = rs.update_lead(h.uid, lid, d.get("status") if "status" in d else None, d.get("notes") if "notes" in d else None)
    h.send_json(200 if lead else 404, {"lead": lead} if lead else {"error": "not found"})


def h_lead_delete(h, lid):
    if _allowed(h):
        ok = rs.delete_lead(h.uid, lid)
        h.send_json(200 if ok else 404, {"ok": ok})


@_safe
def h_lead_creator(h, lid):
    """Put the creator behind a lead into the member's saved creators (they can then take clips only from them on the Create page)."""
    if not _allowed(h):
        return
    lead = next((x for x in rs.list_leads(h.uid) if x["id"] == lid), None)
    if not lead:
        return h.send_json(404, {"error": "not found"})
    c = rs.creator_of(lead)
    if not c:
        raise ValueError("This lead is not a Twitch or YouTube creator page, so it cannot be added to the creator list.")
    if lead["allows"] not in ("yes", "conditional"):
        raise ValueError("Only creators with a proven permission to clip can be added.")
    if not creator_service.allowed(h.is_owner()):
        raise ValueError("The owner has switched off: choosing a creator.")
    item = creator_service.add(h.uid, c["platform"], c["name"], lead["name"])
    h.send_json(200, {"creator": item})


ROUTES = [
    (r"/api/research/options", "GET", h_options),
    (r"/api/research/run", "POST", h_run),
    (r"/api/research/runs", "GET", h_runs),
    (r"/api/research/runs/([0-9a-f]{24})", "GET", h_run_get),
    (r"/api/research/runs/([0-9a-f]{24})/export", "GET", h_run_export),
    (r"/api/research/insights", "GET", h_insights),
    (r"/api/research/leads", "GET", h_leads),
    (r"/api/research/leads/([0-9a-f]{24})", "PATCH", h_lead_patch),
    (r"/api/research/leads/([0-9a-f]{24})", "DELETE", h_lead_delete),
    (r"/api/research/leads/([0-9a-f]{24})/creator", "POST", h_lead_creator),
]
bp = Blueprint("research", __name__)
register(bp, ROUTES)
