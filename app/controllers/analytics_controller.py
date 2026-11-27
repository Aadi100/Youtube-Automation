"""Controller (the C of MVC): the member's YouTube results (read from YouTube Analytics with their permission)."""
from flask import Blueprint

from app.http import register
from app.services import analytics_service as an


def h_results(h):
    h.send_json(200, an.results_for(h.uid))


def h_sync(h):
    h.send_json(200, an.manual_sync(h.uid))


ROUTES = [
    (r"/api/analytics", "GET", h_results),
    (r"/api/analytics/sync", "POST", h_sync),
]
bp = Blueprint("analytics", __name__)
register(bp, ROUTES)
