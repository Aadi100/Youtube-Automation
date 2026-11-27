"""Service (the business logic): the Learning Lab (beta). Owner only, separate from everything else.

Three parts, each with its own switch (all OFF until the owner turns them on):
  titles        examples the owner likes are shown to the AI that writes titles; a small model learns from the views of the owner's videos
                which kinds of titles do better and nudges the title choice a little
  descriptions  examples the owner likes (and descriptions the owner rewrote by hand) are shown to the AI that writes descriptions
  clipping      a small model learns from the videos the owner approved or declined which kinds of clips are worth making and nudges the
                score of a moment a little

Everything is scoped to the owner's own videos. What is recorded (what was generated, features of a clip) is only written down; it changes
nothing until a part is switched on. Every function that the video pipeline calls fails soft: a problem here never stops a video.
"""
import os
import time
from datetime import timedelta
from typing import Dict, List, Optional

import numpy as np

from app.services import analytics_service
from app.engine import lab_model as M
from app.models import Clip, User, Video, now
from app.models.lab import LabExample, LabLog, LabState

PARTS = ("titles", "descriptions", "clipping")
LIMITS = {"title": 120, "description": 700}
_owner_cache = {"at": 0.0, "id": None}


def owner_id() -> Optional[str]:
    if time.time() - _owner_cache["at"] > 60:
        o = User.find_one(role="owner")
        _owner_cache.update(at=time.time(), id=str(o["_id"]) if o else None)
    return _owner_cache["id"]


def _sid(uid, part: str) -> str:
    return f"{uid}:{part}"


# ---------------------------------------------------------------------------------------------- the switches and the models
def get_state(uid, part: str) -> Dict:
    d = LabState.find_one(id=_sid(uid, part)) or {}
    return {"on": bool(d.get("on")), "model": d.get("model"), "n": int(d.get("n") or 0), "trained_at": d.get("trained_at"), "note": d.get("note") or ""}


def set_on(uid, part: str, on: bool) -> Dict:
    if part not in PARTS:
        raise ValueError("unknown part")
    LabState.set_fields(_sid(uid, part), {"user_id": str(uid), "part": part, "on": bool(on)}, upsert=True)
    return get_state(uid, part)


def reset(uid, part: str) -> Dict:
    if part not in PARTS:
        raise ValueError("unknown part")
    LabState.update_where(id=_sid(uid, part), unset=("model", "trained_at", "note"), fields={"n": 0})
    return get_state(uid, part)


def active(part: str) -> Optional[Dict]:
    """The state of a part when it is on AND the running job belongs to the owner; else None. This is what the video pipeline asks."""
    try:
        uid = os.environ.get("CLIPSTUDIO_USER_ID") or ""
        if not uid or uid != owner_id():
            return None
        st = get_state(uid, part)
        return st if st["on"] else None
    except Exception:
        return None


# ---------------------------------------------------------------------------------------------- examples
def _norm(text: str, kind: str) -> str:
    return " ".join(str(text or "").split())[: LIMITS[kind]]


def list_examples(uid, kind: str, limit: int = 100) -> List[Dict]:
    return LabExample.find_all(user_id=str(uid), kind=kind, order=("-created_at",), limit=limit)


def add_example(uid, kind: str, text: str, source: str = "owner") -> Dict:
    if kind not in LIMITS:
        raise ValueError("kind must be title or description")
    t = _norm(text, kind)
    if len(t) < (12 if kind == "title" else 30):
        raise ValueError("That is too short to learn a style from.")
    for e in list_examples(uid, kind, 400):
        if _norm(e["text"], kind).lower() == t.lower():
            return e
    doc = LabExample(user_id=str(uid), kind=kind, text=t, source=source, created_at=now()).save()
    return LabExample.find_one(id=doc.id)


def delete_example(uid, ex_id: str) -> bool:
    from app.models.base import oid
    return LabExample.objects(id=oid(ex_id), user_id=str(uid)).delete() > 0


def examples_for_prompt(kind: str, n: int = 8) -> List[str]:
    """The owner's liked examples for the AI prompt (newest first), when that part is on. [] otherwise."""
    part = "titles" if kind == "title" else "descriptions"
    try:
        if not active(part):
            return []
        uid = os.environ.get("CLIPSTUDIO_USER_ID")
        return [e["text"] for e in list_examples(uid, kind, n)]
    except Exception:
        return []


