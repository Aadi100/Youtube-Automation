"""Controller (the C of MVC): spike alerts. Every member sees and uses only their own alerts."""
from flask import Blueprint

from app.http import register
from app.services import spike_service as sp


def h_list(h):
    from app.engine import clipcfg
    h.send_json(200, {"alerts": sp.recent(h.uid), "mode": clipcfg.pref(h.uid, "spike_mode", "off")})


def h_make(h, aid):
    try:
        h.send_json(202, sp.make_now(h.uid, aid))
    except LookupError:
        h.send_json(404, {"error": "That alert is not there any more."})
    except ValueError as e:
        h.send_json(400, {"error": str(e)})


ROUTES = [
    (r"/api/spikes", "GET", h_list),
    (r"/api/spikes/([0-9a-f]{24})/make", "POST", h_make),
]
bp = Blueprint("spikes", __name__)
register(bp, ROUTES)
