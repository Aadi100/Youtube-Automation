"""Thumbnail studio: every video's thumbnail can be shaped by the person who owns it.

  * pick the moment of the video to use (any frame), or an AI picture, or the person's own picture
  * pick a style (8 looks) or let the studio vary it (never the same style as the last two videos)
  * write the headline and the small text, choose the colours and the font (AI headline ideas cost a token)
  * each member has their own look (default style, colours, font, logo) that new videos use automatically
Frames, styles and text are free. Only a new AI picture and AI headline ideas cost tokens.
"""
import base64
import io
import json
import os
import random
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from app.config import BASE_DIR
from app.engine import thumb_styles, thumbnail_generator as tg
from app.models import Clip, UserPrefs, Video
from app.services import token_service as tokens
from app.utils.paths import inside_outputs

BRANDS = BASE_DIR / "state" / "brands"
PRESET_COLORS = ["#FFE600", "#FFFFFF", "#FF2D87", "#18A0FB", "#22D3A0", "#FF7A18", "#B14CFF", "#FF3B30"]
_frames: Dict[tuple, Image.Image] = {}


def mode_of(doc: Dict) -> str:
    return "16:9" if doc.get("kind") == "compilation" else "9:16"


# ------------------------------------------------------------------ the member's own look
def get_brand(uid) -> Dict:
    b = UserPrefs.of(uid).get("brand") or {}
    return {"style": b.get("style") if b.get("style") in thumb_styles.STYLE_IDS else "auto",
            "text": thumb_styles.valid_color(b.get("text"), thumb_styles.DEFAULT_TEXT), "accent": thumb_styles.valid_color(b.get("accent"), thumb_styles.DEFAULT_ACCENT),
            "font": b.get("font") if b.get("font") in thumb_styles.FONTS else thumb_styles.DEFAULT_FONT, "has_logo": tg.logo_path(str(uid)) is not None,
            "pictures": 3 if int(b.get("pictures") or 1) >= 3 else 1, "tier": b.get("tier") if b.get("tier") in tg.TIERS else "free"}


CLAUDE_PLAN_TOKENS = 2600      # about what one High plan + review uses (4 small frames, the facts, a short JSON answer, one look at the result)


def tier_options(is_owner: bool) -> List[Dict]:
    """The three thumbnail levels: what each does, what it costs at today's prices, and whether this person may use it now."""
    from app.services import diy_service
    p, fl = tokens.pricing(), diy_service.flags()
    gem, cla = bool(os.environ.get("GEMINI_API_KEY")), bool(os.environ.get("ANTHROPIC_API_KEY"))
    est_hi = p["image_gemini"] + CLAUDE_PLAN_TOKENS / 1000.0 * p["claude_per_1k"]
    off = "The owner has not switched this level on."
    # the owner is told which service and key is missing; a member only reads what the level does and whether it is available (no service or model names)
    rows = [("free", "Free", "A free AI picture. The best frame is found by code.", p["image_free"], True, ""),
            ("medium", "Better", "Gemini redraws the real frame as a dramatic thumbnail picture." if is_owner else "The AI redraws the real frame as a dramatic thumbnail picture.", p["image_gemini"],
             gem and (is_owner or fl["tier_medium"]),
             "" if gem and (is_owner or fl["tier_medium"]) else (("Needs the Gemini key." if not gem else off) if is_owner else (off if not fl["tier_medium"] else "Not available right now."))),
            ("high", "Best", "Claude looks at the best frames and plans the headline, look and scene. Gemini draws it, Claude checks it." if is_owner
             else "The AI studies the best frames, plans the headline, look and scene, then draws it and checks the result.", est_hi, gem and cla and (is_owner or fl["tier_high"]),
             "" if gem and cla and (is_owner or fl["tier_high"]) else (("Needs the Claude key (Settings)." if not cla else "Needs the Gemini key." if not gem else off) if is_owner
                                                                       else (off if not fl["tier_high"] else "Not available right now.")))]
    return [{"id": i, "name": n, "desc": d, "price": round(pr, 1), "available": bool(ok), "reason": why} for i, n, d, pr, ok, why in rows]


