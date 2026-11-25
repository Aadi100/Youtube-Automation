"""Everything that sends a video to YouTube: the upload queue, publish / decline, thumbnails, approval mails."""
import re
import secrets as pysecrets
import threading
import time
from datetime import timedelta
from pathlib import Path

import requests
from mongoengine import Q

from app.models import User, UserPrefs, Video, clean, now, oid
from app.services import notification_service as notes
from app.services import token_service as tokens
from app.runtime import N8N_PUBLISH_URL, N8N_THUMB_URL, N8N_UPLOAD_URL, UPLOAD_WAKE
from app.services import auth_service as auth
from app.services import notify_service as notify
from app.services import youtube_service as youtube_api
from app.utils.envfile import studio_secret
from app.utils.paths import inside_outputs


def _next_upload():
    from collections import Counter
    from datetime import datetime, timezone
    cand = Video.find_all(Q(upload_status="queued") & (Q(retry_at__exists=False) | Q(retry_at__lte=time.time())), order=("created_at",), limit=300)
    if not cand:
        return None
    start = tokens.day_start()
    today = Counter(v.get("user_id") for v in Video.find_all(Q(uploaded_at__gte=start) | Q(upload_status="uploading"), only=("user_id",)))
    cand.sort(key=lambda v: (today.get(v.get("user_id"), 0), v["created_at"]))   # members with fewer uploads today go first
    users = {str(u["_id"]): u for u in User.find_all(id__in=[oid(x) for x in {v.get("user_id") for v in cand if v.get("user_id")}])}
    for v in cand:
        uid = v.get("user_id")
        lim = tokens.daily_limit(users.get(uid)) if uid else None
        if lim is not None and today.get(uid, 0) >= lim:     # this member's uploads for today are used up: it goes out tomorrow
            Video.update_where(id=v["_id"], fields={"upload_wait": f"Daily upload limit reached ({lim} a day): it uploads tomorrow"})
            continue
        if Video.update_where(id=v["_id"], upload_status="queued", fields={"upload_status": "uploading", "upload_started": time.time()}, unset=("upload_wait",)):
            return v
    return None


def requeue_stuck_uploads(max_age: int = 1800) -> int:
    """An upload left 'uploading' by a server that stopped goes back in the queue (its fee is returned; it is charged again when it retries)."""
    n = 0
    for v in Video.find_all(Q(upload_status="uploading") & (Q(upload_started__lt=time.time() - max_age) | Q(upload_started__exists=False))):
        tokens.refund_upload(v["_id"])
        if Video.update_where(id=v["_id"], upload_status="uploading", fields={"upload_status": "queued"}):
            n += 1
    if n:
        UPLOAD_WAKE.set()
    return n


def _do_upload(d: dict) -> None:
    privacy = d.get("upload_privacy", "unlisted")
    fee, err = tokens.charge_upload(d)      # the upload fee is taken first and returned if the upload does not finish
    if err:
        Video.update_where(id=d["_id"], fields={"upload_status": "queued", "retry_at": time.time() + 600, "upload_wait": err})
        return
    try:
        if not _direct(d):
            raise youtube_api.YTError("Connect your YouTube channel (Settings -> YouTube) and the upload continues automatically.", 401)
        yt = _direct_upload(d, privacy)
    except youtube_api.YTError as e:
        tokens.refund_upload(d["_id"])
        if e.reason == "quotaExceeded":   # wait for tomorrow's allowance
            Video.update_where(id=d["_id"], fields={"upload_status": "queued"})
            return
        tries = int(d.get("upload_tries", 0)) + 1
        if tries < 3 and e.status not in (401, 403):
            Video.update_where(id=d["_id"], fields={"upload_status": "queued", "upload_tries": tries, "retry_at": time.time() + 120 * tries, "upload_error": str(e)[:300]})
        else:
            Video.update_where(id=d["_id"], fields={"upload_status": "error", "upload_error": str(e)[:300]})
            print(f"[studio] upload failed for {d['_id']}: {e}")
            if e.status in (401, 403):
                notes.notify(d.get("user_id"), "youtube", "Reconnect your YouTube channel", "An upload failed because YouTube did not accept the saved sign-in. Connect your channel again.", "#/profile", "warn", key="ytreconnect")
            else:
                notes.notify(d.get("user_id"), "upload_problem", "An upload failed", f"{d.get('title') or 'A video'} could not be uploaded: {str(e)[:160]}", "#/videos", "error", key=f"uperr-{d['_id']}")
        return
    except Exception as e:
        tokens.refund_upload(d["_id"])
        Video.update_where(id=d["_id"], fields={"upload_status": "error", "upload_error": f"{type(e).__name__}: {str(e)[:200]}"})
        return
    doc = Video.find_one(id=d["_id"])
    _record_uploaded(doc, yt, privacy)
    tokens.record_upload(doc, fee)
    notes.notify(doc.get("user_id"), "upload_done", "Uploaded to YouTube", f"{doc.get('title') or 'Your video'} is on your channel as {privacy.title()}.", "#/videos", "success")
    print(f"[studio] uploaded {d['_id']} -> https://youtu.be/{yt} ({privacy})")
    try:
        push_thumbnail(Video.find_one(id=d["_id"]))
    except Exception as e:
        print(f"[studio] thumbnail push failed: {e}")
    if privacy != "public":
        _notify_uploaded(str(d["_id"]))


