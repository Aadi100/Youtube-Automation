"""Token ledger: every change of a member's token balance."""
from mongoengine import DateTimeField, IntField, StringField

from app.models.base import Doc


class TokenLedger(Doc):
    user_id = StringField()
    delta = IntField()
    balance = IntField()
    reason = StringField()
    ref = StringField()
    t = DateTimeField()
    meta = {"collection": "token_ledger", "indexes": [("user_id", "-t")]}
