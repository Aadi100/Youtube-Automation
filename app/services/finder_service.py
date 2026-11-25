"""The clip finder: scan a stream, replay or video, show the member every good moment found, and process only the ones they pick.

A scan finds up to 10 candidates per pass. For long sources a pass covers 45 minutes; "scan more" moves on to the next 45.
Nothing here costs tokens (see app/engine/finder.py). The expensive steps (commentary, voice, thumbnail) only run for picked clips.
"""
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

from app.config import BASE_DIR, OUTPUT_DIR
from app.engine import clipcfg
from app.engine import discovery as D
from app.engine import finder as F
from app.models import EditSource, Scan, now, oid
from app.services import editor_service as ed
from app.services import notification_service as notes

PASS_SECONDS = 45 * 60
MAX_CANDIDATES = 10
KEEP_SCANS = 6
KEEP_HOURS = 72
_SCAN = threading.Semaphore(1)                    # one scan at a time: they use the network and the CPU of the shared server


def folder(uid, sid) -> Path:
    d = OUTPUT_DIR / "finder" / str(uid) / str(sid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_url(url: str) -> bool:
    url = (url or "").strip()
    return len(url) <= 300 and bool(ed.LINK_RE.match(url) or F.is_channel_url(url))


# ---------------------------------------------------------------- what the browser sees
def cview(sid: str, c: Dict) -> Dict:
    return {"id": c["id"], "start": c["start"], "end": c["end"], "length": round(c["end"] - c["start"]), "score": c["score"], "reasons": c.get("reasons") or [],
            "ready": bool(c.get("ready")), "video": f"/api/finder/scans/{sid}/c/{c['id']}/video", "thumb": f"/api/finder/scans/{sid}/c/{c['id']}/thumb" if c.get("has_thumb") else None}


def view(doc: Dict) -> Dict:
    sid = str(doc["_id"])
    cands = [c for c in (doc.get("candidates") or []) if not c.get("flagged")]
    return {"id": sid, "title": doc.get("title"), "creator": doc.get("creator"), "platform": doc.get("platform"), "kind": doc.get("kind"), "live": bool(doc.get("live")),
            "status": doc.get("status"), "message": doc.get("message") or "", "pct": int(doc.get("pct") or 0), "duration": doc.get("duration"), "window": doc.get("window"),
            "next_start": doc.get("next_start"), "more": bool(doc.get("more")), "hidden": sum(1 for c in (doc.get("candidates") or []) if c.get("flagged")),
            "candidates": [cview(sid, c) for c in sorted(cands, key=lambda c: -c["score"])], "created_at": doc["created_at"].replace(tzinfo=None).isoformat() + "Z" if doc.get("created_at") else None,
            "url": doc.get("url"), "note": doc.get("note") or ""}


def get_scan(uid, sid: str, is_owner: bool = False) -> Optional[Dict]:
    try:
        doc = Scan.find_one(id=oid(sid))
    except ValueError:
        return None
    return doc if doc and (doc.get("user_id") == str(uid) or is_owner) else None


def list_scans(uid) -> List[Dict]:
    return [{"id": str(d["_id"]), "title": d.get("title"), "creator": d.get("creator"), "status": d.get("status"), "kind": d.get("kind"),
             "count": sum(1 for c in (d.get("candidates") or []) if not c.get("flagged")), "created_at": d["created_at"].replace(tzinfo=None).isoformat() + "Z"}
            for d in Scan.find_all(user_id=str(uid), order=("-created_at",), limit=KEEP_SCANS)]


def delete_scan(uid, sid: str) -> bool:
    d = get_scan(uid, sid)
    if not d:
        return False
    shutil.rmtree(OUTPUT_DIR / "finder" / str(uid) / sid, ignore_errors=True)
    Scan.objects(id=d["_id"]).delete()
    return True


def _prune(uid) -> None:
    docs = Scan.find_all(user_id=str(uid), order=("-created_at",))
    for i, d in enumerate(docs):
        old = d.get("created_at") and (now() - d["created_at"].replace(tzinfo=now().tzinfo)).total_seconds() > KEEP_HOURS * 3600
        if i >= KEEP_SCANS or old:
            shutil.rmtree(OUTPUT_DIR / "finder" / str(uid) / str(d["_id"]), ignore_errors=True)
            Scan.objects(id=d["_id"]).delete()


# ---------------------------------------------------------------- scanning
def _set(sid, **f) -> None:
    Scan.objects(id=oid(str(sid))).update(**{f"set__{k}": v for k, v in f.items()})


def start_scan(uid, url: str, start=None, end=None, safety_on: bool = True) -> str:
    url = (url or "").strip()
    if not valid_url(url):
        raise ValueError("Paste a link to a YouTube, Twitch or Kick video, a stream replay or a live stream.")
    a, b = (ed._parse_time(start), ed._parse_time(end)) if (start or end) else (None, None)
    if a is not None and b and b - a < 60:
        raise ValueError("Choose a part at least a minute long.")
    if Scan.total(user_id=str(uid), status="running"):
        raise ValueError("A scan is already running. Wait for it to finish.")
    from app.services import token_service as tokens
    why = tokens.small_shortfall(uid, "finder_scan")
    if why:
        raise ValueError(why)
    _prune(uid)
    doc = Scan(user_id=str(uid), title="Scanning…", url=url, kind="vod", status="running", created_at=now(), pct=2, message="Starting…", candidates=[]).save()
    threading.Thread(target=_run, args=(str(uid), str(doc.id), url, a, b, safety_on, False), daemon=True).start()
    return str(doc.id)


def scan_more(uid, sid: str, safety_on: bool = True) -> str:
    d = get_scan(uid, sid)
    if not d:
        raise ValueError("That scan is not available any more.")
    if d.get("status") == "running" or Scan.total(user_id=str(uid), status="running"):
        raise ValueError("A scan is already running. Wait for it to finish.")
    if not d.get("more"):
        raise ValueError("There is nothing more to scan in this source.")
    from app.services import token_service as tokens
    why = tokens.small_shortfall(uid, "finder_scan")
    if why:
        raise ValueError(why)
    a = float(d.get("next_start") or 0)
    _set(sid, status="running", pct=2, message="Scanning the next part…")
    threading.Thread(target=_run, args=(str(uid), sid, d["url"], a, None, safety_on, True), daemon=True).start()
    return sid


def _run(uid: str, sid: str, url: str, a: Optional[float], b: Optional[float], safety_on: bool, more: bool) -> None:
    try:
        with _SCAN:
            _scan(uid, sid, url, a, b, safety_on, more)
    except ValueError as e:
        _set(sid, status="error", message=str(e)[:300])
    except Exception as e:
        _set(sid, status="error", message=f"Something went wrong: {type(e).__name__}: {str(e)[:200]}")


def _scan(uid: str, sid: str, url: str, a: Optional[float], b: Optional[float], safety_on: bool, more: bool) -> None:
    from app.engine import safety
    fold = folder(uid, sid)
    doc = Scan.find_one(id=oid(sid))
    before, after = clipcfg.span()
    _set(sid, message="Reading the link…", pct=4)
    src_url = url
    if F.is_channel_url(url):                                # a streamer's live page
        if F.platform_of(url) == "twitch":
            vod = F.twitch_current_vod(url.rstrip("/").rsplit("/", 1)[-1])
            if vod:
                src_url = vod
        if src_url == url:
            info = F.probe_url(url)                          # not a Twitch replay: read the live stream itself (raises when it is offline)
        else:
            info = F.probe_url(src_url)
            info["live"] = True
    else:
        info = F.probe_url(url)
    if safety_on and info["age_limit"] >= 18:
        raise ValueError("That video is age-restricted, so it cannot be used.")
    live_rec = info["live"] and src_url == url               # YouTube / Kick live: read back what the stream keeps
    kind = "live" if live_rec else "vod"
    fields = dict(title=info["title"][:140], creator=info["creator"], channel_url=info["channel_url"], platform=info["platform"], kind=kind, live=bool(info["live"]),
                  source_id=info["id"], page_url=info["url"], scan_url=src_url)
    found: List[Dict] = []
    if live_rec:
        _set(sid, message="Reading back the live stream…", pct=10, **fields)
        rec = fold / "live.ts"
        secs = F.record_back(src_url, rec)
        _set(sid, message="Listening for the best moments…", pct=45, duration=secs, window=[0, secs], more=False, note="Live stream: only the part the platform still keeps could be read.")
        found = F.sound_moments(rec, MAX_CANDIDATES + 4)
        media = rec
        base = 0.0
    else:
        dur = info["duration"] or 0
        if not dur:
            raise ValueError("That stream has no replay to read, so only its live picture exists. Try again later, or open a past stream.")
        if a is None:
            a = 0.0
        end_ = min(dur, (b if b else a + PASS_SECONDS))
        _set(sid, message="Checking what viewers replayed…", pct=10, duration=dur, window=[a, end_], **fields)
        if info["heatmap"] and not more:
            found += F.heat_moments(info, MAX_CANDIDATES)
        if end_ - a >= before + after + 15:
            _set(sid, message="Listening to the sound of this part…", pct=20)
            audio = F.download_audio(src_url, (a, end_), fold / "audio")
            _set(sid, message="Listening for the best moments…", pct=45)
            found += F.sound_moments(audio, MAX_CANDIDATES + 4, offset=a)
            audio.unlink(missing_ok=True)
        media, base = None, a
        _set(sid, more=end_ < dur - 120, next_start=end_)
        if (b is not None) or end_ >= dur - 120:
            _set(sid, more=False)
    old = [c for c in (doc.get("candidates") or [])] if more else []
    taken = {c["id"] for c in old}
    n0 = len(old)
    cands = []
    for i, c in enumerate(F.merge(found, MAX_CANDIDATES)):
        c = {**c, "id": f"c{n0 + i + 1}", "ready": False, "flagged": False}
        if any(abs(o["start"] - c["start"]) < 25 for o in old):
            continue
        cands.append(c)
    if not cands:
        _set(sid, status="done", pct=100, message="No clear highlights found in this part." + (" Try scanning the next part." if Scan.find_one(id=oid(sid)).get("more") else ""), candidates=old)
        return
    _set(sid, candidates=old + cands, message=f"Found {len(cands)} moments. Cutting previews…", pct=55)
    # previews: small copies you can play right here (two at a time)
    def one(c):
        out = fold / f"{c['id']}.mp4"
        try:
            if media:
                F.cut_preview(media, c["start"], c["end"], out)
            else:
                F.download_preview(src_url, c["start"], c["end"], out)
            c["ready"] = True
            if F.thumbnail(out, fold / f"{c['id']}.jpg"):
                c["has_thumb"] = True
            if safety_on:                                    # the free local detector hides clips that would be blocked later
                try:
                    ok, _why = (lambda r: (r[0] is not False, r[1]))(safety.review_locally(out))
                    if not ok:
                        c["flagged"] = True
                except Exception:
                    pass
        except Exception as e:
            c["flagged"] = True
            c["error"] = str(e)[:120]
        return c
    done = 0
    with ThreadPoolExecutor(2) as pool:
        for c in pool.map(one, cands):
            done += 1
            allc = old + cands
            _set(sid, candidates=allc, pct=55 + int(40 * done / len(cands)), message=f"Previews ready: {done} of {len(cands)}")
    ok_n = sum(1 for c in cands if c.get("ready") and not c.get("flagged"))
    from app.services import token_service as tokens
    tokens.charge_action(uid, "finder_scan", ref=sid)          # a scan that found moments is paid for; one that found nothing is free
    _set(sid, status="done", pct=100, message=f"{ok_n} moment{'s' if ok_n != 1 else ''} ready to choose.", candidates=old + cands)
    notes.notify(uid, "editor", "Your clip finder is done", f"{ok_n} moments found in {info['title'][:60]}. Open the Editor to choose.", "#/editor", "success", key=f"scan-{sid}")


# ---------------------------------------------------------------- picking
def candidate(doc: Dict, cid: str) -> Optional[Dict]:
    return next((c for c in (doc.get("candidates") or []) if c["id"] == cid and not c.get("flagged")), None)


def file_of(uid, sid: str, cid: str, what: str) -> Optional[Path]:
    p = folder(uid, sid) / f"{cid}.{'mp4' if what == 'video' else 'jpg'}"
    return p if p.is_file() else None


def _materialize(uid: str, doc: Dict, c: Dict, dest: Path) -> Path:
    """The chosen moment at full quality in its own file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if doc.get("kind") == "live":
        F.cut_full(folder(uid, str(doc["_id"])) / "live.ts", c["start"], c["end"], dest)
    else:
        D._fetch(doc.get("scan_url") or doc["url"], "finder", (c["start"], c["end"]), float(doc.get("duration") or 0), dest)
    if not dest.is_file():
        raise ValueError("Could not cut that moment.")
    return dest


def _credit(doc: Dict) -> Dict:
    return {"creator": doc.get("creator"), "title": doc.get("title"), "platform": doc.get("platform"), "video_url": doc.get("page_url") or doc.get("url"),
            "channel_url": doc.get("channel_url")}


def pick_editor(uid, sid: str, cids: List[str]) -> List[str]:
    """Open the chosen clips in the editor (each becomes an item in 'Open again'). Returns task ids."""
    doc = get_scan(uid, sid)
    if not doc:
        raise ValueError("That scan is not available any more.")
    chosen = [candidate(doc, c) for c in cids[:6]]
    if not chosen or any(c is None for c in chosen):
        raise ValueError("Choose at least one moment.")
    tasks = []
    for c in chosen:
        def work(report, c=c):
            report(10, "Cutting the moment…")
            out = ed.src_dir(uid) / f"find_{secrets.token_hex(5)}.mp4"
            _materialize(str(uid), doc, c, out)
            report(85, "Preparing…")
            title = f"{doc.get('title') or 'Moment'} ({int(c['start'] // 60)}:{int(c['start'] % 60):02d})"
            return {"source": ed._add(uid, title, out, "link", ed.editor.probe(out), credit=_credit(doc))}
        tasks.append(ed.start_task(uid, "download", work, ed._DOWNLOAD))
    return tasks


def pick_short(uid, sid: str, cids: List[str], audio_mode: str, after: str) -> List[str]:
    """Make an AI video (commentary, captions, thumbnail) from each chosen moment. Returns task ids; each task result holds the job id."""
    from app.services.queue_service import enqueue
    doc = get_scan(uid, sid)
    if not doc:
        raise ValueError("That scan is not available any more.")
    chosen = [candidate(doc, c) for c in cids[:5]]
    if not chosen or any(c is None for c in chosen):
        raise ValueError("Choose at least one moment.")
    if audio_mode not in ("replace", "bed", "original", "default"):
        audio_mode = "default"
    tasks = []
    for c in chosen:
        length = c["end"] - c["start"]
        if length > 58:
            raise ValueError("A Short can be at most 58 seconds. Use the editor for longer clips.")

        def work(report, c=c):
            report(10, "Cutting the moment…")
            out = BASE_DIR / "inputs" / str(uid) / "finder" / f"{sid}_{c['id']}_{secrets.token_hex(3)}.mp4"
            _materialize(str(uid), doc, c, out)
            report(80, "Starting your video…")
            bucket = f"fc_{doc.get('platform')}_{doc.get('source_id') or sid}_{int(c['start'] // 20)}"
            meta = {"streamer": doc.get("creator"), "title": doc.get("title"), "url": doc.get("page_url") or doc.get("url"), "channel_url": doc.get("channel_url"),
                    "source": doc.get("platform"), "claim": bucket}
            params = {"audio_mode": audio_mode if audio_mode != "default" else _default_audio(uid), "source": "youtube", "game_id": "auto", "diy": {"own_file": str(out), "own_meta": meta}}
            if after in ("auto", "hold"):
                params["after"] = after
            jid, err = enqueue("auto-short", params, "dashboard", uid)
            if jid is None:
                out.unlink(missing_ok=True)
                raise ValueError(err)
            return {"job_id": jid}
        tasks.append(ed.start_task(uid, "download", work, ed._DOWNLOAD))
    return tasks


def _default_audio(uid) -> str:
    from app.controllers.job_controller import default_audio
    return default_audio(uid)