def uploader() -> None:
    while True:
        UPLOAD_WAKE.wait(20)
        UPLOAD_WAKE.clear()
        try:
            while youtube_api.can_upload():
                d = _next_upload()
                if not d:
                    break
                _do_upload(d)
        except Exception as e:
            print(f"[studio] uploader error: {e}")
            time.sleep(5)


# ------------------------------------------------- approve & publish (email link)
def _notify_uploaded(vid: str) -> None:
    """Email 'ready to check' with an Approve link. Runs in the background; sends only once per video."""
    try:
        if not notify.configured():
            return
        doc = Video.find_one(id=oid(vid))
        if not doc or doc.get("notified_at"):
            return
        token = pysecrets.token_urlsafe(24)
        Video.update_where(id=doc["_id"], fields={"approve_token": token, "approve_expires": now() + timedelta(days=14)})
        cfg = notify.get_cfg()
        base = cfg["base_url"]
        owner = User.find_one(id=oid(doc["user_id"])) if doc.get("user_id") else None
        if owner:   # the approval mail goes to the member who owns the video
            cfg["to"] = UserPrefs.of(doc["user_id"]).get("notify_to") or cfg["to"] or owner["email"]
        ok, msg = notify.uploaded_email(clean(doc) | {"thumbnail_path": doc.get("thumbnail_path")}, f"{base}/approve/{token}", cfg)
        Video.update_where(id=doc["_id"], fields={"notified_at": now() if ok else None, "notify_result": msg})
        print(f"[studio] upload email: {msg}")
    except Exception as e:
        print(f"[studio] upload email failed: {e}")


def _owners_video(doc: dict) -> bool:
    """n8n holds the OWNER's YouTube login: never use it for a member's video (it would post on the owner's channel)."""
    return doc.get("user_id") in (None, auth.owner_id())


def _direct(doc: dict) -> bool:
    """True when the video's owner has connected their own YouTube channel (we upload for them, no n8n)."""
    a = youtube_api.get_account(doc.get("user_id"))
    return bool(a) and not a.get("needs_reconnect")


def _record_uploaded(doc: dict, yt: str, privacy: str) -> None:
    pub = privacy == "public"
    Video.update_where(id=doc["_id"], unset=("approve_token", "approve_expires", "upload_error"), fields={
        "status": "public" if pub else "uploaded", "privacy_status": privacy, "youtube_id": yt, "youtube_url": f"https://youtu.be/{yt}",
        "uploaded_at": now(), "upload_status": "done", **({"published_at": now()} if pub else {})})


def _direct_upload(doc: dict, privacy: str) -> str:
    """Upload the video file to the member's channel. Raises youtube_api.YTError."""
    vp = inside_outputs(doc.get("video_path") or "")
    if not vp or not Path(vp).is_file():
        raise youtube_api.YTError("The video file is missing, so it cannot be uploaded.")
    return youtube_api.upload_video(doc["user_id"], Path(vp), doc.get("title", ""), doc.get("description", ""), doc.get("tags") or [], privacy)


