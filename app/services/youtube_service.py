"""YouTube for every member, directly (no n8n): Google sign-in, saved logins, upload, thumbnail, publish, quota.

Each member connects THEIR OWN channel through "Sign in with Google". Their refresh token is stored encrypted
(Fernet, key in .env as TOKEN_ENC_KEY) in MongoDB collection `yt_accounts`, one account per member.

Quota (resets at midnight Pacific time): uploads (videos.insert) have their OWN allowance, 100 a day by default (YT_DAILY_UPLOADS),
one unit each. Everything else (thumbnail, publish, channel read) comes from a separate pool of 10,000 units (YT_DAILY_UNITS),
50 units for a thumbnail or a publish. We count every call so uploads wait for the next day instead of failing. Raise either
number in .env after Google approves a bigger quota (check the Quotas page in Google Cloud Console for your real values).
The base URLs can be overridden with environment variables (used by the automated tests).
"""
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken

from app.models import YtAccount, YtQuota, now, raw
from app.utils.envfile import read_env, write_env

AUTH_URL = os.environ.get("GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
TOKEN_URL = os.environ.get("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
REVOKE_URL = os.environ.get("GOOGLE_REVOKE_URL", "https://oauth2.googleapis.com/revoke")
USERINFO_URL = os.environ.get("GOOGLE_USERINFO_URL", "https://openidconnect.googleapis.com/v1/userinfo")
API = os.environ.get("YT_API_BASE", "https://www.googleapis.com/youtube/v3")
UPLOAD = os.environ.get("YT_UPLOAD_BASE", "https://www.googleapis.com/upload/youtube/v3")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube", "openid", "email"]
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"      # asked for separately, only when a member chooses to let the studio learn from their results
UNITS = {"thumbnail": 50, "update": 50, "list": 1}     # the shared pool; uploads are counted separately (daily_uploads)
CHUNK = 8 * 1024 * 1024   # multiple of 256 KB, as the resumable protocol requires


class YTError(Exception):
    def __init__(self, message: str, status: int = 0, reason: str = ""):
        super().__init__(message)
        self.status, self.reason = status, reason


# ---------------------------------------------------------------- settings / encryption
def client() -> tuple:
    e = read_env()
    return (e.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID") or "",
            e.get("GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET") or "")


def configured() -> bool:
    cid, sec = client()
    return bool(cid and sec)


def _fernet() -> Fernet:
    e = read_env()
    if not e.get("TOKEN_ENC_KEY"):
        write_env({"TOKEN_ENC_KEY": Fernet.generate_key().decode()})
        e = read_env()
    return Fernet(e["TOKEN_ENC_KEY"].encode())


def _enc(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def _dec(s: str) -> str:
    try:
        return _fernet().decrypt(s.encode()).decode()
    except InvalidToken:
        raise YTError("The saved YouTube login cannot be read (the encryption key changed). Connect the channel again.")


# ---------------------------------------------------------------- quota
def _pacific_day() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        return (datetime.utcnow() - timedelta(hours=8)).strftime("%Y-%m-%d")


def daily_units() -> int:
    return int(read_env().get("YT_DAILY_UNITS") or os.environ.get("YT_DAILY_UNITS") or 10000)


def daily_uploads() -> int:
    try:
        return max(1, int(read_env().get("YT_DAILY_UPLOADS") or os.environ.get("YT_DAILY_UPLOADS") or 100))
    except ValueError:
        return 100


def uploads_used() -> int:
    d = YtQuota.objects(id=_pacific_day()).first()
    return int(d.uploads or 0) if d else 0


def uploads_left() -> int:
    return max(0, daily_uploads() - uploads_used())


def quota_used() -> int:
    d = YtQuota.objects(id=_pacific_day()).first()
    return int(d.units or 0) if d else 0


def quota_left() -> int:
    return max(0, daily_units() - quota_used())


def quota_use(units: int) -> None:
    YtQuota.objects(id=_pacific_day()).update_one(upsert=True, inc__units=units, set_on_insert__t=now())


def quota_exhausted_today(uploads: bool = False) -> None:
    """Google said no: mark the upload allowance (uploads=True) or the shared pool as used up for today."""
    if uploads:
        YtQuota.objects(id=_pacific_day()).update_one(upsert=True, set__uploads=daily_uploads())
    else:
        YtQuota.objects(id=_pacific_day()).update_one(upsert=True, set__units=daily_units())


def can_upload() -> bool:
    return uploads_left() >= 1 and quota_left() >= UNITS["thumbnail"] + UNITS["update"]


# ---------------------------------------------------------------- sign in with Google
def auth_url(redirect_uri: str, state: str, scopes=None) -> str:
    cid, _ = client()
    return AUTH_URL + "?" + urlencode({"client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(scopes or SCOPES),
                                       "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state})


def _token_request(data: Dict) -> Dict:
    cid, sec = client()
    r = requests.post(TOKEN_URL, data={**data, "client_id": cid, "client_secret": sec}, timeout=30)
    if r.status_code != 200:
        raise YTError(f"Google refused the login ({r.status_code}): {r.text[:200]}", r.status_code)
    return r.json()


def exchange_code(code: str, redirect_uri: str) -> Dict:
    return _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})


def _channel(access: str) -> Dict:
    r = requests.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, headers={"Authorization": f"Bearer {access}"}, timeout=30)
    quota_use(UNITS["list"])
    if r.status_code != 200:
        raise YTError(f"Could not read your channel ({r.status_code}): {r.text[:200]}", r.status_code)
    items = r.json().get("items") or []
    if not items:
        raise YTError("This Google account has no YouTube channel. Create one at youtube.com first, then connect again.")
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}


def save_account(user_id: str, tokens: Dict) -> Dict:
    if not tokens.get("refresh_token"):
        raise YTError("Google did not return a long-lived login. Remove the app at myaccount.google.com/permissions and connect again.")
    ch = _channel(tokens["access_token"])
    email = ""
    try:
        email = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=20).json().get("email", "")
    except Exception:
        pass
    # one channel can belong to only one member
    other = YtAccount.objects(channel_id=ch["id"], user_id__ne=str(user_id)).first()
    if other:
        raise YTError("This YouTube channel is already connected to another account.")
    doc = {"user_id": str(user_id), "channel_id": ch["id"], "channel_title": ch["title"], "email": email,
           "refresh_enc": _enc(tokens["refresh_token"]), "access_token": tokens["access_token"],
           "expires_at": time.time() + int(tokens.get("expires_in", 3600)) - 60, "connected_at": now(), "scopes": str(tokens.get("scope") or "")}
    YtAccount.objects(user_id=str(user_id)).update_one(upsert=True, **{f"set__{k}": v for k, v in doc.items()})
    return {"channel_id": ch["id"], "channel_title": ch["title"], "email": email}


