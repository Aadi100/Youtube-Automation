"""Models (the M of MVC): every collection as a MongoEngine document, plus the database helpers.

    from app.models import User, Video, Job, now, oid
"""
from app.models.accounts import AuthAttempt, Session, User, UserPrefs
from app.models.base import Doc, clean, connect, now, oid, ping, raw, scope, scope_uid
from app.models.billing import TokenLedger
from app.models.content import BANK_DAYS, Claim, ChannelRegion, Clip, Game, Job, Video
from app.models.system import Setting, System
from app.models.youtube import OAuthState, YtAccount, YtQuota

ALL = [User, Session, AuthAttempt, UserPrefs, Setting, System, Game, Clip, Video, Job, Claim, ChannelRegion,
       TokenLedger, YtAccount, YtQuota, OAuthState]


def create_indexes() -> None:
    """Create the indexes of every model (explicitly at start-up, never lazily on first use)."""
    connect()
    for m in ALL:
        m.ensure_indexes()


def migrate_legacy(owner_id: str) -> None:
    """Everything made before accounts existed belongs to the owner."""
    connect()
    for M in (Game, Clip, Video, Job):
        M.update_where(user_id__exists=False, fields={"user_id": owner_id}, one=False)
    for name in ("clipping", "schedule"):
        old = Setting.find_one(id=name)
        if old and not Setting.find_one(id=f"{name}:{owner_id}"):
            old.pop("_id")
            Setting(id=f"{name}:{owner_id}", **old).save(force_insert=True)
        Setting.remove_where(id=name)


connect()   # open the MongoEngine connection (lazy: no network until the first query)
