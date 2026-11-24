"""Accounts: users, login sessions, failed-login log, per-user preferences."""
from mongoengine import BooleanField, DateTimeField, IntField, ObjectIdField, StringField

from app.models.base import Doc


class User(Doc):
    email = StringField(required=True)
    name = StringField()
    pw_hash = StringField()
    role = StringField(default="member")          # owner | member
    status = StringField(default="active")        # active | pending | disabled
    tokens = IntField(default=0)
    upload_limit = IntField()                     # uploads per day set by the owner for this member (empty = the default for everybody)
    created_at = DateTimeField()
    last_login = DateTimeField()
    meta = {"collection": "users", "indexes": [{"fields": ["email"], "unique": True}]}


class Session(Doc):
    id = StringField(primary_key=True)            # sha256 of the cookie token (the token itself is never stored)
    user_id = ObjectIdField()
    created_at = DateTimeField()
    expires_at = DateTimeField()
    meta = {"collection": "sessions", "indexes": [{"fields": ["expires_at"], "expireAfterSeconds": 0}]}


class AuthAttempt(Doc):
    key = StringField()
    t = DateTimeField()
    meta = {"collection": "auth_attempts", "indexes": ["key", {"fields": ["t"], "expireAfterSeconds": 900}]}


class UserPrefs(Doc):
    id = StringField(primary_key=True)            # user id
    meta = {"collection": "user_prefs"}

    @classmethod
    def of(cls, uid) -> dict:
        """The preferences of one user ({} when there are none)."""
        return (cls.find_one(id=str(uid)) or {}) if uid else {}


class Notification(Doc):
    """One message in a member's bell: what happened, a link to where to look, and whether it was read."""
    user_id = StringField()
    kind = StringField()
    title = StringField()
    body = StringField()
    link = StringField()
    level = StringField(default="info")           # info | success | warn | error
    key = StringField()                           # the same problem is shown once, not every few minutes
    read = BooleanField(default=False)
    created_at = DateTimeField()
    meta = {"collection": "notifications", "indexes": [("user_id", "-created_at"), ("user_id", "read"),
                                                       {"fields": ["created_at"], "expireAfterSeconds": 60 * 86400}]}
