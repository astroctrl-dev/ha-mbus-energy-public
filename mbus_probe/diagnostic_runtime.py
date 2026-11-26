"""Shared sampled diagnostic state for MQTT and WebGUI.

No frame offset is assumed. The production caller must not accept an
observation until an independently verified layout parser exists.
"""
import hashlib
import json
import os
from pathlib import Path
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
    def __init__(self, now=lambda: datetime.now(timezone.utc), *, root=None):
        self.now = now
        self.lock = Lock()
        self.root = Path(root) / 'active-diagnostics' if root is not None else None
        self.samples = {}
        self.passive = {}

    def _path(self, meter_id):
        if not isinstance(meter_id, str) or len(meter_id) != 8 or not meter_id.isascii() or not meter_id.isdigit():
            raise ValueError("invalid meter identity")
        return self.root / (hashlib.sha256(("diagnostic:" + meter_id).encode()).hexdigest() + ".json")

    def _load(self, meter_id):
        if meter_id in self.samples:
            return self.samples[meter_id]
        if self.root is not None:
            try:
                data = json.loads(self._path(meter_id).read_text(encoding="utf-8"))
                if data["schema"] != "t230-frame5-7.12-v1":
                    return None, None
                raw, stamp = bytes.fromhex(data["abcdef"]), data["read_at_utc"]
                if fresh_projection(raw, stamp, layout_verified=True, now=self.now()) is not None:
                    self.samples[meter_id] = (raw, stamp)
                    return raw, stamp
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                pass
        return None, None

    def _save(self, meter_id, raw, stamp):
        if self.root is None:
            return
        path = self._path(meter_id)
        self.root.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="utf-8") as out:
                json.dump({"schema": "t230-frame5-7.12-v1", "abcdef": raw.hex(),
                           "read_at_utc": stamp}, out)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, path)
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temp.unlink(missing_ok=True)

    def observe_normal(self, meter_id, raw, stamp):
        with self.lock:
            self.passive[meter_id] = {**extension_projection(raw), "extension_byte": raw,
                                      "read_at_utc": stamp}

    def observe_verified(self, meter_id, extension, stamp, *, layout_verified=False):
        if fresh_projection(extension, stamp, layout_verified=layout_verified, now=self.now()) is None:
            raise ValueError("unverified or stale diagnostic observation")
        with self.lock:
            self._save(meter_id, bytes(extension), stamp)
            self.samples[meter_id] = (bytes(extension), stamp)

    def invalidate(self, meter_id):
        with self.lock:
            if self.root is not None:
                path = self._path(meter_id)
                path.unlink(missing_ok=True)
                if self.root.exists():
                    fd = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            self.samples.pop(meter_id, None)

    def evidence(self, meter_id):
        with self.lock:
            return self._load(meter_id)

    def snapshot(self, meter_id):
        with self.lock:
            raw, stamp = self._load(meter_id)
            passive = dict(self.passive.get(meter_id, {}))
        observed = fresh_projection(raw, stamp, layout_verified=raw is not None, now=self.now())
        result = dict(observed or {})
        result["battery_status"] = battery_status(observed)
        result.setdefault("meter_installation_status", "unknown")
        result["read_at_utc"] = stamp if observed is not None else None
        result["extension"] = passive
        return result
