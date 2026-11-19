"""Flask glue shared by every controller: the request context an endpoint receives, login / role checks,
rate limiting, security headers, error handling, and the helper that turns a controller's route table into Flask rules."""
import io
import json
import mimetypes
import re
import threading
import time
from pathlib import Path

from flask import Response, request
from flask import send_file as flask_send_file
from werkzeug.exceptions import HTTPException
from werkzeug.routing import BaseConverter

from app.models import User
from app.runtime import COOKIE, allowed_hosts
from app.services import auth_service as auth
from app.utils.envfile import studio_secret

RATE: dict = {}
RATE_LOCK = threading.Lock()


def rate_ok(key: str, limit: int, window: int = 60) -> bool:
    """At most `limit` requests per `window` seconds for this key (in memory, per web process)."""
    now = time.time()
    with RATE_LOCK:
        if len(RATE) > 20000:
            RATE.clear()
        start, n = RATE.get(key, (now, 0))
        if now - start >= window:
            start, n = now, 0
        RATE[key] = (start, n + 1)
        return n + 1 <= limit


SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                                "media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
]
PUBLIC = {("GET", "/"), ("GET", "/healthz"), ("GET", "/api/ui-version"), ("GET", "/api/auth/status"), ("POST", "/api/auth/login"),
          ("POST", "/api/auth/signup"), ("POST", "/api/auth/logout")}
PUBLIC_RE = [r"/approve/[\w-]{20,64}(/decline)?", r"/api/youtube/callback"]          # protected by their own one-time token
INTERNAL_RE = [r"/run", r"/file", r"/api/schedule/claim/(shorts|compilation)", r"/api/videos/[0-9a-f]{24}/uploaded"]   # n8n on this machine
OWNER_ONLY: set = set()                                      # endpoint functions only the owner may call (controllers add theirs)
VIEWS: dict = {}                                             # Flask endpoint name -> endpoint function


class ReConverter(BaseConverter):
    """URL part that must match a regular expression: <re("[0-9a-f]{24}"):g0>"""
    def __init__(self, url_map, rx):
        super().__init__(url_map)
        self.regex = rx


class Ctx:
    """What every endpoint function receives as `h`: a small view of the current Flask request and the response being built."""

    def __init__(self):
        self.user = None
        self.uid = None
        self._extra: list = []
        self.q = request.args.to_dict()
        self.headers = request.headers
        self.path = request.full_path
        self.client_address = (request.remote_addr or "",)
        self.rfile = request.stream
        self.wfile = io.BytesIO()
        self._status, self._hdrs, self._resp = 200, [], None

    # ---- who is calling
    def client_ip(self) -> str:
        return (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or self.client_address[0]

    def is_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1") and not (self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP"))

    def internal_ok(self) -> bool:
        sec = self.headers.get("X-Studio-Secret", "")
        return self.is_local() or (bool(sec) and sec == studio_secret())

    def session_token(self) -> str:
        return request.cookies.get(COOKIE, "")

    def is_owner(self) -> bool:
        return bool(self.user and self.user.get("role") == "owner")

    # ---- reading the request
    def body_json(self) -> dict:
        if (request.content_length or 0) > 1_000_000:
            raise ValueError("body too large")
        data = json.loads(request.get_data(cache=False) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    # ---- building the response
    def send_json(self, code: int, obj) -> None:
        self._resp = Response(json.dumps(obj, ensure_ascii=False).encode("utf-8"), status=code,
                              content_type="application/json; charset=utf-8", headers={"Cache-Control": "no-store"})

    def send_html(self, html: str, code: int = 200) -> None:
        self._resp = Response(html.encode("utf-8"), status=code, content_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})

    def send_response(self, code: int) -> None:      # low-level style used by the few audio / redirect endpoints
        self._status = code

    def send_header(self, k: str, v: str) -> None:
        self._hdrs.append((k, v))

    def end_headers(self) -> None:
        pass

    def send_file(self, p: Path, ctype: str = None, filename: str = None) -> None:
        """Files with Range support (video seeking) and optional download name."""
        self._resp = flask_send_file(p, mimetype=ctype or mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                                     as_attachment=bool(filename), download_name=filename, conditional=True, max_age=0)

    def finish(self) -> Response:
        r = self._resp
        if r is None:
            r = Response(self.wfile.getvalue(), status=self._status)
            for k, v in self._hdrs:
                if k.lower() not in ("content-length", "transfer-encoding"):
                    r.headers[k] = v
        for k, v in self._extra:
            r.headers.add(k, v)
        return r


