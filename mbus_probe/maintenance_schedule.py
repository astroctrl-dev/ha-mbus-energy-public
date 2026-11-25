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
from datetime import datetime, timezone, timedelta
from history_controller import history_file
from zoneinfo import ZoneInfo
from dst_transition import latest_transition, evaluate_transition, TransitionStore

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
        self.clock_observations = {}

    def _calendar_key(self, kind, meter_id):
        return kind + ":" + hashlib.sha256(meter_id.encode()).hexdigest()

    def _done(self, key):
        kind, meter_id, period = key
        return key in self.completed or (period != "startup" and
            self.calendar.get(self._calendar_key("dst" if period.startswith("dst-") else kind, meter_id)) == period)

    def _record(self, key):
        self.completed.add(key)
        kind, meter_id, period = key
        if period == "startup":
            return
        self.calendar[self._calendar_key("dst" if period.startswith("dst-") else kind, meter_id)] = period
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

    def observe_clock(self, meter_id, attributes):
        with self.lock:
            self.clock_observations[meter_id] = dict(attributes)
            self.clock_observations[meter_id].setdefault("observed_at_utc", self.now().isoformat())

    def configuration_due(self, meter_id, local):
        try:
            saved = json.loads(history_file(self.root, meter_id).read_text(encoding="utf-8"))
            if saved.get("schema_version") != 3:
                return False
            if len(saved["stands"]) != 24 or len(saved["bounded_periods"]) != 23:
                return False
            stamp = datetime.fromisoformat(saved.get("configuration_read_at_utc") or saved["captured_at_utc"]).astimezone(self.zone)
            return (stamp.year, stamp.month) != (local.year, local.month)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False

    def history_due(self, meter_id, local):
        """Use saved archive and configuration, never process uptime as freshness."""
        try:
            snapshot = json.loads(history_file(self.root, meter_id).read_text(encoding="utf-8"))
            if snapshot.get("schema_version") == 2:
                return False  # Explicit migration is required before collection.
            stands = snapshot["stands"]
            periods = snapshot["bounded_periods"]
            if (len(stands) != 24 or len(periods) != 23 or
                    {r["month_back"] for r in stands} != set(range(1, 25)) or
                    {r["newer_storage"] for r in periods} != set(range(2, 25))):
                return True
            setting = snapshot["monthly_set_day"]
            day, hour, minute = (setting[k] for k in ("day", "hour", "minute"))
            if not 1 <= day <= 28 or not 0 <= hour < 24 or not 0 <= minute < 60:
                return True
            latest = min(stands, key=lambda r: r["month_back"])
            stamp = datetime.fromisoformat(latest["estimated_date"])
            # Check configuration on the first (or first successful round later).
            captured = datetime.fromisoformat(snapshot["captured_at_utc"]).astimezone(self.zone)
            if self.configuration_due(meter_id, local):
                return False
            # Collect after the configured storage day, not during rollover.
            target = local.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            if local < target + timedelta(days=1):
                return False
            return (stamp.year, stamp.month) != (target.year, target.month)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return True

    def due(self, meter_id, local):
        date = local.date().isoformat()
        if hasattr(self.history, "migration_status") and self.history.migration_status(meter_id) in ("pending", "invalid"):
            return
        if self.config.get("allow_clock_sync") and self.config.get("auto_clock_sync"):
            key = ("clock", meter_id, "startup")
            if not self._done(key):
                yield key
            key = ("clock", meter_id, date)
            if local.day == 15 and local.hour == 23 and not self._done(key):
                yield key
        if self.config.get("allow_monthly_history") and self.config.get("auto_monthly_history"):
            if self.configuration_due(meter_id, local):
                key = ("configuration", meter_id, date)
                if not self._done(key):
                    yield key
                return
            key = ("history", meter_id, date)
            if self.history_due(meter_id, local) and not self._done(key):
                yield key

    def _transition_job(self, meter_id, local):
        """Consume at most one observed seasonal transition, before any write."""
        if hasattr(self.history, "migration_status") and self.history.migration_status(meter_id) in ("pending", "invalid"):
            return None
        zone = self.config.get("clock_timezone", "Europe/Oslo")
        transition = latest_transition(local, zone)
        store = TransitionStore(self.root, meter_id)
        try:
            state = store.establish_baseline(transition, f"{zone}:True")
            if not transition or state["last_transition"] == transition["key"]:
                return None
            observation = self.clock_observations.get(meter_id, {})
            observed = datetime.fromisoformat(observation["observed_at_utc"])
            boundary = datetime.fromisoformat(transition["at_utc"])
            if observed.tzinfo is None or not boundary.timestamp() <= observed.timestamp() <= local.timestamp():
                return None
            if local.timestamp() - observed.timestamp() > 900:
                return None
            offset = observation.get("clock_offset_seconds")
            mismatch = observation.get("clock_dst_mismatch")
            outcome = evaluate_transition(transition, offset, mismatch)
            if outcome == "unknown":
                return None
            if outcome == "independent_success" and hasattr(self.clock, "last_write_at"):
                last_write = self.clock.last_write_at(meter_id)
                # Even a manual test or an uncertain write invalidates independent success.
                if last_write is not None and last_write.timestamp() >= boundary.timestamp():
                    store.record_intervened(transition, local)
                    return None
            store.observe(transition, offset, mismatch, local)
            if (outcome == "seasonal_correction_required" and
                    self.config.get("allow_clock_sync") and self.config.get("auto_clock_sync")):
                return transition
        except (OSError, ValueError, TypeError, KeyError):
            LOG.warning("DST transition state unavailable; seasonal correction suppressed")
        return None

    def _execute_transition(self, meter_id, transition):
        try:
            if self.stop.is_set():
                return
            worker = self.clock.start(meter_id, auto=True,
                                      seasonal_shift=transition["shift_seconds"],
                                      transition=transition)
            if worker is not None:
                worker.join()
            # The clock worker persists the verified override before completing.
        except (ValueError, RuntimeError, OSError, TypeError, KeyError):
            LOG.warning("Seasonal clock correction not verified; alarm retained")

    def on_valid_round(self, meter_ids):
        if self.stop.is_set():
            return
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            if self.clock.snapshot().get("status") == "running":
                return
            local = self.now().astimezone(self.zone)
            # A transition observation is persisted before attempting correction.
            for meter_id in meter_ids:
                transition = self._transition_job(meter_id, local)
                if transition:
                    self.worker = threading.Thread(target=self._execute_transition,
                                                   args=(meter_id, transition), daemon=True)
                    self.worker.start()
                    return
            jobs = [key for meter_id in meter_ids for key in self.due(meter_id, local)
                    if self.monotonic() - self.attempted.get(key, -1e12) >= 600]
            filtered = []
            for key in jobs:
                kind, meter_id, _ = key
                if kind == "clock":
                    observation = self.clock_observations.get(meter_id, {})
                    if observation.get("clock_out_of_sync") is False:
                        self._record(key)
                        continue
                    if observation.get("clock_out_of_sync") is not True:
                        continue
                    offset = observation.get("clock_offset_seconds")
                    if offset is None or abs(offset) > 300 or abs(offset) <= 120:
                        self._record(key)
                        LOG.warning("Meter clock requires manual verification")
                        continue
                filtered.append(key)
            jobs = filtered
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
            elif kind == "configuration":
                controller.start(meter_id, settings_only=True)
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
                    if kind == "clock" and local.day == 15 and local.hour == 23:
                        self._record((kind, meter_id, local.date().isoformat()))
                LOG.info("Automatic %s job completed: %s", kind, status)
        except (ValueError, RuntimeError, OSError) as exc:
            LOG.warning("Automatic %s job deferred: %s", kind, type(exc).__name__)
