"""Controller (the C of MVC): the thumbnail studio and each member's own thumbnail look."""
from flask import Blueprint

from app.controllers.video_controller import _video_for
from app.engine import thumb_styles
from app.http import register
from app.services import thumbnail_service as ts
from app.services import token_service as tokens
from app.services.upload_service import push_thumbnail
from app.models import Video


def _body(h) -> bytes:
    n = int(h.headers.get("Content-Length") or 0)
    return h.rfile.read(n) if 0 < n <= 7_000_000 else b""


def _doc(h, vid):
    doc = _video_for(h, vid)
    if not doc:
        h.send_json(404, {"error": "not found"})
    return doc


def h_thumb_options(h):
    """Styles, fonts, colours, the member's own look and what the paid actions cost."""
    h.send_json(200, {"styles": [{"id": i, "name": n} for i, n in thumb_styles.STYLES], "fonts": thumb_styles.available_fonts(), "colors": ts.PRESET_COLORS,
                      "brand": ts.get_brand(h.uid), "prices": ts.prices(), "owner": h.is_owner(), "tiers": ts.tier_options(h.is_owner())})


def h_brand_put(h):
    h.send_json(200, {"brand": ts.save_brand(h.uid, h.body_json(), h.is_owner())})


def h_logo_post(h):
    ts.save_logo(h.uid, _body(h))
    h.send_json(200, {"brand": ts.get_brand(h.uid)})


def h_logo_delete(h):
    ts.remove_logo(h.uid)
    h.send_json(200, {"brand": ts.get_brand(h.uid)})


def h_logo_get(h):
    from app.engine import thumbnail_generator
    p = thumbnail_generator.logo_path(h.uid)
    if not p:
        return h.send_json(404, {"error": "no logo"})
    body = p.read_bytes()        # a small file: send the bytes so no file stays open (Windows cannot delete an open file)
    h.send_response(200)
    h.send_header("Content-Type", "image/png")
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


def h_thumb_info(h, vid):
    doc = _doc(h, vid)
    if doc:
        h.send_json(200, ts.info(doc, h.uid))


def h_thumb_preview(h, vid):
    doc = _doc(h, vid)
    if not doc:
        return
    body = ts.preview_bytes(doc, h.uid, h.body_json())
    h.send_response(200)
    h.send_header("Content-Type", "image/jpeg")
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


def h_thumb_art(h, vid):
    doc = _doc(h, vid)
    if doc:
        charged = ts.make_art(doc, h.uid, str(h.body_json().get("scene") or ""))
        h.send_json(200, {"ok": True, "charged": charged, "info": ts.info(doc, h.uid)})


def h_thumb_art_upload(h, vid):
    doc = _doc(h, vid)
    if doc:
        ts.save_art_upload(doc, _body(h))
        h.send_json(200, {"ok": True, "info": ts.info(doc, h.uid)})


def h_thumb_variants(h, vid):
    """Three different thumbnails of this video to compare (free)."""
    doc = _doc(h, vid)
    if doc:
        h.send_json(200, {"variants": ts.variants(doc, h.uid, h.body_json())})


def h_thumb_batch_start(h, vid):
    doc = _doc(h, vid)
    if doc:
        d = h.body_json()
        n = 3 if d.get("n") in (None, "") else max(1, min(3, int(d["n"])))      # how many pictures to draw: 1 to 3 (the studio offers 1 or 3); no number = 3
        h.send_json(200, ts.art_batch_start(doc, h.uid, str(d.get("scene") or ""), n))


def h_thumb_batch_status(h, vid):
    doc = _doc(h, vid)
    if doc:
        h.send_json(200, ts.info(doc, h.uid))


def h_thumb_pick(h, vid):
    doc = _doc(h, vid)
    if doc:
        ts.art_pick(doc, int(h.body_json().get("slot") or 0))
        h.send_json(200, {"ok": True, "info": ts.info(doc, h.uid)})


def h_thumb_edited(h, vid):
    """The picture made in the browser editor (crop, arrows, emoji, text) becomes the thumbnail."""
    doc = _doc(h, vid)
    if not doc:
        return
    ts.save_edited(doc, h.uid, _body(h))
    msg = "Your edited thumbnail is saved."
    doc = Video.find_one(id=doc["_id"])
    if doc.get("youtube_id"):
        ok, why = push_thumbnail(doc)
        msg += " It is on YouTube now." if ok else f" (YouTube: {why})"
    h.send_json(200, {"ok": True, "message": msg})


def h_font(h, font_id):
    body = ts.font_bytes(font_id)
    if body is None:
        return h.send_json(404, {"error": "no such font"})
    h.send_response(200)
    h.send_header("Content-Type", "font/ttf")
    h.send_header("Cache-Control", "public, max-age=86400")
    h.end_headers()
    h.wfile.write(body)


def h_thumb_suggest(h, vid):
    doc = _doc(h, vid)
    if doc:
        h.send_json(200, ts.suggest_headlines(doc, h.uid))


def h_thumb_save(h, vid):
    doc = _doc(h, vid)
    if not doc:
        return
    out = ts.save(doc, h.uid, h.body_json())
    msg = "Your thumbnail is saved."
    doc = Video.find_one(id=doc["_id"])
    if doc.get("youtube_id"):
        ok, why = push_thumbnail(doc)
        msg += " It is on YouTube now." if ok else f" (YouTube: {why})"
    h.send_json(200, {"ok": True, "message": msg, "style": out["style"]})


ROUTES = [
    (r"/api/thumb/options", "GET", h_thumb_options),
    (r"/api/brand", "PUT", h_brand_put),
    (r"/api/brand/logo", "POST", h_logo_post),
    (r"/api/brand/logo", "DELETE", h_logo_delete),
    (r"/api/brand/logo", "GET", h_logo_get),
    (r"/api/videos/([0-9a-f]{24})/thumb-info", "GET", h_thumb_info),
    (r"/api/videos/([0-9a-f]{24})/thumb-preview", "POST", h_thumb_preview),
    (r"/api/videos/([0-9a-f]{24})/thumb-art", "POST", h_thumb_art),
    (r"/api/videos/([0-9a-f]{24})/thumb-art-upload", "POST", h_thumb_art_upload),
    (r"/api/videos/([0-9a-f]{24})/thumb-suggest", "POST", h_thumb_suggest),
    (r"/api/videos/([0-9a-f]{24})/thumb-variants", "POST", h_thumb_variants),
    (r"/api/videos/([0-9a-f]{24})/thumb-batch", "POST", h_thumb_batch_start),
    (r"/api/videos/([0-9a-f]{24})/thumb-batch", "GET", h_thumb_batch_status),
    (r"/api/videos/([0-9a-f]{24})/thumb-pick", "POST", h_thumb_pick),
    (r"/api/videos/([0-9a-f]{24})/thumb-edited", "POST", h_thumb_edited),
    (r"/api/font/([a-z]{3,12})", "GET", h_font),
    (r"/api/videos/([0-9a-f]{24})/thumb-save", "POST", h_thumb_save),
]
bp = Blueprint("thumbnail", __name__)
register(bp, ROUTES)
