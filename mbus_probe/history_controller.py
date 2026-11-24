"""Explicit, gated frame-3 collection. Never called by polling or download."""
from bus_timing import write_frame, shared_timing_active
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
from monthly_diagnostic import (RestorationError, run as read_months, extract_months,
                                restore_normal_frame, read_response)
from mbus_probe import read_one, validate
from ha_measurements import REQUIRED_SENSORS, select_measurements

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

    def _recovery_log(self, tx, rx):
        LOG.info("Recovery TX=%s RX length=%d bytes", tx.hex(" "), len(rx))
        if self.config.get("recovery_raw_log") is True:
            LOG.info("Recovery raw RX=%s", rx.hex(" "))

    def _restore_interface(self, port, baud, address):
        import serial
        tx = restore_normal_frame(address)
        with serial.Serial(port, baudrate=baud, bytesize=8, parity="E", stopbits=1,
                           timeout=5, write_timeout=5, exclusive=True) as ser:
            ser.reset_input_buffer()
            write_frame(ser, tx)
            ser.flush()
            rx = read_response(ser)
            self._recovery_log(tx, rx)
        if rx != b"\xe5":
            raise ValueError("normal interface restore not acknowledged")

    def _verify_recovery(self, decoded, address, meter_id):
        if decoded.get("address") != address:
            raise ValueError("normal frame address mismatch")
        values = select_measurements(decoded, meter_id)
        # Identify the ordinary frame by its record layout, not by whether
        # every individual measurement has a usable value. Historical frames
        # must not clear the guard even if they contain some current values.
        present = {r.get("kind") for r in decoded.get("records", ())
                   if r.get("current_record")}
        missing = REQUIRED_SENSORS - present
        if missing:
            raise ValueError("normal frame missing record types: " + ", ".join(sorted(missing)))
        if REQUIRED_SENSORS - values.keys():
            LOG.warning("Normal frame verified with unavailable measurements: %s",
                        ", ".join(sorted(REQUIRED_SENSORS - values.keys())))

    def recover_normal(self, reader=read_one):
        """Read first; optional interface restore only after confirmed frame-3 identity."""
        if not self.blocked.is_set():
            return True
        try:
            with self.bus_lock, self.registry.lock:
                selected = list(self.registry.selected.items())
                if not selected:
                    return False
                for meter_id, address in selected:
                    if not shared_timing_active() and self.stop.wait(61):
                        return False
                    port = self.config["serial_port"]
                    baud = int(self.config.get("baud", 2400))
                    tx, frame = reader(port, baud, address, timeout=5)
                    self._recovery_log(tx, frame)
                    decoded = validate(frame)
                    try:
                        self._verify_recovery(decoded, address, meter_id)
                    except ValueError as normal_error:
                        if decoded.get("address") != address or decoded.get("control") not in (8, 24):
                            raise normal_error
                        try:
                            extract_months(frame, meter_id)
                        except ValueError:
                            raise normal_error from None
                        LOG.warning("Recovery confirmed historical frame for selected meter")
                        if self.config.get("allow_recovery_interface_reset") is not True:
                            raise ValueError("historical frame confirmed; interface restore disabled")
                        if len(selected) != 1:
                            raise ValueError("interface restore requires exactly one selected meter")
                        if not shared_timing_active() and self.stop.wait(61):
                            return False
                        self._restore_interface(port, baud, address)
                        if not shared_timing_active() and self.stop.wait(61):
                            return False
                        tx, frame = reader(port, baud, address, timeout=5)
                        self._recovery_log(tx, frame)
                        self._verify_recovery(validate(frame), address, meter_id)
                if not shared_timing_active() and self.stop.wait(61):
                    return False
                self.marker.unlink(missing_ok=True)
                self.blocked.clear()
                with self.lock:
                    self.state = {"status": "recovered", "error": None, "captured_at_utc": None}
                LOG.info("Normal frame verified; polling resumed")
                return True
        except Exception as exc:
            LOG.warning("Normal frame recovery failed: %s: %s", type(exc).__name__,
                        str(exc) if isinstance(exc, ValueError) else "see local serial/storage configuration")
            return False

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
                    if (self.registry.selected.get(meter_id) != address or self.stop.is_set()
                            or self.blocked.is_set()):
                        raise ValueError("selected meter changed or app is stopping")
                # A normal poll or scan may have finished immediately before the lock.
                if not shared_timing_active():
                    self.pause(61)
                # Marker survives process crash. Clear only after verified restore.
                self.root.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT, 0o600)
                os.close(fd)
                try:
                    result = self.reader(self.config["serial_port"], int(self.config.get("baud", 2400)),
                                         address, meter_id)
                    # The reader returns only after a verified normal frame.
                    self.marker.unlink()
                except Exception:
                    # Set the guard before releasing the bus lock. A queued
                    # poll must never slip into an uncertain interface state.
                    self.blocked.set()
                    raise
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
