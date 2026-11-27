"""Controller (the C of MVC): story videos. Every member works only on their own stories; the owner sets the rules and prices."""
from flask import Blueprint

from app.engine import story_media, story_script, story_trends
from app.http import OWNER_ONLY, register
from app.services import story_service as svc


def _safe(fn):
    def wrap(h, *a):
        try:
            return fn(h, *a)
        except LookupError:
            h.send_json(404, {"error": "That story is not there any more."})
        except ValueError as e:
            h.send_json(400, {"error": str(e)})
        except RuntimeError as e:
            h.send_json(502, {"error": str(e)[:300]})
    wrap.__name__ = fn.__name__
    return wrap


def h_options(h):
    out = {"styles": [{"id": a, "name": b, "about": c} for a, b, c in story_script.ART_STYLES], "genres": [{"id": g[0], "name": g[1], "about": g[3]} for g in story_trends.GENRES],
           "providers": svc.providers(h.is_owner()), "limits": {k: v for k, v in svc.settings().items()}, "mine": svc.list_for(h.uid, 5)}
    h.send_json(200, out)


def h_trends(h):
    force = bool(h.q.get("force")) and h.is_owner()                 # only the owner may spend YouTube's allowance on a fresh look; everyone shares the last one
    h.send_json(200, svc.trends_view(force))


@_safe
def h_ideas(h):
    h.send_json(200, svc.make_ideas(str(h.body_json().get("genre") or "")))


@_safe
def h_script(h):
    d = h.body_json()
    h.send_json(200, svc.make_script(h.uid, str(d.get("genre") or ""), str(d.get("premise") or ""), str(d.get("own_text") or ""), int(d.get("seconds") or 40), str(d.get("style") or "cartoon3d")))


@_safe
def h_estimate(h):
    d = h.body_json()
    s = story_script.clean(d.get("script") or {})
    h.send_json(200, svc.estimate(s, str(d.get("provider") or "motion"), h.is_owner()))


@_safe
def h_start(h):
    d = h.body_json()
    h.send_json(202, svc.start(h.uid, d.get("script") or {}, str(d.get("provider") or "motion"), str(d.get("voice") or ""), str(d.get("finish") or "open"), bool(d.get("captions", True))))


def h_list(h):
    h.send_json(200, {"stories": svc.list_for(h.uid)})


def h_one(h, sid):
    r = svc.get(h.uid, sid)
    h.send_json(200 if r else 404, r or {"error": "not found"})


def h_cancel(h, sid):
    r = svc.cancel(h.uid, sid)
    h.send_json(200 if r else 404, r or {"error": "not found"})


def h_frame(h, sid, n):
    p = svc.frame_path(h.uid, sid, int(n))
    if not p:
        return h.send_json(404, {"error": "not found"})
    h.send_file(p, "image/png")


def h_settings(h):
    h.send_json(200, svc.settings())


@_safe
def h_settings_put(h):
    h.send_json(200, svc.set_settings(h.body_json()))


OWNER_ONLY.update({h_settings, h_settings_put})
ROUTES = [
    (r"/api/stories/options", "GET", h_options),
    (r"/api/stories/trends", "GET", h_trends),
    (r"/api/stories/ideas", "POST", h_ideas),
    (r"/api/stories/script", "POST", h_script),
    (r"/api/stories/estimate", "POST", h_estimate),
    (r"/api/stories/settings", "GET", h_settings),
    (r"/api/stories/settings", "PUT", h_settings_put),
    (r"/api/stories", "GET", h_list),
    (r"/api/stories", "POST", h_start),
    (r"/api/stories/([0-9a-f]{24})", "GET", h_one),
    (r"/api/stories/([0-9a-f]{24})/cancel", "POST", h_cancel),
    (r"/api/stories/([0-9a-f]{24})/frame/(\d{1,2})", "GET", h_frame),
]
bp = Blueprint("stories", __name__)
register(bp, ROUTES)