def publish_video(doc: dict) -> tuple:
    """Unlisted -> Public: on the member's own channel directly, or through the owner's n8n workflow."""
    yt = doc.get("youtube_id") or ""
    if _direct(doc) and re.fullmatch(r"[\w-]{11}", yt):
        try:
            youtube_api.set_privacy(doc["user_id"], yt, "public")
        except youtube_api.YTError as e:
            return False, str(e)
        Video.update_where(id=doc["_id"], unset=("approve_token", "approve_expires"),
                           fields={"status": "public", "privacy_status": "public", "published_at": now()})
        return True, "Published - the video is now Public."
    if not _owners_video(doc):
        return False, "Connect your own YouTube channel first (Settings -> YouTube)."
    if not re.fullmatch(r"[\w-]{11}", yt):
        return False, "This video has no valid YouTube ID (it was not uploaded by the workflow)."
    try:
        r = requests.post(N8N_PUBLISH_URL, json={"youtube_id": yt}, timeout=90,
                          headers={"X-Studio-Secret": studio_secret()})
    except requests.RequestException as e:
        return False, f"Could not reach n8n ({type(e).__name__}). Is n8n running on port 5678?"
    if r.status_code == 404:
        return False, "The n8n 'Approve & publish' workflow is not active yet. Activate it in n8n (and restart n8n)."
    if r.status_code >= 400 or not re.search(r'"privacyStatus"\s*:\s*"public"', r.text):
        return False, f"YouTube did not confirm the change: {r.text[:200]}"
    Video.update_where(id=doc["_id"], unset=("approve_token", "approve_expires"),
                       fields={"status": "public", "privacy_status": "public", "published_at": now()})
    return True, "Published - the video is now Public."


REPUSH_AFTER = (240, 1500)      # seconds after the upload: set the thumbnail again when YouTube has finished processing (the first one can be replaced by an automatic frame)
REPUSH_WAIT = 300               # while YouTube is still processing: look again after this many seconds


def _schedule_repush(doc: dict) -> None:
    """Remember to set the thumbnail again soon: a thumbnail put on a video that YouTube is still processing is often replaced by an automatic frame at the end."""
    if doc.get("thumb_repush_at") or int(doc.get("thumb_repush_n") or 0) >= len(REPUSH_AFTER):
        return
    Video.update_where(id=doc["_id"], fields={"thumb_repush_at": time.time() + REPUSH_AFTER[0], "thumb_repush_n": 0, "thumb_wait_n": 0})


def repush_due() -> int:
    """Set the thumbnail again on videos whose time has come (called often by the maintenance loop; cheap when nothing is due). Returns how many were pushed."""
    ids = [v.id for v in Video.objects(__raw__={"thumb_repush_at": {"$lte": time.time(), "$ne": None}}).only("id").limit(5)]
    done = 0
    for vid in ids:
        d = Video.find_one(id=vid)
        if not d or not d.get("thumb_repush_at"):
            continue
        n, waited = int(d.get("thumb_repush_n") or 0), int(d.get("thumb_wait_n") or 0)
        claimed = Video.objects(id=d["_id"], thumb_repush_at=d["thumb_repush_at"]).update_one(set__thumb_repush_at=time.time() + 600)       # one worker takes it
        if not claimed:
            continue
        yt = d.get("youtube_id") or ""
        if not re.fullmatch(r"[\w-]{11}", yt) or d.get("status") == "discarded":
            Video.update_where(id=d["_id"], unset=("thumb_repush_at",))
            continue
        try:
            if _direct(d):
                if youtube_api.quota_left() < youtube_api.UNITS["thumbnail"] + 20:       # the day's shared pool is nearly used: try again later
                    Video.update_where(id=d["_id"], fields={"thumb_repush_at": time.time() + 3600})
                    continue
                state = youtube_api.processing_state(d["user_id"], yt)
                if state == "processing" and waited < 6:
                    Video.update_where(id=d["_id"], fields={"thumb_repush_at": time.time() + REPUSH_WAIT, "thumb_wait_n": waited + 1})
                    continue
        except Exception:
            pass
        ok, msg = push_thumbnail(Video.find_one(id=d["_id"]))
        done += 1
        n += 1
        if n < len(REPUSH_AFTER):
            Video.update_where(id=d["_id"], fields={"thumb_repush_at": time.time() + REPUSH_AFTER[n] - REPUSH_AFTER[n - 1], "thumb_repush_n": n, "thumb_wait_n": 0})
        else:
            Video.update_where(id=d["_id"], unset=("thumb_repush_at",), fields={"thumb_repush_n": n})
        print(f"[studio] thumbnail set again for {yt} ({n} of {len(REPUSH_AFTER)}): {'ok' if ok else msg[:120]}", flush=True)
    return done


