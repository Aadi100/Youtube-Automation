"""YouTube: each member's connected channel, the shared daily quota counter, and short-lived OAuth state tokens."""
from mongoengine import DateTimeField, IntField, StringField

from app.models.base import Doc


class YtAccount(Doc):
    user_id = StringField(required=True)
    channel_id = StringField(required=True)
    meta = {"collection": "yt_accounts", "indexes": [{"fields": ["user_id"], "unique": True}, {"fields": ["channel_id"], "unique": True}]}


class YtQuota(Doc):
    id = StringField(primary_key=True)            # Pacific-time day
    units = IntField(default=0)
    t = DateTimeField()
    meta = {"collection": "yt_quota"}


class OAuthState(Doc):
    id = StringField(primary_key=True)
    t = DateTimeField()
    meta = {"collection": "oauth_states", "indexes": [{"fields": ["t"], "expireAfterSeconds": 900}]}
