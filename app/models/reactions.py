"""Models for the Reaction Lab (beta). Nothing outside the lab reads these collections.

RxScan   one analysis of a video / replay: its reaction map and the moments found (each with its signals).
RxLabel  one judgment of the member (good reaction / not good). Kept even when the scan is deleted: it is the training data.
RxModel  what the lab has learned from the labels (one general model, and one per kind of reaction once there are enough labels).
"""
from mongoengine import DateTimeField, StringField

from app.models.base import Doc


class RxScan(Doc):
    user_id = StringField()
    url = StringField()
    title = StringField()
    status = StringField(default="running")       # running | done | error
    created_at = DateTimeField()
    meta = {"collection": "rx_scans", "indexes": [("user_id", "-created_at")]}


class RxLabel(Doc):
    user_id = StringField()
    scan_id = StringField()
    cand_id = StringField()
    category = StringField(default="any")
    created_at = DateTimeField()
    meta = {"collection": "rx_labels", "indexes": [("user_id", "category"), ("user_id", "scan_id", "cand_id")]}


class RxModel(Doc):
    user_id = StringField()
    category = StringField(default="any")
    trained_at = DateTimeField()
    meta = {"collection": "rx_models", "indexes": [("user_id", "category")]}