def get_account(user_id) -> Optional[Dict]:
    return raw(YtAccount.objects(user_id=str(user_id)).first()) if user_id else None


def has_analytics(user_id) -> bool:
    """Has this member allowed the studio to read their YouTube Analytics?"""
    a = get_account(user_id)
    return bool(a and ANALYTICS_SCOPE in str(a.get("scopes") or ""))


def public_status(user_id) -> Dict:
    a = get_account(user_id)
    return {"configured": configured(), "connected": bool(a), "analytics": has_analytics(user_id), "channel_title": a.get("channel_title") if a else None,
            "channel_id": a.get("channel_id") if a else None, "email": a.get("email") if a else None}


def disconnect(user_id: str) -> None:
    a = get_account(user_id)
    if not a:
        return
    try:
        requests.post(REVOKE_URL, data={"token": _dec(a["refresh_enc"])}, timeout=15)
    except Exception:
        pass
    YtAccount.objects(user_id=str(user_id)).delete()


def access_token(user_id) -> str:
    a = get_account(user_id)
    if not a:
        raise YTError("Connect your YouTube channel first (Settings -> YouTube).")
    if a.get("access_token") and a.get("expires_at", 0) > time.time():
        return a["access_token"]
    try:
        t = _token_request({"grant_type": "refresh_token", "refresh_token": _dec(a["refresh_enc"])})
    except YTError as e:
        if e.status in (400, 401):   # the member revoked access (or the token expired): they must connect again
            YtAccount.objects(id=a["_id"]).update(set__needs_reconnect=True)
            from app.services import notification_service as notes
            notes.notify(a["_id"], "youtube", "Reconnect your YouTube channel", "YouTube access was removed or expired, so uploads are paused. Connect your channel again.", "#/profile", "warn", key="ytreconnect")
            raise YTError("YouTube access was removed or expired. Connect your channel again (Settings -> YouTube).", e.status)
        raise
    YtAccount.objects(id=a["_id"]).update(set__access_token=t["access_token"], set__expires_at=time.time() + int(t.get("expires_in", 3600)) - 60,
                                          set__needs_reconnect=False)
    return t["access_token"]


# ---------------------------------------------------------------- calls
def _raise(r: requests.Response, what: str) -> None:
    reason = ""
    try:
        reason = ((r.json().get("error") or {}).get("errors") or [{}])[0].get("reason", "")
    except Exception:
        pass
    if r.status_code == 403 and reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
        quota_exhausted_today(uploads=what.startswith("upload"))
        raise YTError("YouTube's daily upload limit is used up. It will continue tomorrow.", 403, "quotaExceeded")
    if r.status_code == 403 and "thumbnail" in what:
        raise YTError("This channel is not allowed to set custom thumbnails yet. Verify it at youtube.com/verify.", 403, reason)
    raise YTError(f"YouTube {what} failed ({r.status_code}): {r.text[:200]}", r.status_code, reason)


def _clean(title: str, description: str, tags: List[str]) -> tuple:
    t = " ".join((title or "Video").replace("<", "").replace(">", "").split())[:100] or "Video"
    d = (description or "").replace("<", "").replace(">", "")[:4900]
    out, total = [], 0
    for x in tags or []:
        x = str(x).replace("<", "").replace(">", "").strip()
        if x and total + len(x) + 1 <= 450:
            out.append(x)
            total += len(x) + 1
    return t, d, out