def _json(code: int, obj) -> Response:
    return Response(json.dumps(obj, ensure_ascii=False).encode("utf-8"), status=code, content_type="application/json; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


def _guard():
    if request.host not in allowed_hosts():
        return _json(403, {"error": "bad host"})
    if request.method not in ("GET", "HEAD") and request.headers.get("X-Requested-With") != "studio":
        return _json(403, {"error": "missing X-Requested-With: studio header"})
    local = (request.remote_addr or "") in ("127.0.0.1", "::1") and not (request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP"))
    if not local:   # this machine itself (n8n, the tests) is never limited; everybody else is
        ip = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or (request.remote_addr or "")
        kind = "auth" if request.path.startswith("/api/auth/") else "media" if request.path.startswith("/media/") else "api"
        if not rate_ok(f"{kind}:{ip}", {"auth": 40, "media": 900, "api": 300}[kind]):
            return _json(429, {"error": "Too many requests. Please slow down for a minute."})


def _headers(resp):
    for k, v in SECURITY_HEADERS:
        resp.headers[k] = v
    if request.headers.get("X-Forwarded-Proto") == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


def _error(e):
    if isinstance(e, HTTPException):
        return _json(e.code or 500, {"error": "not found" if e.code == 404 else e.description})
    if isinstance(e, ValueError):
        return _json(400, {"error": str(e)})
    if isinstance(e, (BrokenPipeError, ConnectionResetError)):
        return Response(status=204)
    print(f"[studio] error in {request.method} {request.path}: {type(e).__name__}: {str(e)[:300]}")
    return _json(500, {"error": f"{type(e).__name__}: {str(e)[:300]}"})


def _view(**kw):
    """One entry point for every endpoint: login / role checks, then the endpoint function."""
    h = Ctx()
    fn = VIEWS[request.endpoint]
    path = request.path
    public = (request.method, path) in PUBLIC or any(re.fullmatch(p, path) for p in PUBLIC_RE)
    if not public:
        if any(re.fullmatch(p, path) for p in INTERNAL_RE) and h.internal_ok():
            h.uid = auth.owner_id()          # the n8n bridge works for the owner's workspace
            h.user = User.find_one(role="owner") or {}
        else:
            h.user = auth.user_for_token(h.session_token())
            if not h.user:
                return _json(401, {"error": "login required"})
            h.uid = str(h.user["_id"])
        if fn in OWNER_ONLY and not h.is_owner():
            return _json(403, {"error": "only the owner can do this"})
    fn(h, *[kw[f"g{i}"] for i in range(len(kw))])
    return h.finish()


def register(bp, routes) -> None:
    """Turn a controller's route table [(regex, method, function)] into rules of its Flask blueprint."""
    for i, (pat, meth, fn) in enumerate(routes):
        n = [0]

        def group(m):
            n[0] += 1
            return f'<re("{m.group(1)}"):g{n[0] - 1}>'
        rule = re.sub(r"\((?!\?)([^()]*)\)", group, pat)
        ep = f"{fn.__name__}_{meth}_{i}"
        VIEWS[f"{bp.name}.{ep}"] = fn
        bp.add_url_rule(rule, endpoint=ep, view_func=_view, methods=[meth])


def install(flask_app) -> None:
    """Hook the shared behaviour into the Flask app."""
    flask_app.url_map.strict_slashes = False
    flask_app.url_map.converters["re"] = ReConverter
    flask_app.before_request(_guard)
    flask_app.after_request(_headers)
    flask_app.register_error_handler(Exception, _error)
