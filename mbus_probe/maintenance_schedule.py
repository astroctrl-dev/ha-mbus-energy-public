"""Queue automatic maintenance only after a fresh ordinary measurement.

Calendar jobs use local dates, not elapsed 24-hour timers. A successful
operation consumes its job key; failed operations are retried on a later
valid round with a bounded retry interval. Manual controls remain unchanged.
"""
import hashlib
import json
import os
from pathlib import Path
import logging
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOG = logging.getLogger("mbus.maintenance")


class MaintenanceSchedule:
    def __init__(self, config, clock, history, stop, now=lambda: datetime.now(timezone.utc),
                 monotonic=time.monotonic, root='/data/analysis'):
        self.config, self.clock, self.history, self.stop = config, clock, history, stop
        self.now, self.monotonic = now, monotonic
        self.zone = ZoneInfo(config.get("clock_timezone", "Europe/Oslo"))
        self.completed = set()
        self.root = Path(root)
        self.path = self.root / 'maintenance-calendar.json'
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            self.calendar = {k: v for k, v in saved.items() if isinstance(k, str) and isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            self.calendar = {}
        self.attempted = {}
        self.lock = threading.Lock()
        self.worker = None

    def _calendar_key(self, kind, meter_id):
        return kind + ":" + hashlib.sha256(meter_id.encode()).hexdigest()

    def _done(self, key):
        kind, meter_id, period = key
        return key in self.completed or (period != "startup" and
            self.calendar.get(self._calendar_key(kind, meter_id)) == period)

    def _record(self, key):
        self.completed.add(key)
        kind, meter_id, period = key
        if period == "startup":
            return
        self.calendar[self._calendar_key(kind, meter_id)] = period
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            with temp.open("w", encoding="utf-8") as out:
                json.dump(self.calendar, out)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
        except OSError:
            LOG.warning("Maintenance calendar could not be persisted")

    def due(self, meter_id, local):
        date = local.date().isoformat()
        if self.config.get("allow_clock_sync") and self.config.get("auto_clock_sync"):
            key = ("clock", meter_id, "startup")
            if not self._done(key):
                yield key
            key = ("clock", meter_id, date)
            if local.hour == 23 and not self._done(key):
                yield key
        if self.config.get("allow_monthly_history") and self.config.get("auto_monthly_history"):
            key = ("history", meter_id, "startup")
            if not self._done(key):
                yield key
            key = ("history", meter_id, date)
            if local.day in (1, 2) and local.hour == 1 and not self._done(key):
                yield key

    def on_valid_round(self, meter_ids):
        if self.stop.is_set():
            return
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            local = self.now().astimezone(self.zone)
            jobs = [key for meter_id in meter_ids for key in self.due(meter_id, local)
                    if self.monotonic() - self.attempted.get(key, -1e12) >= 600]
            if not jobs:
                return
            # One job per round; a fresh normal read is required before another.
            self.worker = threading.Thread(target=self._execute, args=(jobs[0],), daemon=True)
            self.worker.start()

    def _execute(self, key):
        kind, meter_id, _ = key
        controller = self.clock if kind == "clock" else self.history
        with self.lock:
            self.attempted[key] = self.monotonic()
        try:
            if self.stop.is_set():
                return
            if kind == "clock":
                controller.start(meter_id, auto=True)
            else:
                controller.start(meter_id)
            worker = controller.worker
            worker.join()
            # A new manual job may have replaced the completed worker.
            # Do not attribute its outcome to this calendar job.
            if controller.worker is not worker:
                return
            status = controller.snapshot()["status"]
            if status in (("verified", "manual_required") if kind == "clock" else ("complete",)):
                with self.lock:
                    self._record(key)
                    self.completed.add((kind, meter_id, "startup"))
                    local = self.now().astimezone(self.zone)
                    if (kind == "history" and local.day in (1, 2) and local.hour == 1
                            or kind == "clock" and local.hour == 23):
                        self._record((kind, meter_id, local.date().isoformat()))
                LOG.info("Automatic %s job completed: %s", kind, status)
        except (ValueError, RuntimeError, OSError) as exc:
            LOG.warning("Automatic %s job deferred: %s", kind, type(exc).__name__)
