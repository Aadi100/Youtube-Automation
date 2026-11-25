"""Models for the Learning Lab (beta). Nothing outside the lab reads these collections for any other purpose.

LabExample  one example the owner likes (a title, a description) or the lab collected from the owner's own edits.
LabLog      what the studio generated for one video (the title candidates and which one won; the description parts), kept so the lab can show
            and learn from it.
LabState    one per part ("titles", "descriptions", "clipping"): is it switched on, and what has it learned.
"""
from mongoengine import BooleanField, DateTimeField, IntField, StringField

from app.models.base import Doc


class LabExample(Doc):
    user_id = StringField()
    kind = StringField()                          # title | description
    text = StringField()
    source = StringField(default="owner")         # owner (added by hand) | edit (the owner rewrote a generated one)
    created_at = DateTimeField()
    meta = {"collection": "lab_examples", "indexes": [("user_id", "kind", "-created_at")]}


class LabLog(Doc):
    user_id = StringField()
    kind = StringField()                          # title | description
    job_id = StringField()
    created_at = DateTimeField()
    meta = {"collection": "lab_logs", "indexes": [("user_id", "kind", "-created_at"), "job_id"]}


class LabState(Doc):
    id = StringField(primary_key=True)            # "<user id>:<part>"
    user_id = StringField()
    part = StringField()
    on = BooleanField(default=False)
    n = IntField(default=0)                       # how many examples the current model was trained on
    trained_at = DateTimeField()
    meta = {"collection": "lab_state"}
