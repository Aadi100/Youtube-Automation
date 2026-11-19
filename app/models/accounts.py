"""Accounts: users, login sessions, failed-login log, per-user preferences."""
from mongoengine import DateTimeField, IntField, ObjectIdField, StringField

from app.models.base import Doc


class User(Doc):
    email = StringField(required=True)
    name = StringField()
    pw_hash = StringField()
    role = StringField(default="member")          # owner | member
    status = StringField(default="active")        # active | pending | disabled
    tokens = IntField(default=0)
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