def effective_tier(requested: Optional[str], uid, is_owner: bool) -> str:
    """The level a video really gets: what was asked (else the member's default), never above what they may use now."""
    want = requested or get_brand(uid)["tier"]
    ok = {t["id"] for t in tier_options(is_owner) if t["available"]}
    return want if want in ok else ("medium" if want == "high" and "medium" in ok else "free")


def check_tier(tier: str, is_owner: bool) -> None:
    for t in tier_options(is_owner):
        if t["id"] == tier:
            if not t["available"]:
                raise ValueError(t["reason"] or "That level is not available.")
            return
    raise ValueError("Choose Free, Better or Best.")


def save_brand(uid, d: Dict, is_owner: bool = True) -> Dict:
    style = d.get("style") or "auto"
    if style != "auto" and style not in thumb_styles.STYLE_IDS:
        raise ValueError("Choose one of the listed styles, or 'Vary automatically'.")
    font = d.get("font") or thumb_styles.DEFAULT_FONT
    if font not in thumb_styles.FONTS:
        raise ValueError("Choose one of the listed fonts.")
    tier = d.get("tier") or get_brand(uid)["tier"]
    if tier != get_brand(uid)["tier"]:
        check_tier(tier, is_owner)                 # choosing a level you may not use is refused (keeping the one you already had is fine)
    brand = {"style": style, "text": thumb_styles.valid_color(d.get("text"), thumb_styles.DEFAULT_TEXT),
             "accent": thumb_styles.valid_color(d.get("accent"), thumb_styles.DEFAULT_ACCENT), "font": font, "pictures": 3 if str(d.get("pictures") or "1") == "3" else 1, "tier": tier}
    UserPrefs.set_fields(str(uid), brand=brand, upsert=True)
    return get_brand(uid)


def _image_from(raw: bytes, max_bytes: int) -> Image.Image:
    if not raw or len(raw) > max_bytes:
        raise ValueError(f"Choose an image up to {max_bytes // 1_000_000} MB (JPG or PNG).")
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        return im
    except Exception:
        raise ValueError("That file is not an image. Use a JPG or PNG.")


def save_logo(uid, raw: bytes) -> None:
    im = _image_from(raw, 3_000_000).convert("RGBA")
    im.thumbnail((500, 500), Image.Resampling.LANCZOS)
    BRANDS.mkdir(parents=True, exist_ok=True)
    im.save(BRANDS / f"{uid}.png", "PNG")


def remove_logo(uid) -> None:
    p = tg.logo_path(str(uid))
    if p:
        p.unlink(missing_ok=True)


# ------------------------------------------------------------------ the video and its picture
def _paths(doc: Dict):
    video = Path(inside_outputs(doc.get("video_path") or ""))
    return video, video.with_name(video.stem + "_art.jpg")


def slot_file(doc: Dict, slot: int) -> Path:
    video, _ = _paths(doc)
    return video.with_name(f"{video.stem}_art_{int(slot)}.jpg")


