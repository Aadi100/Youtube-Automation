"""Controller (the C of MVC): the permission tracker. Every member works only on their own list."""
from flask import Blueprint

from app.http import register
from app.services import permission_service as perms


def _safe(fn):
    def wrap(h, *a):
        try:
            return fn(h, *a)
        except LookupError:
            h.send_json(404, {"error": "That record is not there any more."})
        except ValueError as e:
            h.send_json(400, {"error": str(e)})
    wrap.__name__ = fn.__name__
    return wrap


def h_list(h):
    h.send_json(200, {"permissions": perms.list_for(h.uid, h.q.get("status") or ""), "max": perms.MAX_PER_MEMBER})


@_safe
def h_add(h):
    h.send_json(200, perms.add(h.uid, h.body_json()))


@_safe
def h_update(h, pid):
    h.send_json(200, perms.update(h.uid, pid, h.body_json()))


def h_delete(h, pid):
    ok = perms.delete(h.uid, pid)
    h.send_json(200 if ok else 404, {"ok": ok})


ROUTES = [
    (r"/api/permissions", "GET", h_list),
    (r"/api/permissions", "POST", h_add),
    (r"/api/permissions/([0-9a-f]{24})", "PUT", h_update),
    (r"/api/permissions/([0-9a-f]{24})", "DELETE", h_delete),
]
bp = Blueprint("permissions", __name__)
register(bp, ROUTES)
