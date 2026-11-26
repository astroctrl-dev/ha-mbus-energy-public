"""Shared sampled diagnostic state for MQTT and WebGUI.

No frame offset is assumed. The production caller must not accept an
observation until an independently verified layout parser exists.
"""
from datetime import datetime, timezone
from threading import Lock
from active_diagnostics import active_projection, extension_projection
from battery_diagnostics import battery_status

MAX_AGE_SECONDS = 26 * 3600


def fresh_projection(extension, stamp, *, layout_verified=False, now=None):
    if layout_verified is not True or not isinstance(stamp, str):
        return None
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        if observed.utcoffset() is None or current.utcoffset() is None:
            return None
        if 0 <= (current - observed).total_seconds() <= MAX_AGE_SECONDS:
            return active_projection(extension, layout_verified=True)
    except (ValueError, TypeError, OverflowError, AttributeError):
        pass
    return None


class DiagnosticRuntime:
    def __init__(self, now=lambda: datetime.now(timezone.utc)):
        self.now = now
        self.lock = Lock()
        self.samples = {}
        self.passive = {}

    def observe_normal(self, meter_id, raw, stamp):
        with self.lock:
            self.passive[meter_id] = {**extension_projection(raw), "extension_byte": raw,
                                      "read_at_utc": stamp}

    def observe_verified(self, meter_id, extension, stamp, *, layout_verified=False):
        if fresh_projection(extension, stamp, layout_verified=layout_verified, now=self.now()) is None:
            raise ValueError("unverified or stale diagnostic observation")
        with self.lock:
            self.samples[meter_id] = (bytes(extension), stamp)

    def invalidate(self, meter_id):
        with self.lock:
            self.samples.pop(meter_id, None)

    def evidence(self, meter_id):
        with self.lock:
            return self.samples.get(meter_id, (None, None))

    def snapshot(self, meter_id):
        with self.lock:
            raw, stamp = self.samples.get(meter_id, (None, None))
            passive = dict(self.passive.get(meter_id, {}))
        observed = fresh_projection(raw, stamp, layout_verified=raw is not None, now=self.now())
        result = dict(observed or {})
        result["battery_status"] = battery_status(observed)
        result["read_at_utc"] = stamp if observed is not None else None
        result["extension"] = passive
        return result
