"""Gated frame-3 collection, manual or scheduled."""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from analysis_export import _alias
from history_model import build_snapshot, detect_month_shift, estimated_month_at_capture, save_snapshot
from mqtt_bridge import device_key
from monthly_diagnostic import RestorationError, run as read_months

LOG = logging.getLogger("mbus.history")


def history_file(root, meter_id):
    root = Path(root)
    alias = _alias(meter_id, root / "alias.key")
    return root / "history" / (alias + ".json")


def load_history(root, selected):
    """Only snapshots for currently selected meters enter the workbook."""
    result = []
    for row in selected:
        path = history_file(root, row["meter_id"])
        if not path.exists():
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if len(snapshot.get("stands", ())) != 24 or len(snapshot.get("bounded_periods", ())) != 23:
            raise ValueError("invalid saved monthly history")
        result.append((path.stem, snapshot))
    return result


class HistoryController:
    def __init__(self, registry, config, bus_lock, stop, root="/data/analysis",
                 reader=read_months, pause=time.sleep, on_complete=None):
        self.registry, self.config, self.bus_lock, self.stop = registry, config, bus_lock, stop
        self.root, self.reader, self.pause, self.on_complete = Path(root), reader, pause, on_complete
        self.lock = threading.Lock()
        self.marker = self.root / "normal_frame_unverified"
        self.blocked = threading.Event()
        if self.marker.exists():
            self.blocked.set()
        self.state = {"status": "restore_unverified" if self.blocked.is_set() else "not_started",
                      "error": "Normalramme ikke verifisert; polling stoppet" if self.blocked.is_set() else None,
                      "captured_at_utc": None}
        self.worker = None
        self.publish_pending = {}
        self.publish_worker = None
        self.publication_lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, meter_id, completion=None):
        if self.config.get("allow_monthly_history") is not True:
            raise ValueError("Aktiver månedshistorikk i appens Configuration først")
        if self.stop.is_set() or self.blocked.is_set():
            raise ValueError("app is stopping or normal frame is unverified")
        with self.registry.lock:
            address = self.registry.selected.get(meter_id)
            if address is None:
                raise ValueError("select a meter before history collection")
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("monthly history is already running")
            self.state = {"status": "running", "error": None, "captured_at_utc": None}
            self.worker = threading.Thread(target=self._collect, args=(meter_id, address, completion), daemon=True)
            self.worker.start()

    def queue_saved_publication(self):
        """Reload durable snapshots on reconnect without replacing newer pending data."""
        for row in self.registry.snapshot()["selected"]:
            meter_id = row["meter_id"]
            try:
                with self.lock:
                    path = history_file(self.root, meter_id)
                    if path.exists():
                        snapshot = json.loads(path.read_text(encoding="utf-8"))
                        self.publish_pending.setdefault(meter_id, snapshot)
            except (OSError, ValueError):
                LOG.warning("Saved history could not be queued")
        self.retry_publication()

    def retry_publication(self):
        """Retry saved snapshots outside the physical bus lock."""
        with self.lock:
            if not self.publish_pending or self.stop.is_set():
                return
            if self.publish_worker and self.publish_worker.is_alive():
                return
            self.publish_worker = threading.Thread(target=self._publish_pending, daemon=True)
            self.publish_worker.start()

    def _publish_pending(self):
        with self.lock:
            pending = list(self.publish_pending.items())
        for meter_id, snapshot in pending:
            try:
                with self.publication_lock:
                    with self.registry.lock:
                        selected = meter_id in self.registry.selected
                    if selected and not self.stop.is_set():
                        self.on_complete(meter_id, snapshot)
                    elif self.stop.is_set():
                        return
            except (OSError, ValueError, ConnectionError, RuntimeError):
                LOG.warning("History saved but MQTT publication failed; retry pending")
                continue
            with self.lock:
                if self.publish_pending.get(meter_id) is snapshot:
                    self.publish_pending.pop(meter_id, None)

    def _collect(self, meter_id, address, completion=None):
        success = False
        try:
            with self.bus_lock:
                with self.registry.lock:
                    if self.registry.selected.get(meter_id) != address or self.stop.is_set():
                        raise ValueError("selected meter changed or app is stopping")
                # A normal poll or scan may have finished immediately before the lock.
                self.pause(61)
                if self.stop.is_set() or self.blocked.is_set():
                    raise ValueError("app stopping or normal frame unverified")
                # Marker survives process crash. Clear only after verified restore.
                self.root.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT, 0o600)
                os.close(fd)
                try:
                    result = self.reader(self.config["serial_port"], int(self.config.get("baud", 2400)),
                                         address, meter_id)
                except Exception:
                    self.blocked.set()  # Set before releasing the shared bus.
                    raise
                finally:
                    self.pause(61)
                # The reader returns only after a checksum/identity-verified normal frame.
                self.marker.unlink()
                if isinstance(result, tuple):
                    months, observation, history_read_at = result
                else:
                    months, observation, history_read_at = result, None, None
                captured_at = datetime.now(timezone.utc).isoformat()
                trust_file = self.root / ("clock-trust-" + device_key(meter_id) + ".json")
                try:
                    trust_record = json.loads(trust_file.read_text(encoding="utf-8"))
                    clock_trusted = trust_record.get("status") == "verified"
                except (OSError, ValueError):
                    trust_record, clock_trusted = {}, False
                estimated_month = estimated_month_at_capture(
                    captured_at, observation, clock_trusted,
                    self.config.get("clock_timezone", "Europe/Oslo"), history_read_at)
                snapshot = build_snapshot(months, captured_at, estimated_month)
                snapshot["date_provenance"] = {
                    "history_read_at_utc": history_read_at,
                    "normal_read_at_utc": observation.get("last_successful_read_utc") if observation else None,
                    "meter_local_time_at_normal": observation.get("meter_local_time") if observation else None,
                    "meter_summer_time_at_normal": observation.get("meter_summer_time") if observation else None,
                    "clock_trusted_at_capture": clock_trusted,
                    "clock_trust_verified_at_utc": trust_record.get("at_utc") if clock_trusted else None,
                    "timezone_assumed": self.config.get("clock_timezone", "Europe/Oslo"),
                    "rule": "first-of-month fallback after 15-minute grace; not meter storage time",
                    "estimate_applied": estimated_month is not None,
                }
                path = history_file(self.root, meter_id)
                try:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    previous = None
                snapshot["rollover_evidence"] = (
                    "confirmed_shift" if detect_month_shift(previous, snapshot) else "not_observed")
                save_snapshot(path, snapshot)
                if self.on_complete:
                    with self.lock:
                        self.publish_pending[meter_id] = snapshot
                    self.retry_publication()
                with self.lock:
                    self.state = {"status": "complete", "error": None,
                                  "captured_at_utc": snapshot["captured_at_utc"]}
            success = True
        except Exception as exc:
            # No ID, raw telegram, serial path or exception details in UI/logs.
            uncertain = isinstance(exc, RestorationError) or self.marker.exists()
            if uncertain:
                # A reader exception before verified return is also an unknown frame state.
                self.blocked.set()  # Persistent marker forbids further ordinary polling.
            LOG.error("Monthly history failed: %s%s", type(exc).__name__,
                      "; normal frame unverified, polling stopped" if uncertain else "")
            with self.lock:
                self.state = {"status": "restore_unverified" if uncertain else "failed",
                              "error": "Normalramme ikke verifisert; polling stoppet" if uncertain
                                       else "Historikkavlesning feilet; tidligere data beholdt",
                              "captured_at_utc": None}

        finally:
            if completion:
                completion(success)


