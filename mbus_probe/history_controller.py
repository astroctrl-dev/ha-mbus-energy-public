"""Explicit, gated frame-3 collection. Never called by polling or download."""
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

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, meter_id):
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
            self.worker = threading.Thread(target=self._collect, args=(meter_id, address), daemon=True)
            self.worker.start()

    def _collect(self, meter_id, address):
        try:
            with self.bus_lock:
                with self.registry.lock:
                    if self.registry.selected.get(meter_id) != address or self.stop.is_set():
                        raise ValueError("selected meter changed or app is stopping")
                # A normal poll or scan may have finished immediately before the lock.
                self.pause(61)
                # Marker survives process crash. Clear only after verified restore.
                self.root.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT, 0o600)
                os.close(fd)
                result = self.reader(self.config["serial_port"], int(self.config.get("baud", 2400)),
                                     address, meter_id)
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
                    try:
                        self.on_complete(meter_id, snapshot)
                    except (OSError, ValueError, ConnectionError):
                        LOG.warning("History saved but MQTT publication failed")
                with self.lock:
                    self.state = {"status": "complete", "error": None,
                                  "captured_at_utc": snapshot["captured_at_utc"]}
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
