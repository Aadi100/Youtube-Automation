"""Controller (the C of MVC): owner reports - usage, real cost, revenue and profit."""
from flask import Blueprint

from app.http import OWNER_ONLY, register
from app.services import price_service, report_service, token_service as tokens


def h_report(h):
    h.send_json(200, report_service.build_report(int(h.q.get("days") or 7)))


def h_story_report(h):
    h.send_json(200, report_service.story_report(int(h.q.get("days") or 30)))


def h_ai_savings(h):
    h.send_json(200, report_service.ai_savings(int(h.q.get("days") or 7)))


def h_report_csv(h):
    body = report_service.build_csv(int(h.q.get("days") or 30)).encode("utf-8-sig")
    h.send_response(200)
    h.send_header("Content-Type", "text/csv; charset=utf-8")
    h.send_header("Content-Disposition", 'attachment; filename="clip-studio-report.csv"')
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


def h_my_report(h):
    """Every signed-in member: their own usage and what they were billed (never real costs or other members)."""
    h.send_json(200, report_service.build_member_report(h.uid, int(h.q.get("days") or 7)))


def h_my_report_csv(h):
    body = report_service.build_member_csv(h.uid, int(h.q.get("days") or 30)).encode("utf-8-sig")
    h.send_response(200)
    h.send_header("Content-Type", "text/csv; charset=utf-8")
    h.send_header("Content-Disposition", 'attachment; filename="my-clip-studio-usage.csv"')
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


def h_costs_put(h):
    """The owner's real dollar costs per service and what one token is worth."""
    tokens.set_real_costs(h.body_json())
    h_report(h)


def h_price_overview(h):
    """Settings -> Pricing & costs: the model catalogue, what Settings uses, the usage mix, a typical video, and the saved prices and costs."""
    h.send_json(200, price_service.overview())


def h_price_suggest(h):
    d = h.body_json()
    try:
        costs = d.get("costs") if isinstance(d.get("costs"), dict) else tokens.real_costs()
        h.send_json(200, {"prices": price_service.suggest(costs, float(d.get("token_usd") or costs.get("token_usd") or 0), float(d.get("margin_pct") or 0), price_service.usage_mix())})
    except (ValueError, TypeError) as e:
        h.send_json(400, {"error": str(e)})


def h_price_save(h):
    try:
        h.send_json(200, price_service.save(h.body_json()))
    except ValueError as e:
        h.send_json(400, {"error": str(e)})


ROUTES = [
    (r"/api/admin/price/overview", "GET", h_price_overview),
    (r"/api/admin/price/suggest", "POST", h_price_suggest),
    (r"/api/admin/price/save", "PUT", h_price_save),
    (r"/api/admin/report", "GET", h_report),
    (r"/api/admin/story-report", "GET", h_story_report),
    (r"/api/admin/report.csv", "GET", h_report_csv),
    (r"/api/admin/ai-savings", "GET", h_ai_savings),
    (r"/api/admin/costs", "PUT", h_costs_put),
    (r"/api/me/report", "GET", h_my_report),
    (r"/api/me/report.csv", "GET", h_my_report_csv),
]
OWNER_ONLY.update({h_story_report, h_report, h_report_csv, h_costs_put, h_ai_savings, h_price_overview, h_price_suggest, h_price_save})
bp = Blueprint("report", __name__)
register(bp, ROUTES)