class HistorySchedule:
    """Schedule per meter after valid normal rounds, without blocking polling."""
    def __init__(self, controller, now=lambda: datetime.now(timezone.utc),
                 monotonic=time.monotonic, retry_seconds=900):
        from zoneinfo import ZoneInfo
        self.controller = controller
        self.zone = ZoneInfo(controller.config.get("clock_timezone", "Europe/Oslo"))
        self.now, self.monotonic = now, monotonic
        self.retry_seconds = retry_seconds
        self.lock = threading.Lock()
        self.started = set()
        self.completed = {}
        self.retry_at = {}
        self.pending = {}
        self.active = False

    def on_valid_round(self, meter_ids):
        c = self.controller
        if not c.config.get("allow_monthly_history") or c.stop.is_set() or c.blocked.is_set():
            return
        local = self.now().astimezone(self.zone)
        slot = local.date() if local.day in (1, 2) and local.hour >= 1 else None
        with self.lock:
            if self.active:
                return
            for meter_id in meter_ids:
                if slot is not None and self.completed.get(meter_id) != slot:
                    self.pending[meter_id] = slot
            for meter_id in meter_ids:
                if self.monotonic() < self.retry_at.get(meter_id, 0):
                    continue
                if meter_id in self.started and meter_id not in self.pending:
                    continue
                requested_slot = self.pending.get(meter_id)
                self.active = True
                break
            else:
                return

        def finished(success):
            with self.lock:
                if success:
                    self.started.add(meter_id)
                    if requested_slot is not None:
                        self.completed[meter_id] = requested_slot
                        if self.pending.get(meter_id) == requested_slot:
                            self.pending.pop(meter_id, None)
                    self.retry_at.pop(meter_id, None)
                else:
                    self.retry_at[meter_id] = self.monotonic() + self.retry_seconds
                self.active = False

        try:
            c.start(meter_id, completion=finished)
        except (ValueError, RuntimeError):
            finished(False)
