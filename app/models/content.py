"""Content: games, clips, videos, jobs and the claims that keep every video unique to one member."""
import re
import time as _t
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from mongoengine import BooleanField, DateTimeField, FloatField, IntField, StringField
from mongoengine.errors import NotUniqueError

from app.config import TWITCH_GAME_NAME, YOUTUBE_QUERY
from app.models.base import Doc, clean, now, oid, raw, scope, scope_uid


def _sets(fields: Dict) -> Dict:
    return {f"set__{k}": v for k, v in fields.items()}


# ---- games ---------------------------------------------------------------
class Game(Doc):
    """One doc per game you cover: where to find its clips and how to brand its videos."""
    id = StringField(primary_key=True)            # slug
    name = StringField()
    user_id = StringField()
    enabled = BooleanField(default=True)
    created_at = DateTimeField()
    last_used_at = DateTimeField()
    meta = {"collection": "games", "indexes": ["user_id"]}

    @staticmethod
    def slugify(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "game"

    @staticmethod
    def default_data() -> Dict:
        """Used when MongoDB is unavailable (CLI runs) and to seed the first game."""
        return {"id": "gta-6", "name": "GTA 6", "twitch_category": TWITCH_GAME_NAME,
                "youtube_query": YOUTUBE_QUERY, "hashtags": ["GTA6", "GrandTheftAuto6"],
                "thumb_label": "GTA 6", "enabled": True}

    @classmethod
    def ensure_default(cls) -> None:
        if cls.objects.count() == 0:
            d = cls.default_data()
            try:
                cls(id=d.pop("id"), **d, created_at=now(), last_used_at=None).save(force_insert=True)
            except NotUniqueError:   # web and worker boot together; the other one already seeded it
                pass

    @classmethod
    def list_for(cls, uid: Optional[str] = None) -> List[Dict]:
        return [clean(raw(g)) for g in cls.objects(**scope(uid)).order_by("created_at")]

    @classmethod
    def get_for(cls, game_id: str, uid: Optional[str] = None) -> Optional[Dict]:
        g = cls.objects(id=game_id, **scope(uid)).first()
        return clean(raw(g)) if g else None

    @classmethod
    def create_for(cls, fields: Dict, uid: Optional[str] = None) -> Dict:
        gid, n = cls.slugify(fields["name"]), 2
        base = gid
        while cls.objects(id=gid).first():   # game ids are unique across all members
            gid, n = f"{base}-{n}"[:40], n + 1
        cls(id=gid, **fields, user_id=scope_uid(uid), created_at=now(), last_used_at=None).save(force_insert=True)
        return cls.get_for(gid, uid)

    @classmethod
    def update_for(cls, game_id: str, fields: Dict, uid: Optional[str] = None) -> Optional[Dict]:
        n = cls.objects(id=game_id, **scope(uid)).update(**_sets(fields))
        return cls.get_for(game_id, uid) if n else None

    @classmethod
    def delete_for(cls, game_id: str, uid: Optional[str] = None) -> bool:
        return cls.objects(id=game_id, **scope(uid)).delete() > 0

    @classmethod
    def resolve(cls, game_id: Optional[str], uid: Optional[str] = None) -> Dict:
        """'auto'/None -> the enabled game used longest ago (round-robin); otherwise that exact game."""
        if game_id and game_id != "auto":
            g = cls.get_for(game_id, uid)
            if not g:
                raise ValueError(f"Game '{game_id}' not found. Add it on the Games tab.")
            return g
        enabled = [g for g in cls.list_for(uid) if g.get("enabled", True)]
        if not enabled:
            raise ValueError("No enabled games. Add or enable one on the Games tab.")
        return min(enabled, key=lambda g: g.get("last_used_at") or "")

    @classmethod
    def touch(cls, game_id: str) -> None:
        cls.objects(id=game_id).update(set__last_used_at=now())


# ---- clips ---------------------------------------------------------------
BANK_DAYS = 4   # a banked moment is used within this many days, then it is dropped (live moments go stale)


class Clip(Doc):
    id = StringField(primary_key=True)            # source clip / moment id
    user_id = StringField()
    status = StringField()                        # downloaded | banked | used | expired | rejected
    game_id = StringField()
    score = FloatField()
    created_at = DateTimeField()
    meta = {"collection": "clips", "indexes": [("user_id", "status"), "-created_at"]}

    @classmethod
    def known_ids(cls, ids: List[str]) -> set:
        return {str(c.id) for c in cls.objects(id__in=ids).only("id")}

    @classmethod
    def save_downloaded(cls, item: Dict) -> None:
        cls.objects(id=item["clip_id"]).update_one(
            upsert=True,
            set_on_insert__created_at=now(), set_on_insert__status="downloaded", set_on_insert__user_id=scope_uid(item.get("user_id")),
            **_sets({"source": item.get("source", "twitch"), "game_id": item.get("game_id"),
                     "channel_url": item.get("channel_url"), "streamer": item["streamer"], "title": item["title"], "views": item.get("views", 0),
                     "url": item.get("url"), "path": item["path"]}))

    @classmethod
    def bank(cls, item: Dict) -> None:
        """Keep a good moment for a later video. Needs clip_id, streamer, title, url, source; plus either `path` (file already cut)
        or `window` [start, end] + `src_duration` (a part of a long video that is downloaded only when it is used)."""
        cls.objects(id=item["clip_id"]).update_one(
            upsert=True, set_on_insert__created_at=now(), set_on_insert__user_id=scope_uid(item.get("user_id")),
            **_sets({"status": "banked", "source": item.get("source", "youtube"), "game_id": item.get("game_id"), "channel_url": item.get("channel_url"),
                     "streamer": item["streamer"], "title": item["title"], "views": item.get("views", 0), "url": item.get("url"),
                     "path": item.get("path"), "window": item.get("window"), "src_duration": item.get("src_duration"),
                     "duration": item.get("duration"), "score": float(item.get("score") or 0), "hook": item.get("hook", ""), "reason": item.get("reason", "")}))

    @classmethod
    def expire_banked(cls) -> int:
        """Drop banked moments older than the bank time (and delete their files)."""
        try:
            from app.engine import clipcfg
            days = clipcfg.load()["bank_days"]
        except Exception:
            days = BANK_DAYS
        cutoff = now() - timedelta(days=days)
        n = 0
        for c in list(cls.objects(status="banked", created_at__lt=cutoff)):
            try:
                if c.path:
                    Path(c.path).unlink(missing_ok=True)
            except Exception:
                pass
            cls.objects(id=c.id).update(set__status="expired")
            n += 1
        return n

    @classmethod
    def banked_for(cls, game_id: Optional[str], limit: int = 5, uid: Optional[str] = None) -> List[Dict]:
        """Best banked moments of this member for a game first (highest score)."""
        return cls.find_all(status="banked", game_id=game_id, order=("-score", "created_at"), limit=limit, **scope(uid))

    @classmethod
    def bank_size(cls, uid: Optional[str] = None) -> int:
        return cls.total(status="banked", **scope(uid))

    @classmethod
    def mark_used(cls, clip_ids: List[str], video_id: Optional[str] = None) -> None:
        if clip_ids:
            cls.objects(id__in=clip_ids).update(set__status="used", set__video_id=video_id, set__used_at=now())


# ---- videos --------------------------------------------------------------
class Video(Doc):
    user_id = StringField()
    game_id = StringField()
    kind = StringField()                          # short | compilation
    status = StringField()                        # rendered | uploaded | public | declined | discarded ...
    upload_status = StringField()
    title = StringField()
    created_at = DateTimeField()
    meta = {"collection": "videos", "indexes": [("upload_status", "created_at"), ("user_id", "-created_at"),
                                                "-created_at", "status", "game_id"]}

    @classmethod
    def save_manifest(cls, manifest: Dict, job_id: Optional[str] = None, uid: Optional[str] = None) -> str:
        """Store the video a pipeline run just made."""
        doc = {k: manifest[k] for k in ("kind", "title", "description", "tags", "video_path",
                                       "thumbnail_path", "audio_mode", "clip_ids")}
        doc.update({"game_id": manifest.get("game_id"), "game_name": manifest.get("game_name"),
                    "credits": manifest.get("credits", [])})
        doc.update({"status": "rendered", "privacy_status": manifest.get("privacy_status", "unlisted"),
                    "youtube_id": None, "twitch": {"status": "pending"},  # twitch is uploaded by hand
                    "created_at": now(), "job_id": job_id, "user_id": scope_uid(uid)})
        return str(cls(**doc).save().id)


# ---- jobs ----------------------------------------------------------------
class Job(Doc):
    user_id = StringField()
    mode = StringField()
    status = StringField()                        # queued | running | done | failed | cancelled
    worker = StringField()
    heartbeat = FloatField()
    tokens = IntField()
    created_at = DateTimeField()
    finished_at = DateTimeField()
    meta = {"collection": "jobs", "indexes": [("user_id", "-created_at"), ("status", "created_at"), "-created_at"]}

    @classmethod
    def create(cls, mode: str, params: Dict, source: str, uid: Optional[str] = None, status: str = "running") -> str:
        j = cls(mode=mode, params=params, source=source, status=status, user_id=scope_uid(uid), log=[], video_id=None, error=None,
                created_at=now(), finished_at=None).save()
        return str(j.id)

    @classmethod
    def update_fields(cls, job_id: str, **fields) -> None:
        cls.objects(id=oid(job_id)).update(**_sets(fields))

    @classmethod
    def fail_stale(cls, worker_id: Optional[str] = None) -> int:
        """Jobs left 'running' by a worker that was stopped / crashed (only that worker's jobs when worker_id is given)."""
        q = cls.objects(status="running", **({"worker": worker_id} if worker_id else {}))
        return q.update(set__status="failed", set__error="worker restarted", set__finished_at=now())

    @classmethod
    def reap_stale(cls, max_age: int = 180) -> List[str]:
        """Running jobs whose worker stopped sending heartbeats (machine lost) -> failed. Returns their ids (to refund tokens)."""
        out = []
        for j in cls.objects(status="running", heartbeat__lt=_t.time() - max_age).only("id"):
            if cls.objects(id=j.id, status="running").update(set__status="failed", set__error="worker lost", set__finished_at=now()):
                out.append(str(j.id))
        return out


# ---- unique clips: one source can only ever go to ONE member -------------------
class Claim(Doc):
    id = StringField(primary_key=True)
    user_id = StringField()
    t = DateTimeField()
    meta = {"collection": "claims", "indexes": ["t"]}

    @classmethod
    def source(cls, source_id: str, uid: Optional[str] = None) -> bool:
        """Atomically reserve a whole source (a video, a Twitch clip) for one member. False if another member already has it."""
        u = scope_uid(uid)
        try:
            cls(id=source_id, user_id=u, t=now()).save(force_insert=True)
            return True
        except NotUniqueError:
            d = cls.objects(id=source_id).first()
            return bool(d and d.user_id == u)

    @classmethod
    def release(cls, source_id: str, uid: Optional[str] = None) -> None:
        cls.objects(id=source_id, user_id=scope_uid(uid)).delete()

    @classmethod
    def window(cls, source_id: str, start: float, end: float, uid: Optional[str] = None) -> bool:
        """Reserve a stretch of a live stream (30-second buckets, all or nothing). False if any part is already someone else's."""
        u = scope_uid(uid)
        mine = []
        for b in range(int(start // 30), int(end // 30) + 1):
            key = f"{source_id}#{b}"
            try:
                cls(id=key, user_id=u, t=now()).save(force_insert=True)
                mine.append(key)
            except NotUniqueError:
                d = cls.objects(id=key).first()
                if d and d.user_id == u:
                    continue
                if mine:
                    cls.objects(id__in=mine).delete()
                return False
        return True


class ChannelRegion(Doc):
    """Cached country of a YouTube channel (so creators outside the allowed regions are skipped)."""
    id = StringField(primary_key=True)
    meta = {"collection": "channel_regions"}