def push_thumbnail(doc: dict) -> tuple:
    """Put the AI thumbnail on the video on YouTube (n8n holds the YouTube login). Safe to call more than once.
    The same thumbnail is put on again a few minutes later, when YouTube has finished processing the video."""
    yt = doc.get("youtube_id") or ""
    if re.fullmatch(r"[\w-]{11}", yt):
        try:
            _schedule_repush(doc)
        except Exception:
            pass
    if not _direct(doc) and not _owners_video(doc):
        return False, "Connect your own YouTube channel first."
    if not re.fullmatch(r"[\w-]{11}", yt):
        return False, "not on YouTube yet"
    tp = inside_outputs(doc.get("thumbnail_path") or "") if doc.get("thumbnail_path") else None
    if not tp or not Path(tp).is_file():
        return False, "no thumbnail file"
    if Path(tp).stat().st_size > 2_000_000:   # YouTube's limit is 2 MB
        try:
            from PIL import Image
            im = Image.open(tp).convert("RGB")
            im.save(tp, "JPEG", quality=82)
        except Exception:
            pass
    if _direct(doc):
        try:
            youtube_api.set_thumbnail(doc["user_id"], yt, Path(tp))
        except youtube_api.YTError as e:
            Video.update_where(id=doc["_id"], fields={"thumbnail_on_youtube": False, "thumbnail_error": str(e)[:200]})
            return False, str(e)
        Video.update_where(id=doc["_id"], fields={"thumbnail_on_youtube": True, "thumbnail_error": None})
        return True, "Thumbnail set on YouTube."
    r, last = None, ""
    for attempt in range(2):   # n8n very rarely hangs on one request: a second try almost always goes through
        try:
            r = requests.post(N8N_THUMB_URL, json={"youtube_id": yt, "thumbnail_path": str(tp)}, timeout=60,
                              headers={"X-Studio-Secret": studio_secret()})
            if r.status_code == 200 and '"ok"' in r.text:
                break
        except requests.RequestException as e:
            last = type(e).__name__
            r = None
    if r is None:
        return False, f"Could not reach n8n ({last})"
    ok = r.status_code == 200 and '"ok"' in r.text
    Video.update_where(id=doc["_id"], fields={"thumbnail_on_youtube": bool(ok), "thumbnail_error": None if ok else r.text[:200]})
    print(f"[studio] YouTube thumbnail for {yt}: {'set' if ok else 'FAILED ' + r.text[:160]}")
    if ok:
        return True, "Thumbnail set on YouTube."
    return False, ("YouTube refused (403): this channel is not allowed to set custom thumbnails yet. Verify the channel with your phone number at "
                   "youtube.com/verify, wait a few minutes, then press 'Put thumbnail on YouTube' again.")


