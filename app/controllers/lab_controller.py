"""Controller (the C of MVC): the Learning Lab (beta). Owner only, separate from everything else: it never starts a video job, uploads or spends AI tokens."""
from flask import Blueprint

from app.http import OWNER_ONLY, register
from app.services import lab_service as lab


def _safe(fn):
    def wrap(h, *a):
        try:
            return fn(h, *a)
        except ValueError as e:
            h.send_json(400, {"error": str(e)})
    wrap.__name__ = fn.__name__
    return wrap


def h_overview(h):
    h.send_json(200, lab.overview(h.uid))


@_safe
def h_part(h, part):
    h.send_json(200, lab.detail(h.uid, part))


@_safe
def h_part_put(h, part):
    on = bool(h.body_json().get("on"))
    lab.set_on(h.uid, part, on)
    h.send_json(200, lab.detail(h.uid, part))


@_safe
def h_example_add(h):
    d = h.body_json()
    lab.add_example(h.uid, str(d.get("kind") or ""), str(d.get("text") or ""))
    h.send_json(200, lab.detail(h.uid, "titles" if d.get("kind") == "title" else "descriptions"))


@_safe
def h_example_delete(h, eid):
    if not lab.delete_example(h.uid, eid):
        return h.send_json(404, {"error": "That example is not there any more."})
    h.send_json(200, {"ok": True})


@_safe
def h_train(h):
    part = str(h.body_json().get("part") or "")
    res = lab.train(h.uid, part)
    h.send_json(200, {**res, "detail": lab.detail(h.uid, part)})


@_safe
def h_reset(h):
    part = str(h.body_json().get("part") or "")
    lab.reset(h.uid, part)
    h.send_json(200, lab.detail(h.uid, part))


def h_sync(h):
    h.send_json(200, lab.sync_views(h.uid))


PARTS = r"(titles|descriptions|clipping)"
ROUTES = [
    (r"/api/lab", "GET", h_overview),
    (r"/api/lab/" + PARTS, "GET", h_part),
    (r"/api/lab/" + PARTS, "PUT", h_part_put),
    (r"/api/lab/examples", "POST", h_example_add),
    (r"/api/lab/examples/([0-9a-f]{24})", "DELETE", h_example_delete),
    (r"/api/lab/train", "POST", h_train),
    (r"/api/lab/reset", "POST", h_reset),
    (r"/api/lab/sync", "POST", h_sync),
]
OWNER_ONLY.update({h_overview, h_part, h_part_put, h_example_add, h_example_delete, h_train, h_reset, h_sync})
bp = Blueprint("lab", __name__)
register(bp, ROUTES)
