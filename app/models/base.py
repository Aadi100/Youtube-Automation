"""Database connection and the base class of every model (MongoEngine).

Queries use MongoEngine's own keyword syntax (status__in=[..], created_at__lt=..) and Q objects; results of the `find_*` helpers come back as
plain dicts (with '_id') so views, JSON and the video pipeline can use them directly.
"""
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import mongoengine
from bson import ObjectId
from bson.errors import InvalidId
from mongoengine import DynamicDocument

from app.config import MONGODB_DB, MONGODB_URI

_connected = False


def now() -> datetime:
    return datetime.now(timezone.utc)


def connect():
    """Open the MongoEngine connection once (lazy: no network until the first query). Returns the pymongo database behind it."""
    global _connected
    if not _connected:
        mongoengine.connect(db=MONGODB_DB, host=MONGODB_URI, tz_aware=True, serverSelectionTimeoutMS=int(os.environ.get("MONGODB_TIMEOUT_MS") or 4000))   # a database on the internet (Atlas) needs longer than one on this machine
        _connected = True
    return mongoengine.connection.get_db()


def ping() -> Dict:
    try:
        info = connect().client.server_info()
        return {"ok": True, "version": info.get("version"), "database": MONGODB_DB}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "database": MONGODB_DB}


def oid(s) -> ObjectId:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        raise ValueError("invalid id")


def raw(doc) -> Optional[Dict]:
    """A model instance as the plain dict (with '_id') the rest of the code works with."""
    return doc.to_mongo().to_dict() if doc is not None else None


def clean(doc: Optional[Dict]) -> Optional[Dict]:
    """Make a document JSON-safe: _id -> id, datetimes -> ISO strings, ObjectIds -> strings."""
    if doc is None:
        return None
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, list):
            out[k] = [str(x) if isinstance(x, ObjectId) else x for x in v]
        else:
            out[k] = v
    return out


def scope_uid(uid: Optional[str] = None) -> Optional[str]:
    """The user a call is for: given explicitly, else the job's user (CLIPSTUDIO_USER_ID set by the server), else nobody (CLI / legacy)."""
    return str(uid) if uid else (os.environ.get("CLIPSTUDIO_USER_ID") or None)


def scope(uid: Optional[str] = None) -> Dict:
    u = scope_uid(uid)
    return {"user_id": u} if u else {}


class Doc(DynamicDocument):
    """Base of every model. The fields a model declares are typed (and indexed); anything else the pipeline stores is kept as it is."""
    meta = {"abstract": True, "auto_create_index": False}

    @classmethod
    def find_one(cls, *q, **kw):
        return raw(cls.objects(*q, **kw).first())

    @classmethod
    def find_all(cls, *q, order=(), skip=0, limit=0, only=(), slice_=None, **kw):
        qs = cls.objects(*q, **kw)
        if order:
            qs = qs.order_by(*order)
        if only:
            qs = qs.only(*only)
        if slice_:
            qs = qs.fields(**{f"slice__{k}": v for k, v in slice_.items()})
        if skip:
            qs = qs.skip(skip)
        if limit:
            qs = qs.limit(limit)
        return [raw(d) for d in qs]

    @classmethod
    def total(cls, *q, **kw) -> int:
        return cls.objects(*q, **kw).count()

    @classmethod
    def count_by(cls, field: str, *q, **kw) -> dict:
        """{value of field: number of documents}"""
        return {r["_id"]: r["n"] for r in cls.objects(*q, **kw).aggregate([{"$group": {"_id": f"${field}", "n": {"$sum": 1}}}])}

    @classmethod
    def update_where(cls, *q, fields=None, unset=(), upsert=False, one=True, **kw) -> int:
        """Set (and/or remove) fields on the matching document(s). Returns how many matched - 0 means nothing was there / the condition failed,
        which is how workers claim a job or a schedule slot atomically."""
        ops = {}
        if fields:
            ops["$set"] = dict(fields)
        if unset:
            ops["$unset"] = {k: "" for k in unset}
        if not ops:
            return 0
        qs = cls.objects(*q, **kw)
        return qs.update_one(upsert=upsert, __raw__=ops) if one else qs.update(upsert=upsert, __raw__=ops)

    @classmethod
    def set_fields(cls, pk, fields=None, *, unset=(), upsert=False, **more) -> int:
        return cls.update_where(id=pk, fields={**(fields or {}), **more}, unset=unset, upsert=upsert)

    @classmethod
    def remove_where(cls, *q, **kw) -> int:
        return cls.objects(*q, **kw).delete()

    @classmethod
    def take(cls, *q, **kw):
        """Atomically delete one matching document and return it (a one-time token can only be used once)."""
        return raw(cls.objects(*q, **kw).modify(remove=True))
