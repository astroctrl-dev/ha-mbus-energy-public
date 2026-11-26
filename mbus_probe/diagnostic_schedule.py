"""Conservative automatic diagnostic policy; no bus access.

A durable reservation precedes each automatic attempt. A verified layout
and explicit runtime enablement are both mandatory. Failed attempts are
not retried automatically until the next local day. Manual capture is
a separate operation. This module does not authorize physical access.
"""
import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class DiagnosticSchedule:
    def __init__(self, root, timezone_name):
        self.root = Path(root)
        self.zone = ZoneInfo(timezone_name)
        self.path = self.root / "diagnostic-calendar.json"
        self.lock = threading.Lock()

    def reserve(self, meter_id, now, *, enabled=False, layout_verified=False,
                fresh_normal=False, bus_idle=False):
        if not all(x is True for x in (enabled, layout_verified, fresh_normal, bus_idle)):
            return False
        if not isinstance(now, datetime) or now.utcoffset() is None:
            return False
        if not isinstance(meter_id, str) or len(meter_id) != 8 or not meter_id.isascii() or not meter_id.isdigit():
            return False
        day = now.astimezone(self.zone).date().isoformat()
        key = hashlib.sha256(("diagnostic:" + meter_id).encode()).hexdigest()
        with self.lock:
            try:
                try:
                    state = json.loads(self.path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    state = {}
                if not isinstance(state, dict):
                    return False
                for k, v in state.items():
                    if not isinstance(k, str) or not isinstance(v, str):
                        return False
                    if datetime.strptime(v, "%Y-%m-%d").date().isoformat() != v:
                        return False
                if state.get(key, "") >= day:
                    return False
                state[key] = day
                self.root.mkdir(parents=True, exist_ok=True)
                temp = self.path.with_suffix(".tmp")
                try:
                    with temp.open("w", encoding="utf-8") as out:
                        json.dump(state, out)
                        out.flush()
                        os.fsync(out.fileno())
                    os.chmod(temp, 0o600)
                    os.replace(temp, self.path)
                    fd = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                finally:
                    temp.unlink(missing_ok=True)
                return True
            except (OSError, ValueError, TypeError):
                return False
