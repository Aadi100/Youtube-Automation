"""Token ledger (every change of a balance) and the usage records every video's bill is built from."""
import os
import threading

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
               ok: bool = True, video_id: str = None, job_id: str = None, user_id: str = None, estimated: bool = False) -> None:
        """Called from the pipeline process (it knows its job and member from the environment). Never raises: a missing
        record must not break a video."""
        AiCall.from_usage(kind, provider, task, units, tokens_in, tokens_out, ok, user_id, video_id or job_id, estimated)      # the owner's AI usage page counts every call, with or without a video
        try:
            job_id = job_id or os.environ.get("CLIPSTUDIO_JOB_ID") or None
            user_id = user_id or os.environ.get("CLIPSTUDIO_USER_ID") or None
            if not (job_id or video_id):
                return
            cls(user_id=user_id, job_id=job_id, video_id=video_id, kind=kind, provider=provider, task=task, units=float(units or 0),
                tokens_in=int(tokens_in or 0), tokens_out=int(tokens_out or 0), ok=bool(ok), t=now()).save(force_insert=True)
        except Exception:
            pass


_WHO = threading.local()
# what a usage record of this kind is, in the words of the AI usage page: (kind shown, the unit of `units`)
_AI_KINDS = {"llm": ("text", "tokens"), "image": ("image", "images"), "tts": ("voice", "characters"), "whisper": ("captions", "seconds"),
             "safety_local": ("safety", "clips"), "web_search": ("search", "searches")}


class AiCall(Doc):
    """One real call to an AI service (text, picture, voice, captions, video, web search), written when the call is made, for whoever asked.
    The numbers are what the service itself reported (tokens in and out); `estimated` is true when it did not report them and the studio counted by size.
    This is the owner's AI usage page. It is separate from the bill (UsageEvent), which only exists while a video is being made."""
    t = DateTimeField()
    service = StringField()                       # deepseek | gemini | claude | flux | free | azure | kokoro | edge-tts | whisper | veo | nudenet
    kind = StringField()                          # text | image | voice | captions | video | search | safety
    task = StringField()                          # commentary | metadata | thumbnail | story-picture | story-script ...
    tokens_in = IntField(default=0)               # text AI: input tokens as the service reported them
    tokens_out = IntField(default=0)
    estimated = BooleanField(default=False)
    units = FloatField(default=0)                 # images: count, voice: characters, captions / video: seconds, search: searches, safety: clips
    unit = StringField()
    ok = BooleanField(default=True)
    error = StringField()
    user_id = StringField()
    ref = StringField()                           # the job, video or story it belonged to
    meta = {"collection": "ai_calls", "indexes": [("service", "-t"), ("user_id", "-t"), {"fields": ["t"], "expireAfterSeconds": 400 * 86400}]}

    @staticmethod
    def set_who(user_id=None, ref=None) -> None:
        """Who is asking, for the calls made on this thread (a web request, a story being made)."""
        _WHO.user, _WHO.ref = user_id, ref

    @classmethod
    def log(cls, service: str, kind: str, task: str = "", tokens_in: int = 0, tokens_out: int = 0, units: float = 0, unit: str = "", ok: bool = True,
            error: str = "", estimated: bool = False, user_id: str = None, ref: str = None) -> None:
        """Never raises: a missing row must not break a video."""
        try:
            cls(t=now(), service=service or "", kind=kind, task=task or "", tokens_in=int(tokens_in or 0), tokens_out=int(tokens_out or 0), estimated=bool(estimated),
                units=float(units or 0), unit=unit, ok=bool(ok), error=str(error or "")[:160],
                user_id=user_id or getattr(_WHO, "user", None) or os.environ.get("CLIPSTUDIO_USER_ID") or None,
                ref=ref or getattr(_WHO, "ref", None) or os.environ.get("CLIPSTUDIO_JOB_ID") or None).save(force_insert=True)
        except Exception:
            pass

    @classmethod
    def from_usage(cls, kind: str, provider: str, task: str, units: float, tokens_in: int, tokens_out: int, ok: bool, user_id=None, ref=None, estimated: bool = False) -> None:
        """The same thing seen from a bill record: only the kinds that are an AI service are written (not scans, uploads, e-mails ...)."""
        k = _AI_KINDS.get(kind)
        if not k:
            return
        cls.log(provider, k[0], task, tokens_in, tokens_out, 0 if kind == "llm" else units, "" if kind == "llm" else k[1], ok, "", estimated, user_id, ref)


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