def upload_and_publish(doc: dict, privacy: str = "public") -> tuple:
    """Rendered but never uploaded: n8n uploads it to YouTube (it holds the YouTube login). privacy: public | unlisted."""
    if _direct(doc):
        try:
            yt = _direct_upload(doc, privacy)
        except youtube_api.YTError as e:
            return False, str(e)
        _record_uploaded(doc, yt, privacy)
        threading.Thread(target=lambda: push_thumbnail(Video.find_one(id=doc["_id"])), daemon=True).start()
        return True, f"Uploaded and published: https://youtu.be/{yt}" if privacy == "public" else f"Uploaded as Unlisted: https://youtu.be/{yt}"
    if not _owners_video(doc):
        return False, "Connect your own YouTube channel first (Settings -> YouTube)."
    vp = inside_outputs(doc.get("video_path") or "")
    if not vp or not Path(vp).is_file():
        return False, "The video file is missing, so it cannot be uploaded."
    tp = inside_outputs(doc.get("thumbnail_path") or "") if doc.get("thumbnail_path") else None
    body = {"video_id": str(doc["_id"]), "title": doc.get("title", "")[:100], "description": doc.get("description", ""),
            "tags": doc.get("tags") or [], "kind": doc.get("kind", "short"), "privacy": privacy,
            "video_path": str(vp), "thumbnail_path": str(tp) if tp and Path(tp).is_file() else ""}
    try:
        r = requests.post(N8N_UPLOAD_URL, json=body, timeout=3600, headers={"X-Studio-Secret": studio_secret()})
    except requests.RequestException as e:
        return False, f"Could not reach n8n ({type(e).__name__}). Is n8n running on port 5678?"
    if r.status_code == 404:
        return False, "The n8n 'Upload & publish' workflow is not active yet. Activate it in n8n (and restart n8n)."
    try:
        data = r.json()
        data = data[0] if isinstance(data, list) and data else data
        yt = str((data or {}).get("youtube_id", ""))
    except ValueError:
        yt = ""
    if r.status_code >= 400 or not re.fullmatch(r"[\w-]{11}", yt):
        return False, f"YouTube upload did not finish: {r.text[:200]}"
    pub = privacy == "public"
    Video.update_where(id=doc["_id"], unset=("approve_token", "approve_expires"), fields={
        "status": "public" if pub else "uploaded", "privacy_status": privacy, "youtube_id": yt,
        "youtube_url": f"https://youtu.be/{yt}", "uploaded_at": now(), **({"published_at": now()} if pub else {})})
    threading.Thread(target=lambda: push_thumbnail(Video.find_one(id=doc["_id"])), daemon=True).start()
    return True, f"Uploaded and published: https://youtu.be/{yt}" if pub else f"Uploaded as Unlisted: https://youtu.be/{yt}"


def auto_upload(vid: str) -> None:
    """Every finished video goes to YouTube by itself as Unlisted, then you get the approval email."""
    try:
        doc = Video.find_one(id=oid(vid))
        if not doc or doc.get("youtube_id") or doc.get("status") != "rendered":
            return
        if _direct(doc):   # the upload queue takes it from here (it respects YouTube's daily limit and is fair between members)
            Video.update_where(id=doc["_id"], fields={"upload_status": "queued", "upload_privacy": "unlisted"})
            UPLOAD_WAKE.set()
            return
        if not _owners_video(doc):
            Video.update_where(id=doc["_id"], fields={"upload_status": "needs_youtube"})
            notes.notify(doc.get("user_id"), "youtube", "Connect your YouTube channel", "Your video is made, but it cannot be uploaded until you connect your channel. It goes up by itself once you do.", "#/profile", "warn", key="ytconnect")
            return
        ok, msg = upload_and_publish(doc, "unlisted")
        print(f"[studio] auto-upload: {msg}")
        if ok:
            _notify_uploaded(vid)
        else:
            Video.update_where(id=doc["_id"], fields={"upload_error": msg[:300]})
            if notify.configured():
                notify.failed_email("automatic YouTube upload", msg)
    except Exception as e:
        print(f"[studio] auto-upload failed: {e}")


def approve_video(doc: dict) -> tuple:
    """Approve = make it live: publish if it is already on YouTube (Unlisted), otherwise upload it as Public."""
    if doc.get("status") == "declined":
        return False, "This video was declined."
    if doc.get("youtube_id"):
        return publish_video(doc)
    if _direct(doc):
        Video.update_where(id=doc["_id"], fields={"upload_status": "queued", "upload_privacy": "public"})
        UPLOAD_WAKE.set()
        return True, "Queued: it will be uploaded and made Public as soon as a YouTube upload slot is free (usually within a minute)."
    return upload_and_publish(doc)


def decline_video(doc: dict) -> tuple:
    """Reject an uploaded video: marked declined here; it stays Unlisted (hidden) on YouTube."""
    if doc.get("status") == "public":
        return False, "This video is already Public. Make it private in YouTube Studio if you want it hidden."
    Video.update_where(id=doc["_id"], unset=("approve_token", "approve_expires"), fields={"status": "declined", "declined_at": now()})
    return True, "Declined - it stays hidden (Unlisted) on YouTube and will never be published. Delete it in YouTube Studio if you like."


def _by_token(token: str):
    return Video.find_one(approve_token=token, approve_expires__gt=now())
