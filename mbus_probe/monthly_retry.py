"""Persistent bounded monthly retry ledger, independent of serial I/O."""
import json
import os
import tempfile
import threading
from functools import wraps
from pathlib import Path
from datetime import date

_lock = threading.RLock()

def synchronized(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper

class MonthlyRetry:
    def __init__(self, root):
        self.path = Path(root) / "monthly-retry.json"

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError("invalid monthly retry ledger")
        for key, row in data.items():
            if not isinstance(row, dict):
                raise ValueError("invalid monthly retry row")
            if key == "alarms":
                if any(not isinstance(alarm, dict) or type(alarm.get("active")) is not bool
                       for alarm in row.values()):
                    raise ValueError("invalid monthly retry alarm")
                continue
            if type(row.get("complete")) is not bool:
                raise ValueError("invalid monthly retry completion")
            for field in ("days", "failures"):
                counts = row.get(field, {})
                if not isinstance(counts, dict) or any(type(n) is not int or not 0 <= n <= 3
                                                      for n in counts.values()):
                    raise ValueError("invalid monthly retry counts")
                for day in counts:
                    date.fromisoformat(day)
            for day, failures in row.get("failures", {}).items():
                if failures > row.get("days", {}).get(day, 0):
                    raise ValueError("invalid monthly retry failure count")
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".monthly-retry-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(data, out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def eligible(self, key, today, first_day):
        row = self.load().get(key, {})
        age = (today - first_day).days
        return (0 <= age < 10 and not row.get("complete", False)
                and row.get("days", {}).get(today.isoformat(), 0) < 3)

    @synchronized
    def reserve(self, key, today, first_day):
        if not self.eligible(key, today, first_day):
            return False
        data = self.load()
        row = data.setdefault(key, {"days": {}, "complete": False})
        day = today.isoformat()
        row["days"][day] = row["days"].get(day, 0) + 1
        self.save(data)
        return True

    @staticmethod
    def _failure(data, key, day, reason):
        row = data[key]
        failures = row.setdefault("failures", {})
        failures[day] = failures.get(day, 0) + 1
        if failures[day] == 3:
            meter, month = key.rsplit(":", 1)
            alarms = data.setdefault("alarms", {})
            previous = alarms.get(meter, {})
            # Reconciliation must not overwrite a newer alarm or re-latch
            # an already acknowledged incident for the same day.
            if previous.get("date", "") < day:
                alarms[meter] = {"active": True, "month": month, "date": day,
                                 "attempts": 3, "reason": reason}

    @synchronized
    def reconcile_interrupted(self):
        """Called once by the scheduler at process startup, never by UI readers."""
        data = self.load()
        changed = False
        for key, row in list(data.items()):
            if key == "alarms" or row["complete"]:
                continue
            for day, reserved in sorted(row["days"].items()):
                missing = reserved - row.get("failures", {}).get(day, 0)
                for _ in range(missing):
                    self._failure(data, key, day, "interrupted_unverified")
                    changed = True
        if changed:
            self.save(data)

    @synchronized
    def finish(self, key, today, success, reason=None):
        data = self.load()
        row = data[key]
        day = today.isoformat()
        if row["complete"] or row.get("failures", {}).get(day, 0) >= row["days"].get(day, 0):
            raise ValueError("no outstanding monthly attempt")
        if success:
            row["complete"] = True
        else:
            self._failure(data, key, day, reason)
        self.save(data)

    def alarm(self, meter):
        return self.load().get("alarms", {}).get(meter, {"active": False})

    @synchronized
    def acknowledge(self, meter):
        data = self.load()
        row = data.get("alarms", {}).get(meter)
        if row:
            row["active"] = False
            self.save(data)