def note_edit(before: Dict, changes: Dict) -> None:
    """The owner rewrote a title or description by hand: the new text becomes an example (it is what the owner actually wanted). Never raises."""
    try:
        if str(before.get("user_id")) != str(owner_id()):
            return
        uid = str(before.get("user_id"))
        if "title" in changes and M.clean_title(changes["title"]) != M.clean_title(before.get("title")):
            add_example(uid, "title", M.clean_title(changes["title"]), source="edit")
        if "description" in changes and str(changes["description"]).strip() != str(before.get("description") or "").strip():
            paras = [p.strip() for p in str(changes["description"]).split("\n\n") if p.strip()]
            head = " / ".join(paras[:2])[: LIMITS["description"]]       # the hook and the story: not the credits and links
            if len(head) >= 30:
                add_example(uid, "description", head, source="edit")
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------- recording what was generated
def log(kind: str, data: Dict) -> None:
    """Write down what was generated for the owner's current job. Only written, never read by the pipeline. Never raises."""
    try:
        uid = os.environ.get("CLIPSTUDIO_USER_ID") or ""
        if not uid or uid != owner_id():
            return
        LabLog(user_id=uid, kind=kind, job_id=os.environ.get("CLIPSTUDIO_JOB_ID") or "", created_at=now(), data=data).save()
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------- the pipeline's questions
def title_bonus_fn():
    """A function title -> points (or None when the titles part is off or not trained). Used by the title picker."""
    st = active("titles")
    if not st or not st.get("model"):
        return None
    model = st["model"]
    return lambda title: M.title_bonus(model, title)


def clip_bonus_fn():
    """A function lab-features -> points (or None). Used when moments are ranked."""
    st = active("clipping")
    if not st or not st.get("model"):
        return None
    model = st["model"]
    return lambda lab: M.clip_bonus(model, lab)


# ---------------------------------------------------------------------------------------------- view counts
def _api_key() -> str:
    from app.utils.envfile import read_env
    return (os.environ.get("YOUTUBE_API_KEY") or read_env().get("YOUTUBE_API_KEY") or "").strip()


def sync_views(uid) -> Dict:
    """Read the view counts of the owner's uploaded videos from YouTube (the public Data API, with the YouTube API key). Only for the lab."""
    key = _api_key()
    if not key:
        return {"ok": False, "message": "Add a YouTube Data API key in Settings -> Accounts & keys: the lab reads the view counts of your videos with it."}
    import requests
    cutoff = now() - timedelta(hours=12)
    vids = [v for v in Video.find_all(user_id=str(uid), status__in=["uploaded", "public"]) if v.get("youtube_id")
            and (not v.get("lab_views_at") or v["lab_views_at"] < cutoff)]
    got = missing = 0
    for i in range(0, len(vids), 50):
        chunk = vids[i:i + 50]
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "statistics", "id": ",".join(v["youtube_id"] for v in chunk), "key": key}, timeout=30)
            r.raise_for_status()
            stats = {it["id"]: it.get("statistics") or {} for it in r.json().get("items", [])}
        except Exception as e:
            return {"ok": False, "message": f"YouTube did not answer ({type(e).__name__}). Try again later.", "updated": got}
        for v in chunk:
            s = stats.get(v["youtube_id"])
            if s is None or "viewCount" not in s:
                missing += 1
                continue
            Video.update_where(id=v["_id"], fields={"lab_views": int(s.get("viewCount") or 0), "lab_likes": int(s.get("likeCount") or 0), "lab_views_at": now()})
            got += 1
    return {"ok": True, "updated": got, "not_found": missing, "checked": len(vids),
            "message": f"Updated the view counts of {got} video(s)." + (f" {missing} could not be read (private or removed)." if missing else "")}


# ---------------------------------------------------------------------------------------------- the data sets
def _age_days(v: Dict) -> float:
    c = v.get("created_at")
    return max(0.0, (now() - c).total_seconds() / 86400.0) if c else 0.0


def title_dataset(uid):
    X, y, titles = [], [], []
    for v in Video.find_all(user_id=str(uid), kind="short"):
        if v.get("lab_views") is None or not v.get("title"):
            continue
        age = _age_days(v)
        if age < 2.0:                                       # a new video has not had its chance yet
            continue
        X.append(M.title_features(v["title"]))
        y.append(float(analytics_service.perf(v, age)))          # views per day, moved up or down by the watch time and the stayed-to-watch share when YouTube gave them
        titles.append(M.clean_title(v["title"]))
    return (np.array(X) if X else np.zeros((0, len(M.TITLE_FEATURES)))), np.array(y), titles


