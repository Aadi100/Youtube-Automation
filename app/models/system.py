"""Server-wide documents: settings, singletons (pricing, alerts, worker heartbeats) and leases."""
import time as _t

from mongoengine import Q, StringField
from mongoengine.errors import NotUniqueError

from app.models.base import Doc


class Setting(Doc):
    id = StringField(primary_key=True)            # e.g. "clipping:<user id>", "schedule:<user id>"
    meta = {"collection": "settings"}


class System(Doc):
    """Singletons: "auth", "pricing", "alerts", "worker:<id>" heartbeats, "lease:<name>" locks."""
    id = StringField(primary_key=True)
    meta = {"collection": "system"}

    @classmethod
    def acquire_lease(cls, name: str, who: str, ttl: int = 90) -> bool:
        """Only one of several workers holds a named lease at a time (scheduler, maintenance). Renewed every loop; expires if the holder dies."""
        t = _t.time()
        key = f"lease:{name}"
        if cls.objects(Q(id=key) & (Q(until__lt=t) | Q(holder=who))).modify(set__holder=who, set__until=t + ttl):
            return True
        try:
            cls(id=key, holder=who, until=t + ttl).save(force_insert=True)
            return True
        except NotUniqueError:
            return False
