"""Token ledger (every change of a balance) and the usage records every video's bill is built from."""
import os

from mongoengine import BooleanField, DateTimeField, FloatField, IntField, StringField

from app.models.base import Doc, now


class TokenLedger(Doc):
    user_id = StringField()
    delta = IntField()
    balance = IntField()
    reason = StringField()
    ref = StringField()
    t = DateTimeField()
    meta = {"collection": "token_ledger", "indexes": [("user_id", "-t")]}


class UsageEvent(Doc):
    """One thing that cost something: an AI call, an image, a voice line, captions, a safety check or an upload.
    The video pipeline writes them while it runs; the bill is calculated from them when the video is finished (prices are the owner's)."""
    user_id = StringField()
    job_id = StringField()
    video_id = StringField()
    kind = StringField()                          # llm | image | tts | whisper | safety_local | upload
    provider = StringField()                      # gemini | deepseek | free | edge-tts | whisper | local ...
    task = StringField()                          # commentary | metadata | moments | scoring | safety ...
    units = FloatField(default=0)                 # images: count, tts: characters, whisper: seconds, safety_local: clips, upload: 1
    tokens_in = IntField(default=0)               # AI tokens, as reported by the AI service itself
    tokens_out = IntField(default=0)
    ok = BooleanField(default=True)               # a failed call is never billed
    cost = FloatField(default=0)                  # priced in studio tokens when the video was settled
    billed = BooleanField(default=False)          # False for the owner and for failed videos (records only)
    t = DateTimeField()
    meta = {"collection": "usage_events", "indexes": ["job_id", ("user_id", "-t"), "video_id"]}

    @classmethod
    def record(cls, kind: str, provider: str = "", task: str = "", units: float = 0, tokens_in: int = 0, tokens_out: int = 0,
               ok: bool = True, video_id: str = None, job_id: str = None, user_id: str = None) -> None:
        """Called from the pipeline process (it knows its job and member from the environment). Never raises: a missing
        record must not break a video."""
        try:
            job_id = job_id or os.environ.get("CLIPSTUDIO_JOB_ID") or None
            user_id = user_id or os.environ.get("CLIPSTUDIO_USER_ID") or None
            if not (job_id or video_id):
                return
            cls(user_id=user_id, job_id=job_id, video_id=video_id, kind=kind, provider=provider, task=task, units=float(units or 0),
                tokens_in=int(tokens_in or 0), tokens_out=int(tokens_out or 0), ok=bool(ok), t=now()).save(force_insert=True)
        except Exception:
            pass


class AiCache(Doc):
    """An AI answer worth keeping: the same question (same video, same moments, same clip file) is never paid for twice."""
    id = StringField(primary_key=True)            # sha256 of what was asked
    task = StringField()
    payload = StringField()                       # the answer, as JSON text
    tokens = IntField(default=0)                  # what it cost the first time (that is what every later hit saves)
    hits = IntField(default=0)
    created_at = DateTimeField()
    meta = {"collection": "ai_cache", "indexes": [{"fields": ["created_at"], "expireAfterSeconds": 30 * 86400}, "task"]}


class AiSaving(Doc):
    """AI tokens the studio did NOT spend, and why (cache | lowres | budget | local). Shown in Reports."""
    user_id = StringField()
    job_id = StringField()
    task = StringField()
    kind = StringField()
    tokens = IntField(default=0)
    t = DateTimeField()
    meta = {"collection": "ai_savings", "indexes": [("t",), "kind"]}

    @classmethod
    def record(cls, task: str, kind: str, tokens: int, user_id: str = None, job_id: str = None) -> None:
        try:
            if int(tokens) <= 0:
                return
            cls(user_id=user_id or os.environ.get("CLIPSTUDIO_USER_ID") or None, job_id=job_id or os.environ.get("CLIPSTUDIO_JOB_ID") or None,
                task=task, kind=kind, tokens=int(tokens), t=now()).save(force_insert=True)
        except Exception:
            pass