def clip_dataset(uid):
    """One row per Short the owner decided on: published = 1, declined = 0. The clip's features were written down when it was found."""
    X, y = [], []
    shorts = Video.find_all(user_id=str(uid), kind="short")
    scored = sorted(analytics_service.perf(v, max(_age_days(v), 2.0)) for v in shorts if v.get("status") == "public" and v.get("analytics") and not (v.get("analytics") or {}).get("empty"))
    perf_cut = scored[len(scored) // 3] if len(scored) >= 6 else None      # the weakest third of the published videos that have results (needs 6 of them)
    for v in shorts:
        label = 1.0 if v.get("status") == "public" else 0.0 if v.get("status") in ("declined", "discarded") else None
        ids = v.get("clip_ids") or []
        if label is None or not ids:
            continue
        c = Clip.find_one(id=ids[0])
        if not c:
            continue
        if label == 1.0 and v.get("analytics") and not (v.get("analytics") or {}).get("empty") and perf_cut is not None and analytics_service.perf(v, max(_age_days(v), 2.0)) < perf_cut:
            label = 0.0                                          # it was published, but it did badly: the moments like it are not what works on this channel
        X.append(M.clip_features(M.lab_from_clip(c)))
        y.append(label)
    return (np.array(X) if X else np.zeros((0, len(M.CLIP_FEATURES)))), np.array(y)


# ---------------------------------------------------------------------------------------------- training
def _save_model(uid, part: str, model: Optional[Dict], note: str) -> None:
    LabState.set_fields(_sid(uid, part), {"user_id": str(uid), "part": part, "model": model, "n": int(model["n"]) if model else 0,
                                          "trained_at": now() if model else None, "note": note}, upsert=True)


def train(uid, part: str) -> Dict:
    if part == "titles":
        X, y, _t = title_dataset(uid)
        if len(y) < M.MIN_TITLES:
            note = f"Not enough yet: {len(y)} of the {M.MIN_TITLES} videos with view counts that are needed (videos younger than 2 days do not count)."
            _save_model(uid, part, None, note)
            return {"trained": False, "n": int(len(y)), "need": M.MIN_TITLES, "message": note}
        model = M.fit_ridge(X, y, [k for k, _ in M.TITLE_FEATURES])
        n_res = sum(1 for v in Video.find_all(user_id=str(uid), kind="short") if v.get("analytics") and not (v.get("analytics") or {}).get("empty"))
        note = f"Learned from the views per day of {len(y)} of your videos" + (f" and from how long people watched ({n_res} videos have YouTube results)." if n_res else ".")
        _save_model(uid, part, model, note)
        return {"trained": True, "n": int(len(y)), "message": note}
    if part == "clipping":
        X, y = clip_dataset(uid)
        pos, neg = int(y.sum()) if len(y) else 0, int(len(y) - y.sum()) if len(y) else 0
        if len(y) < M.MIN_CLIPS or min(pos, neg) < M.MIN_PER_CLASS:
            note = (f"Not enough yet: {pos} published and {neg} declined. It needs at least {M.MIN_CLIPS} decisions in total and "
                    f"{M.MIN_PER_CLASS} of each kind (publish the good ones, decline the weak ones).")
            _save_model(uid, part, None, note)
            return {"trained": False, "n": int(len(y)), "pos": pos, "neg": neg, "need": M.MIN_CLIPS, "message": note}
        model = M.fit_logistic(X, y, [k for k, _ in M.CLIP_FEATURES])
        note = f"Learned from {pos} published and {neg} declined videos."
        _save_model(uid, part, model, note)
        return {"trained": True, "n": int(len(y)), "pos": pos, "neg": neg, "message": note}
    raise ValueError("Descriptions have nothing to train: they learn from your examples and your edits.")


# ---------------------------------------------------------------------------------------------- what the page shows
def overview(uid) -> Dict:
    out = {"has_api_key": bool(_api_key()), "min": {"titles": M.MIN_TITLES, "clipping": M.MIN_CLIPS, "per_class": M.MIN_PER_CLASS}, "parts": {}}
    ty = [v for v in Video.find_all(user_id=str(uid), kind="short") if v.get("lab_views") is not None and _age_days(v) >= 2.0]
    decided = clip_dataset(uid)[1]
    for part in PARTS:
        st = get_state(uid, part)
        kind = "title" if part == "titles" else "description"
        d = {"on": st["on"], "trained": bool(st["model"]), "trained_at": st["trained_at"], "note": st["note"], "n": st["n"]}
        if part in ("titles", "descriptions"):
            d["examples"] = LabExample.total(user_id=str(uid), kind=kind)
            d["logged"] = LabLog.total(user_id=str(uid), kind=kind)
        if part == "titles":
            d["with_views"] = len(ty)
        if part == "clipping":
            d["published"] = int(decided.sum()) if len(decided) else 0
            d["declined"] = int(len(decided) - decided.sum()) if len(decided) else 0
        out["parts"][part] = d
    return out


def detail(uid, part: str) -> Dict:
    if part not in PARTS:
        raise ValueError("unknown part")
    st = get_state(uid, part)
    feats = M.TITLE_FEATURES if part == "titles" else M.CLIP_FEATURES
    d = {"part": part, "on": st["on"], "note": st["note"], "learned": M.explain(st["model"], feats) if part != "descriptions" else [],
         "overview": overview(uid)["parts"][part]}
    if part in ("titles", "descriptions"):
        kind = "title" if part == "titles" else "description"
        d["examples"] = [{"id": str(e["_id"]), "text": e["text"], "source": e.get("source", "owner")} for e in list_examples(uid, kind, 100)]
        recent = LabLog.find_all(user_id=str(uid), kind=kind, order=("-created_at",), limit=8)
        d["recent"] = [{"at": r["created_at"], "data": r.get("data") or {}} for r in recent]
    return d