def _meta(doc: Dict) -> Dict:
    try:
        return json.loads(Path(inside_outputs(doc.get("video_path") or "")).with_suffix(".json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def info(doc: Dict, uid) -> Dict:
    from app.engine.video_processor import get_video_info
    video, art = _paths(doc)
    if not video.is_file():
        raise ValueError("The video file is missing.")
    m = _meta(doc)
    return {"duration": round(float(get_video_info(video)["duration"]), 2), "mode": mode_of(doc), "has_art": art.is_file(), "art_version": int(art.stat().st_mtime) if art.is_file() else 0,
            "slots": [i for i in (1, 2, 3) if slot_file(doc, i).is_file()], "batch": art_batch_status(doc),
            "headline": m.get("thumb_headline") or (doc.get("title") or "")[:30].replace("#Shorts", "").strip().upper(), "subtext": m.get("thumb_subtext") or (doc.get("game_name") or ""),
            "style": doc.get("thumb_style") if doc.get("thumb_style") in thumb_styles.STYLE_IDS else "classic",      # "edited"/"own" thumbnails have no studio style
            "brand": get_brand(uid)}


def _frame(doc: Dict, t: Optional[float]) -> Image.Image:
    """A frame of the video: from the original clip when it still exists (no blurred bars), else from the finished video."""
    video, _ = _paths(doc)
    src, from_clip = video, False
    if doc.get("kind") != "compilation":
        for cid in (doc.get("clip_ids") or [])[:1]:
            c = Clip.find_one(id=cid)
            if c and c.get("path") and Path(c["path"]).is_file():
                src, from_clip = Path(c["path"]), True
    from app.engine.video_processor import get_video_info
    dur = float(get_video_info(src)["duration"])
    ts = max(0.0, min(float(t) if t is not None else dur * 0.65, max(0.0, dur - 0.2)))
    key = (str(src), int(src.stat().st_mtime), round(ts, 1))
    if key not in _frames:
        tmp = src.with_name(f"_thumbframe_{int(time.time() * 1000)}.jpg")
        try:
            tg.extract_keyframe(src, tmp, timestamp=ts)
            fr = Image.open(tmp).convert("RGB")
            fr.load()
        finally:
            tmp.unlink(missing_ok=True)
        if not from_clip and fr.height > fr.width * 1.4:     # a finished vertical Short: only its sharp middle band, not the blurred bars
            fr = fr.crop((0, int(fr.height * 0.34), fr.width, int(fr.height * 0.66)))
        fr = fr.crop((0, 0, fr.width, int(fr.height * 0.82)))
        if len(_frames) > 12:
            _frames.clear()
        _frames[key] = fr
    return _frames[key].copy()


def render_image(doc: Dict, uid, o: Dict) -> Image.Image:
    brand = get_brand(uid)
    m = _meta(doc)
    style = o.get("style") or "classic"
    if style not in thumb_styles.STYLE_IDS and style != "auto":     # a value left by an edited / uploaded thumbnail
        style = "classic"
    if style == "auto":
        style = thumb_styles.pick_style(str(uid), brand["style"] if brand["style"] != "auto" else None)
    if style not in thumb_styles.STYLE_IDS:
        raise ValueError("Unknown style.")
    _, art_file = _paths(doc)
    if o.get("art_slot") in (1, 2, 3, "1", "2", "3"):
        art_file = slot_file(doc, int(o["art_slot"]))
    art = None
    if o.get("source") == "art" and art_file.is_file():
        with Image.open(art_file) as im:
            art = im.convert("RGB")
    if o.get("source") == "art" and art is None:
        raise ValueError("Make or upload a picture first.")
    frame = _frame(doc, o.get("t"))
    headline = (o.get("headline") or m.get("thumb_headline") or (doc.get("title") or "")[:30]).strip()[:60]
    sub = o.get("subtext") if o.get("subtext") is not None else (m.get("thumb_subtext") or doc.get("game_name") or "")
    font = o.get("font") if o.get("font") in thumb_styles.FONTS else brand["font"]
    img = thumb_styles.render(art, frame, style=style, mode=mode_of(doc), headline=headline, subtext=str(sub)[:30], text=o.get("text") or brand["text"],
                              accent=o.get("accent") or brand["accent"], font=font, logo=tg.logo_of(str(uid)))
    img.info["style"] = style
    return img


def preview_bytes(doc: Dict, uid, o: Dict) -> bytes:
    """A small preview, or (o["full"]) the full-size picture for the editor."""
    img = render_image(doc, uid, o)
    full = bool(o.get("full"))
    if not full:
        img.thumbnail((640, 640) if mode_of(doc) == "16:9" else (400, 720), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92 if full else 82)
    return buf.getvalue()


def variants(doc: Dict, uid, o: Dict, n: int = 3) -> List[Dict]:
    """Three different thumbnails of this video to compare: other moments, other styles, other colours and fonts. Free."""
    dur = float(info(doc, uid)["duration"])
    styles = [s for s in thumb_styles.STYLE_IDS if s != o.get("style")]
    random.shuffle(styles)
    colors = random.sample(PRESET_COLORS[2:], n)
    fonts = [f["id"] for f in thumb_styles.available_fonts()]
    random.shuffle(fonts)
    out = []
    for i in range(n):
        v = dict(o)
        v.update(style=styles[i % len(styles)], accent=colors[i], font=fonts[i % len(fonts)])
        if o.get("source") != "art":
            v.update(source="frame", t=round(max(0.0, min(dur - 0.3, dur * (0.15 + 0.35 * i) + random.uniform(-0.05, 0.05) * dur)), 1))
        v.pop("full", None)
        out.append({"opts": v, "image": "data:image/jpeg;base64," + base64.b64encode(preview_bytes(doc, uid, v)).decode()})
    return out


def save_edited(doc: Dict, uid, raw: bytes) -> Dict:
    """The picture made in the browser editor becomes the thumbnail (free). It keeps its own shape: 9:16 for Shorts, 16:9 for compilations."""
    im = _image_from(raw, 8_000_000).convert("RGB")
    W, H = (1280, 720) if mode_of(doc) == "16:9" else (1080, 1920)
    im = tg._cover(im, (W, H))
    video, _ = _paths(doc)
    target = Path(inside_outputs(str(video.with_name(f"{video.stem}_thumb_{int(time.time())}.jpg"))))
    for q in (92, 84, 76, 68):
        im.save(target, "JPEG", quality=q)
        if target.stat().st_size <= 1_900_000:
            break
    old = doc.get("thumbnail_path")
    Video.update_where(id=doc["_id"], fields={"thumbnail_path": str(target), "thumb_style": "edited", "thumbnail_own": True})
    if old and Path(old) != target and ("_thumb_" in Path(old).stem or "_mythumb" in Path(old).stem) and Path(old).is_file():
        Path(old).unlink(missing_ok=True)
    return {"path": str(target)}


def font_bytes(font_id: str) -> Optional[bytes]:
    """A bundled font file, so the browser editor draws text in the same fonts as the thumbnails."""
    f = thumb_styles.FONTS.get(font_id)
    p = BASE_DIR / "fonts" / f[1] if f else None
    return p.read_bytes() if p and p.is_file() else None


def save(doc: Dict, uid, o: Dict) -> Dict:
    """Make the real thumbnail and put it on the video (and on YouTube when the video is already there)."""
    img = render_image(doc, uid, o)
    video, _ = _paths(doc)
    target = Path(inside_outputs(str(video.with_name(f"{video.stem}_thumb_{int(time.time())}.jpg"))))
    for q in (92, 84, 76, 68):
        img.save(target, "JPEG", quality=q)
        if target.stat().st_size <= 1_900_000:
            break
    old = doc.get("thumbnail_path")
    Video.update_where(id=doc["_id"], fields={"thumbnail_path": str(target), "thumb_style": img.info.get("style"), "thumbnail_own": False})
    if old and Path(old) != target and "_thumb" in Path(old).stem and Path(old).is_file():
        Path(old).unlink(missing_ok=True)
    return {"path": str(target), "style": img.info.get("style")}


# ------------------------------------------------------------------ the two small paid actions
def ART_EVENT() -> Dict:
    return {"kind": "image", "provider": "gemini" if (os.environ.get("AI_IMAGE_PROVIDER") or "free").lower() == "gemini" else "free", "task": "thumbnail", "units": 1}



SUGGEST_EVENT = {"kind": "llm", "provider": "deepseek", "task": "thumbnail-headlines", "tokens_in": 650, "tokens_out": 220}


def prices() -> Dict:
    p = tokens.pricing()
    return {"art": max(1, tokens._up(tokens.price_event({**ART_EVENT(), "ok": True}, p))), "suggest": max(1, tokens._up(tokens.price_event({**SUGGEST_EVENT, "ok": True}, p)))}


def _afford(uid, events: List[Dict]) -> None:
    err = tokens.adhoc_shortfall(str(uid), events)
    if err:
        raise ValueError(err)


def make_art(doc: Dict, uid, scene: str) -> int:
    """A new AI picture for the thumbnail (one image: costs tokens). Returns the tokens charged."""
    from app.engine import ai_art
    if not ai_art.enabled():
        raise ValueError("AI pictures are switched off on this server.")
    ev = [ART_EVENT()]
    _afford(uid, ev)
    video, art_file = _paths(doc)
    got = ai_art.generate_background(doc.get("game_name") or "video game", mode_of(doc), art_file, scene=(scene or "").strip()[:200])
    if not got or not Path(got).is_file():
        raise ValueError("The picture service is busy right now. Nothing was charged. Please try again in a minute.")
    return tokens.charge_adhoc(str(uid), str(doc["_id"]), ev, "New AI picture for a thumbnail")


_BATCH: Dict[str, Dict] = {}


def art_batch_status(doc: Dict) -> Dict:
    st = _BATCH.get(str(doc["_id"]))
    return {"running": bool(st and st["running"]), "n": st["n"] if st else 0, "done": list(st["done"]) if st else [], "failed": st["failed"] if st else 0,
            "charged": st["charged"] if st else 0, "error": st["error"] if st else None}


def art_batch_start(doc: Dict, uid, scene: str, n: int = 3) -> Dict:
    """Draw n new AI pictures to choose from (each costs the image price when it is drawn; a failed one costs nothing). Runs in the background,
    because the free image service allows only one picture every 45 seconds."""
    from app.engine import ai_art
    if not ai_art.enabled():
        raise ValueError("AI pictures are switched off on this server.")
    vid = str(doc["_id"])
    if _BATCH.get(vid, {}).get("running"):
        raise ValueError("Pictures are already being drawn for this video. Wait for them to finish.")
    _afford(uid, [ART_EVENT() for _ in range(n)])
    for i in (1, 2, 3):          # a new batch replaces the earlier pictures
        slot_file(doc, i).unlink(missing_ok=True)
    st = _BATCH[vid] = {"running": True, "n": n, "done": [], "failed": 0, "charged": 0, "error": None}
    mode, game, scene = mode_of(doc), doc.get("game_name") or "video game", (scene or "").strip()[:200]
    files = [slot_file(doc, i) for i in range(1, n + 1)]

    def work():
        try:
            for slot, f in enumerate(files, 1):
                try:
                    err = tokens.adhoc_shortfall(str(uid), [ART_EVENT()])
                    if err:
                        st["error"] = err
                        break
                    got = ai_art.generate_background(game, mode, f, scene=scene)
                    if got and Path(got).is_file():
                        st["charged"] += tokens.charge_adhoc(str(uid), vid, [ART_EVENT()], "New AI picture for a thumbnail")
                        st["done"].append(slot)
                    else:
                        st["failed"] += 1
                except Exception:
                    st["failed"] += 1
        finally:
            st["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return art_batch_status(doc)


def art_pick(doc: Dict, slot: int) -> None:
    f = slot_file(doc, slot)
    if not f.is_file():
        raise ValueError("That picture is not there any more.")
    _, art = _paths(doc)
    shutil.copyfile(f, art)


def save_art_upload(doc: Dict, raw: bytes) -> None:
    """The member's own picture as the base of the thumbnail (free)."""
    im = _image_from(raw, 6_000_000).convert("RGB")
    W, H = (1280, 720) if mode_of(doc) == "16:9" else (1080, 1920)
    _, art_file = _paths(doc)
    tg._cover(im, (W, H)).save(art_file, "JPEG", quality=92)


def _ai_headlines(title: str) -> List[str]:
    from app.engine import llm
    prompt = (f"Write 6 different YouTube thumbnail headlines for a gaming video titled \"{title}\". Each is 2 to 4 words, ALL CAPS, at most 20 characters, "
              "an emotion or curiosity trigger, different from the title. Return ONLY a JSON array of 6 strings.")
    out = json.loads(llm.generate("metadata", prompt, json_mode=True, timeout=45).strip().removeprefix("```json").removesuffix("```").strip())
    if isinstance(out, dict):
        out = next(iter(out.values()))
    return [str(x).upper().strip()[:20] for x in out if str(x).strip()][:6]


def suggest_headlines(doc: Dict, uid) -> Dict:
    """Six headline ideas (2-4 words, capitals). AI ideas cost a token; with no AI available (or no tokens) the ideas come from the title for free."""
    import re
    title = re.sub(r"#\w+", "", doc.get("title") or "").strip()
    words = [w for w in re.findall(r"[A-Za-z0-9']+", title) if len(w) > 2]
    free = [x for x in [" ".join(words[:3]).upper(), "WAIT FOR IT", "NO WAY!", "HE PANICKED", "THIS WENT WRONG", "UNREAL MOMENT"] if x]
    ev = [SUGGEST_EVENT]
    if tokens.adhoc_shortfall(str(uid), ev) is None:
        try:
            ideas = _ai_headlines(title)
            if ideas:
                return {"headlines": ideas, "charged": tokens.charge_adhoc(str(uid), str(doc["_id"]), ev, "AI headline ideas")}
        except Exception:
            pass
    return {"headlines": free, "charged": 0}
