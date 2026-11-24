"""Reaction Lab (beta): find the moments people react to, let the member judge them, and learn from the judgments.

Fully separate from the rest of the studio: it has its own collections, its own folder, its own endpoints and page, it never starts a video job,
never uploads, never spends AI tokens and never changes a setting. It only READS from the clip finder's download helpers.

One scan:  read the link  ->  listen to the sound (and read the chat replay when the platform allows)  ->  mark the strongest moments
           ->  cut a short preview of each and look at the camera picture / listen to the words  ->  score every moment with the model.
"""
import shutil
import threading
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from app.config import OUTPUT_DIR
from app.engine import clipcfg
from app.engine import discovery as D
from app.engine import finder as F
from app.engine import reaction_model as rm
from app.engine import reaction_signals as RS
from app.models import RxLabel, RxModel, RxScan, now, oid
from app.services import editor_service as ed

MOMENTS = (8, 12, 16)
PASS_SECONDS = 30 * 60
KEEP_SCANS = 4
KEEP_HOURS = 72
_RUN = threading.Semaphore(1)                       # one scan at a time: it uses the network and the CPU of the shared server


def folder(uid, sid) -> Path:
    d = OUTPUT_DIR / "reactions" / str(uid) / str(sid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_of(uid, sid: str, cid: str, what: str) -> Optional[Path]:
    p = folder(uid, sid) / f"{cid}.{'mp4' if what == 'video' else 'jpg'}"
    return p if p.is_file() else None


# ---------------------------------------------------------------- the model the member is using
def _model_doc(uid, category: str) -> Optional[Dict]:
    d = RxModel.find_one(user_id=str(uid), category=category)
    return {"w": list(d["w"]), "b": float(d["b"]), "n": int(d.get("n") or 0), "pos": int(d.get("pos") or 0), "trained": True, "acc": d.get("acc"), "base": d.get("base")} if d and d.get("w") else None


def model_for(uid, category: str) -> Optional[Dict]:
    """The model that scores a scan of this kind: the kind's own once it has enough judgments, else the general one, else None (starting weights)."""
    if category and category != "any":
        m = _model_doc(uid, category)
        if m:
            return m
    return _model_doc(uid, "any")


def _save_model(uid, category: str, m: Optional[Dict]) -> None:
    RxModel.objects(user_id=str(uid), category=category).delete()
    if m:
        RxModel(user_id=str(uid), category=category, trained_at=now(), **{k: m[k] for k in ("w", "b", "n", "pos", "acc", "base")}).save()


def retrain(uid, category: str = "any") -> None:
    """Learn from every judgment so far (general model), and from this kind's own judgments once there are enough of them."""
    rows = list(RxLabel.find_all(user_id=str(uid)))
    _save_model(uid, "any", rm.train([r.get("feat") or {} for r in rows], [r.get("y") for r in rows]))
    if category and category != "any":
        mine = [r for r in rows if r.get("category") == category]
        _save_model(uid, category, rm.train([r.get("feat") or {} for r in mine], [r.get("y") for r in mine]) if len(mine) >= rm.CATEGORY_MIN else None)


def model_status(uid) -> Dict:
    rows = list(RxLabel.find_all(user_id=str(uid)))
    models = [rm.describe(_model_doc(uid, "any"), "any")]
    per = {}
    for r in rows:
        c = per.setdefault(r.get("category") or "any", {"n": 0, "good": 0})
        c["n"] += 1
        c["good"] += 1 if r.get("y") else 0
    for cat in rm.CATEGORIES[1:]:
        m = _model_doc(uid, cat)
        if m:
            models.append(rm.describe(m, cat))
    good = sum(1 for r in rows if r.get("y"))
    return {"labels": len(rows), "good": good, "bad": len(rows) - good, "by_category": per, "models": models, "min_each": rm.MIN_EACH_CLASS, "category_min": rm.CATEGORY_MIN,
            "general_ready": bool(_model_doc(uid, "any"))}


def reset_model(uid) -> int:
    n = RxModel.objects(user_id=str(uid)).count()
    RxModel.objects(user_id=str(uid)).delete()
    return n


# ---------------------------------------------------------------- what the browser sees
def _sig_rows(c: Dict) -> List[Dict]:
    feat, avail = c.get("feat") or {}, set(c.get("avail") or [])
    return [{"id": s, "label": rm.LABEL[s], "help": rm.HELP[s], "value": int(round(100 * float(feat.get(s) or 0))) if s in avail else None} for s in rm.SIGNALS]


def cview(sid: str, c: Dict) -> Dict:
    return {"id": c["id"], "start": c["start"], "end": c["end"], "length": round(c["end"] - c["start"]), "score": c["score"], "reasons": c.get("reasons") or [], "signals": _sig_rows(c),
            "ready": bool(c.get("ready")), "video": f"/api/reactions/scans/{sid}/c/{c['id']}/video", "thumb": f"/api/reactions/scans/{sid}/c/{c['id']}/thumb" if c.get("has_thumb") else None,
            "said": c.get("said") or "", "label": c.get("label"), "category": c.get("cat") or "any", "peak": c.get("peak")}


def view(doc: Dict) -> Dict:
    sid = str(doc["_id"])
    cands = sorted(doc.get("candidates") or [], key=lambda c: -c["score"])
    return {"id": sid, "title": doc.get("title"), "creator": doc.get("creator"), "platform": doc.get("platform"), "url": doc.get("url"), "status": doc.get("status"), "message": doc.get("message") or "",
            "pct": int(doc.get("pct") or 0), "duration": doc.get("duration"), "window": doc.get("window"), "category": doc.get("category") or "any", "timeline": doc.get("timeline") or [],
            "step": doc.get("step") or 1, "available": doc.get("available") or {}, "model": doc.get("model_note") or "", "candidates": [cview(sid, c) for c in cands],
            "created_at": doc["created_at"].replace(tzinfo=None).isoformat() + "Z" if doc.get("created_at") else None}


def get_scan(uid, sid: str) -> Optional[Dict]:
    try:
        d = RxScan.find_one(id=oid(sid))
    except ValueError:
        return None
    return d if d and d.get("user_id") == str(uid) else None


def list_scans(uid) -> List[Dict]:
    out = []
    for d in RxScan.find_all(user_id=str(uid), order=("-created_at",), limit=KEEP_SCANS):
        cs = d.get("candidates") or []
        out.append({"id": str(d["_id"]), "title": d.get("title"), "status": d.get("status"), "category": d.get("category") or "any", "count": len(cs), "judged": sum(1 for c in cs if c.get("label") is not None),
                    "created_at": d["created_at"].replace(tzinfo=None).isoformat() + "Z"})
    return out


def delete_scan(uid, sid: str) -> bool:
    d = get_scan(uid, sid)
    if not d:
        return False
    shutil.rmtree(OUTPUT_DIR / "reactions" / str(uid) / sid, ignore_errors=True)
    RxScan.objects(id=d["_id"]).delete()                  # the judgments stay: they are what the lab learns from
    return True


def _prune(uid) -> None:
    for i, d in enumerate(RxScan.find_all(user_id=str(uid), order=("-created_at",))):
        old = d.get("created_at") and (now() - d["created_at"].replace(tzinfo=now().tzinfo)).total_seconds() > KEEP_HOURS * 3600
        if i >= KEEP_SCANS or old:
            shutil.rmtree(OUTPUT_DIR / "reactions" / str(uid) / str(d["_id"]), ignore_errors=True)
            RxScan.objects(id=d["_id"]).delete()


# ---------------------------------------------------------------- scanning
def _set(sid, **f) -> None:
    RxScan.objects(id=oid(str(sid))).update(**{f"set__{k}": v for k, v in f.items()})


def start_scan(uid, url: str, category: str = "any", moments: int = 12, faces: bool = True, words: bool = False, start=None, end=None) -> str:
    url = (url or "").strip()
    if len(url) > 300 or not ed.LINK_RE.match(url):
        raise ValueError("Paste a link to a YouTube or Twitch video or a stream replay.")
    category = category if category in rm.CATEGORIES else "any"
    moments = int(moments) if int(moments) in MOMENTS else 12
    a, b = (ed._parse_time(start), ed._parse_time(end)) if (start or end) else (None, None)
    if a is not None and b and b - a < 120:
        raise ValueError("Choose a part at least two minutes long.")
    if RxScan.total(user_id=str(uid), status="running"):
        raise ValueError("A scan is already running. Wait for it to finish.")
    _prune(uid)
    doc = RxScan(user_id=str(uid), title="Scanning…", url=url, status="running", created_at=now(), pct=2, message="Starting…", category=category, candidates=[]).save()
    threading.Thread(target=_run, args=(str(uid), str(doc.id), url, category, moments, bool(faces), bool(words), a, b), daemon=True).start()
    return str(doc.id)


def _run(uid, sid, url, category, moments, faces, words, a, b) -> None:
    try:
        with _RUN:
            _scan(uid, sid, url, category, moments, faces, words, a, b)
    except ValueError as e:
        _set(sid, status="error", message=str(e)[:300])
    except Exception as e:
        _set(sid, status="error", message=f"Something went wrong: {type(e).__name__}: {str(e)[:200]}")


def _fetch_chat(url: str, fold: Path) -> list:
    """The chat replay of a past stream, when the platform lets us read it (YouTube does for streams that were live). [] otherwise: the lab then works without chat."""
    try:
        D._ytdlp("--skip-download", "--write-subs", "--sub-langs", "live_chat,rechat", "--no-playlist", "-o", str(fold / "chat.%(ext)s"), url, timeout=300)
    except Exception:
        return []
    events: list = []
    for p in list(fold.glob("chat*.json")) + list(fold.glob("chat*.jsonl")):
        events += RS.parse_chat(p)
        p.unlink(missing_ok=True)
    return events


def _heat_array(info: Dict, a: float, n: int) -> Optional[np.ndarray]:
    hm = info.get("heatmap") or []
    if not hm:
        return None
    arr = np.zeros(n)
    top = max((float(h.get("value") or 0) for h in hm), default=0) or 1.0
    for h in hm:
        s, e = float(h.get("start_time") or 0) - a, float(h.get("end_time") or 0) - a
        lo, hi = max(0, int(s)), min(n, int(np.ceil(e)))
        if hi > lo:
            arr[lo:hi] = float(h.get("value") or 0) / top
    return arr


def _stage_one(sig: Dict[str, np.ndarray], chat: Optional[Dict], heat: Optional[np.ndarray]) -> np.ndarray:
    """One number per second to find the places worth a closer look: the starting weights over the signals we have for the whole video."""
    n = len(sig["loud"])
    z = np.zeros(n)
    for s in ("loud", "burst", "laugh", "hush"):
        z += rm.PRIOR[s] * sig[s]
    if chat:
        z += rm.PRIOR["chat"] * chat["chat"] + rm.PRIOR["hype"] * chat["hype"]
    if heat is not None:
        z += rm.PRIOR["heat"] * heat[:n]
    return np.convolve(z, np.ones(5) / 5, mode="same")


def _peaks(z: np.ndarray, want: int, before: int, after: int, gap: int = 45) -> List[int]:
    z = z.copy()
    n = len(z)
    z[:before] = -1e9
    z[max(0, n - after - 2):] = -1e9
    floor = float(np.percentile(z[z > -1e8], 60)) if (z > -1e8).any() else 0.0
    out: List[int] = []
    while len(out) < want:
        i = int(z.argmax())
        if z[i] <= floor or z[i] < -1e8:
            break
        out.append(i)
        z[max(0, i - gap):i + gap] = -1e9
    return out


def _scan(uid, sid, url, category, moments, faces, words, a, b) -> None:
    fold = folder(uid, sid)
    before, after = clipcfg.span()
    _set(sid, message="Reading the link…", pct=4)
    info = F.probe_url(url)
    if info["live"]:
        raise ValueError("The Reaction Lab (beta) reads past videos and stream replays. Open the replay of that stream instead.")
    if info["age_limit"] >= 18:
        raise ValueError("That video is age-restricted, so it cannot be used.")
    dur = info["duration"] or 0
    if dur < 180:
        raise ValueError("That video is too short to find reactions in (it needs at least three minutes).")
    a = 0.0 if a is None else float(a)
    end_ = min(dur, b if b else a + PASS_SECONDS)
    _set(sid, title=info["title"][:140], creator=info["creator"], platform=info["platform"], duration=dur, window=[a, end_], message="Listening to the sound…", pct=12)
    audio = F.download_audio(url, (a, end_), fold / "audio")
    x = RS.read_samples(audio)
    audio.unlink(missing_ok=True)
    sig = RS.audio_signals(x)
    if not len(sig["loud"]):
        raise ValueError("Could not read the sound of that video.")
    n = len(sig["loud"])
    _set(sid, message="Reading the chat replay…", pct=30)
    chat = RS.chat_signals(_fetch_chat(url, fold), n, offset=a)
    heat = _heat_array(info, a, n)
    _set(sid, message="Marking the strongest moments…", pct=42)
    z1 = _stage_one(sig, chat, heat)
    peaks = _peaks(z1, moments, before, after)
    if not peaks:
        raise ValueError("No clear reaction moments were found in this part. Try another part of the video.")
    model = model_for(uid, category)
    cands: List[Dict] = []
    seen_face = seen_words = False
    for k, p in enumerate(sorted(peaks), start=1):
        _set(sid, message=f"Looking closely at moment {k} of {len(peaks)}…", pct=45 + int(50 * k / len(peaks)))
        feat = RS.window_features(sig, chat, heat, p)
        avail = ["loud", "burst", "laugh", "hush"] + (["chat", "hype"] if chat else []) + (["heat"] if heat is not None else [])
        c = {"id": f"c{k}", "start": round(a + max(0, p - before), 1), "end": round(min(end_, a + p + after), 1), "peak": round(a + p, 1), "ready": False}
        vid = fold / f"{c['id']}.mp4"
        try:
            F.download_preview(url, c["start"], c["end"], vid)
            c["ready"] = True
            c["has_thumb"] = bool(F.thumbnail(vid, fold / f"{c['id']}.jpg"))
            ps = RS.picture_signals(vid, faces_on=faces)
            feat["action"] = ps["action"]
            avail.append("action")
            if ps["smile"] is not None:
                feat["smile"], feat["jolt"] = ps["smile"], ps["jolt"]
                avail += ["smile", "jolt"]
                seen_face = True
            if words:
                ws = RS.word_signals(vid)
                if ws["words"] is not None:
                    feat["words"] = ws["words"]
                    avail.append("words")
                    c["said"] = ws["text"]
                    seen_words = True
        except Exception:
            pass                                          # no preview for this moment: it is still scored from the sound and chat
        c.update(feat=feat, avail=avail, cat=category, label=None, score=rm.score(feat, model), reasons=rm.reasons(feat, model))
        cands.append(c)
    step = max(1, n // 240)
    tl = [int(round(100 * float(rm.sigmoid(z1[i:i + step].max() + rm.PRIOR_BIAS)))) for i in range(0, n, step)]
    _set(sid, candidates=cands, timeline=tl, step=step, status="done", pct=100, message=f"{len(cands)} moments found", model_note=("your trained model" if model else "the starting weights"),
         available={"audio": True, "chat": bool(chat), "heat": heat is not None, "faces": seen_face, "words": seen_words, "faces_asked": faces, "words_asked": words})


# ---------------------------------------------------------------- judging and learning
def judge(uid, sid: str, cid: str, y, category: str = "") -> Dict:
    """Say whether a moment is a good reaction (1), not good (0) or take the judgment back (None). The lab retrains at once."""
    d = get_scan(uid, sid)
    if not d:
        raise ValueError("That scan is not available any more.")
    if y not in (1, 0, None, True, False):
        raise ValueError("Choose good or not good.")
    cands = d.get("candidates") or []
    c = next((x for x in cands if x["id"] == cid), None)
    if not c:
        raise ValueError("That moment is not in this scan.")
    cat = category if category in rm.CATEGORIES else (c.get("cat") or d.get("category") or "any")
    RxLabel.objects(user_id=str(uid), scan_id=sid, cand_id=cid).delete()
    if y is None:
        c["label"] = None
    else:
        c["label"], c["cat"] = int(bool(y)), cat
        RxLabel(user_id=str(uid), scan_id=sid, cand_id=cid, category=cat, created_at=now(), y=int(bool(y)), feat={s: float((c.get("feat") or {}).get(s) or 0) for s in rm.SIGNALS},
                title=d.get("title") or "").save()
    RxScan.objects(id=d["_id"]).update(set__candidates=cands)
    retrain(uid, cat)
    return model_status(uid)


def rescore(uid, sid: str) -> Dict:
    """Score the moments of a scan again with what the lab has learned since (so the member sees the difference)."""
    d = get_scan(uid, sid)
    if not d:
        raise ValueError("That scan is not available any more.")
    model = model_for(uid, d.get("category") or "any")
    cands = d.get("candidates") or []
    for c in cands:
        c["score"], c["reasons"] = rm.score(c.get("feat") or {}, model), rm.reasons(c.get("feat") or {}, model)
    RxScan.objects(id=d["_id"]).update(set__candidates=cands, set__model_note="your trained model" if model else "the starting weights")
    return view(RxScan.find_one(id=d["_id"]))
