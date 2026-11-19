"""Controller (the C of MVC): approve endpoints."""
from urllib.parse import urlparse

from flask import Blueprint, render_template

from app.http import register
from app.services.upload_service import _by_token, decline_video, publish_video

def h_approve_page(h, token):
    want_decline = "decline=1" in (urlparse(h.path).query or "")
    h.send_html(render_template("approve.html", doc=_by_token(token), want_decline=want_decline))


def h_approve_do(h, token):
    doc = _by_token(token)
    if not doc:
        return h.send_json(404, {"error": "This approval link is invalid, expired, or already used."})
    ok, msg = publish_video(doc)
    h.send_json(200 if ok else 502, {"message": msg} if ok else {"error": msg})


def h_decline_do(h, token):
    doc = _by_token(token)
    if not doc:
        return h.send_json(404, {"error": "This link is invalid, expired, or already used."})
    ok, msg = decline_video(doc)
    h.send_json(200 if ok else 409, {"message": msg} if ok else {"error": msg})


ROUTES = [
    (r"/approve/([\w-]{20,64})", "GET", h_approve_page),
    (r"/approve/([\w-]{20,64})", "POST", h_approve_do),
    (r"/approve/([\w-]{20,64})/decline", "POST", h_decline_do),
]
bp = Blueprint("approve", __name__)
register(bp, ROUTES)