def upload_video(user_id, path: Path, title: str, description: str, tags: List[str], privacy: str = "unlisted", synthetic: bool = False) -> str:
    """Resumable upload. Returns the YouTube video id."""
    if not can_upload():
        raise YTError("YouTube's daily upload limit is used up. It will continue tomorrow.", 403, "quotaExceeded")
    token = access_token(user_id)
    path = Path(path)
    total = path.stat().st_size
    t, d, tg = _clean(title, description, tags)
    meta = {"snippet": {"title": t, "description": d, "tags": tg, "categoryId": "20"},
            "status": {"privacyStatus": privacy if privacy in ("public", "unlisted", "private") else "unlisted",
                       "selfDeclaredMadeForKids": False, "embeddable": True, "publicStatsViewable": True, **({"containsSyntheticMedia": True} if synthetic else {})}}
    r = requests.post(f"{UPLOAD}/videos", params={"uploadType": "resumable", "part": "snippet,status"}, json=meta, timeout=60,
                      headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(total), "X-Upload-Content-Type": "video/mp4"})
    if r.status_code != 200 or not r.headers.get("Location"):
        _raise(r, "upload start")
    session_url = r.headers["Location"]
    YtQuota.objects(id=_pacific_day()).update_one(upsert=True, inc__uploads=1, set_on_insert__t=now())
    sent, retries = 0, 0
    with open(path, "rb") as f:
        while True:
            f.seek(sent)
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            try:
                rr = requests.put(session_url, data=chunk, timeout=300,
                                  headers={"Content-Length": str(len(chunk)), "Content-Type": "video/mp4",
                                           "Content-Range": f"bytes {sent}-{end}/{total}"})
            except requests.RequestException:
                rr = None
            if rr is not None and rr.status_code in (200, 201):
                vid = rr.json().get("id")
                if not vid:
                    raise YTError("YouTube accepted the file but returned no video id.")
                return vid
            if rr is not None and rr.status_code == 308:
                rng = rr.headers.get("Range", "")
                sent = int(rng.split("-")[-1]) + 1 if rng else sent + len(chunk)
                retries = 0
                continue
            retries += 1                      # network error or 5xx: ask how much arrived, then continue from there
            if retries > 6 or (rr is not None and rr.status_code in (400, 401, 403, 404)):
                _raise(rr, "upload") if rr is not None else (_ for _ in ()).throw(YTError("The upload connection kept failing."))
            time.sleep(min(2 ** retries, 30))
            try:
                q = requests.put(session_url, headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"}, timeout=60)
                if q.status_code in (200, 201) and q.json().get("id"):
                    return q.json()["id"]
                if q.status_code == 308 and q.headers.get("Range"):
                    sent = int(q.headers["Range"].split("-")[-1]) + 1
                elif q.status_code == 308:
                    sent = 0
            except requests.RequestException:
                pass


def processing_state(user_id, video_id: str) -> str:
    """Has YouTube finished processing the upload? 'ready', 'processing', 'failed' or 'unknown'. A thumbnail set while the video is still processing can be replaced
    by an automatic frame when the processing ends, so the studio sets it again once the video is ready. Costs 1 unit of the shared pool."""
    try:
        token = access_token(user_id)
        r = requests.get(f"{API}/videos", params={"part": "status,processingDetails", "id": video_id}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code != 200:
            return "unknown"
        quota_use(UNITS["list"])
        items = r.json().get("items") or []
        if not items:
            return "unknown"
        st = (items[0].get("status") or {}).get("uploadStatus", "")
        pd = (items[0].get("processingDetails") or {}).get("processingStatus", "")
        if st in ("failed", "rejected") or pd == "failed":
            return "failed"
        if st == "processed" and pd in ("", "succeeded"):
            return "ready"
        return "processing"
    except Exception:
        return "unknown"


def set_thumbnail(user_id, video_id: str, image: Path) -> None:
    token = access_token(user_id)
    r = requests.post(f"{UPLOAD}/thumbnails/set", params={"videoId": video_id, "uploadType": "media"}, data=Path(image).read_bytes(), timeout=120,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"})
    if r.status_code != 200:
        _raise(r, "thumbnail")
    quota_use(UNITS["thumbnail"])


def set_privacy(user_id, video_id: str, privacy: str, synthetic: bool = False) -> None:
    token = access_token(user_id)
    body = {"id": video_id, "status": {"privacyStatus": privacy, "embeddable": True, "publicStatsViewable": True, "license": "youtube",
                                       "selfDeclaredMadeForKids": False, **({"containsSyntheticMedia": True} if synthetic else {})}}
    r = requests.put(f"{API}/videos", params={"part": "status"}, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if r.status_code != 200:
        _raise(r, "publish")
    quota_use(UNITS["update"])
    if (r.json().get("status") or {}).get("privacyStatus") != privacy:
        raise YTError("YouTube did not confirm the change.")
