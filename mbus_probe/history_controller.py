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
from history_model import migrate_snapshot, configured_anchor, build_snapshot, detect_month_shift, estimated_month_at_capture, save_snapshot
from mqtt_bridge import device_key
from rolling_history import merge_history
from archive_acquisition import ArchiveDataError
from mbus_records import t230_footer
from monthly_diagnostic import (RestorationError, run as read_months, extract_months, extract_monthly_set_day,
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
        if reader is read_months:
            from functools import partial
            self.reader = partial(read_months, read_set_day=True)
        self.lock = threading.Lock()
        self.marker = self.root / "normal_frame_unverified"
        self.blocked = threading.Event()
        if self.marker.exists():
            self.blocked.set()
        self.state = {"status": "restore_unverified" if self.blocked.is_set() else "not_started",
                      "error": "Normalramme ikke verifisert; polling stoppet" if self.blocked.is_set() else None,
                      "captured_at_utc": None}
        self.worker = None
        self.archive_progress = {}
        self.archive_meter = None
        self.archive_revision = 0
        self.startup_pending = False
        self.startup_readings = []

    def snapshot(self):
        with self.lock:
            return {**self.state, "archive_meter": self.archive_meter,
                    "archive_progress": dict(self.archive_progress), "archive_revision": self.archive_revision}

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

    @staticmethod
    def _confirmed_archive(decoded, address, meter_id):
        return (decoded.get("type") == "long" and decoded.get("ci") == 0x72
                and decoded.get("control") in (8,24) and decoded.get("address") == address
                and decoded.get("meter_id") == meter_id and decoded.get("manufacturer") == "LUG"
                and decoded.get("medium_code") == 4 and decoded.get("status") in (0,0x10)
                and t230_footer(decoded,4) is not None)

    def require_startup_normal(self):
        """Every process start must verify frame 1 on known meters."""
        if self.registry.snapshot()["selected"]:
            self.startup_pending = True
            self.blocked.set()
            with self.lock:
                self.state = {"status":"restore_unverified","error":"Startup normal frame initialization pending",
                              "captured_at_utc":None}

    def _initialize_normal(self, selected, reader):
        # Verify first; only a positively identified historical frame permits
        # a selector write. Keep the startup guard until all meters verify.
        readings = []
        for meter_id,address in selected:
            if self.stop.is_set():
                raise ValueError("startup interrupted")
            port = self.config["serial_port"]
            baud = int(self.config.get("baud",2400))
            if not shared_timing_active() and self.stop.wait(61):
                raise ValueError("startup interrupted")
            tx,frame = reader(port,baud,address,timeout=5)
            read_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
            self._recovery_log(tx,frame)
            decoded = validate(frame)
            try:
                self._verify_recovery(decoded,address,meter_id)
            except ValueError as normal_error:
                if (decoded.get("address") != address or decoded.get("control") not in (8,24)
                        or decoded.get("meter_id") != meter_id or decoded.get("manufacturer") != "LUG"):
                    raise normal_error
                try:
                    extract_months(frame,meter_id)
                except ValueError:
                    try:
                        extract_monthly_set_day(frame,address,meter_id)
                    except ValueError:
                        if not self._confirmed_archive(decoded,address,meter_id):
                            raise normal_error from None
                if len(selected) != 1:
                    raise ValueError("interface restore requires exactly one selected meter")
                if self.stop.is_set():
                    raise ValueError("startup interrupted")
                self.root.mkdir(parents=True,exist_ok=True)
                with self.marker.open("w") as guard:
                    json.dump({"operation":"startup_normal"},guard)
                    guard.flush()
                    os.fsync(guard.fileno())
                fd = os.open(self.root,os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                if not shared_timing_active() and self.stop.wait(61):
                    raise ValueError("startup interrupted")
                LOG.info("Startup: confirmed historical frame; selecting normal telegram")
                self._restore_interface(port,baud,address)
                if not shared_timing_active() and self.stop.wait(61):
                    raise ValueError("startup interrupted")
                tx,frame = reader(port,baud,address,timeout=5)
                read_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
                self._recovery_log(tx,frame)
                decoded = validate(frame)
                self._verify_recovery(decoded,address,meter_id)
            readings.append((meter_id,address,decoded,read_at))
            LOG.info("Startup: normal telegram verified at primary address %d",address)
        self.startup_readings = readings

    def take_startup_readings(self):
        readings, self.startup_readings = self.startup_readings, []
        return readings

    def recover_normal(self, reader=read_one):
        """Read first; restore a confirmed interrupted app-owned archive or explicitly permitted historical frame."""
        if not self.blocked.is_set():
            return True
        try:
            with self.bus_lock, self.registry.lock:
                selected = list(self.registry.selected.items())
                try:
                    owned = json.loads(self.marker.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    owned = None
                if not selected:
                    return False
                if self.startup_pending:
                    self._initialize_normal(selected,reader)
                    self.marker.unlink(missing_ok=True)
                    self.startup_pending = False
                    self.blocked.clear()
                    with self.lock:
                        self.state = {"status":"recovered","error":None,"captured_at_utc":None}
                    LOG.info("Startup initialization complete; polling enabled")
                    return True
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
                            try:
                                extract_monthly_set_day(frame, address, meter_id)
                            except ValueError:
                                if not self._confirmed_archive(decoded,address,meter_id):
                                    raise normal_error from None
                        LOG.warning("Recovery confirmed non-normal frame for selected meter")
                        app_owned = (owned == {"operation":"archive_frame4","meter_id":meter_id,"address":address}
                                     and self._confirmed_archive(decoded,address,meter_id))
                        if not app_owned and self.config.get("allow_recovery_interface_reset") is not True:
                            raise ValueError("historical frame confirmed; interface restore disabled")
                        if app_owned:
                            LOG.info("Restoring interrupted app-owned archive to normal frame")
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

    def migration_status(self, meter_id):
        try:
            saved = json.loads(history_file(self.root, meter_id).read_text(encoding="utf-8"))
            version = saved.get("schema_version")
            return {2: "pending", 3: "complete"}.get(version, "invalid")
        except FileNotFoundError:
            return "no_history"
        except (OSError, ValueError, AttributeError):
            return "invalid"

    def migrate(self, meter_id):
        """Explicit local-only job, serialized against history collection."""
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("history collection running")
            with self.registry.lock:
                if meter_id not in self.registry.selected:
                    raise ValueError("meter not selected")
            path = history_file(self.root, meter_id)
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("schema_version") == 3:
                raise ValueError("migration already completed")
            snapshot = migrate_snapshot(old)
            save_snapshot(path, snapshot)
            self.state = {"status": "complete", "error": None,
                          "captured_at_utc": snapshot["captured_at_utc"]}
        if self.on_complete:
            try:
                self.on_complete(meter_id, snapshot)
            except (OSError, ValueError, ConnectionError, RuntimeError):
                LOG.warning("Migration saved; MQTT publication pending")
        return snapshot

    def start_extended_archive(self, meter_id, *, confirmed=False):
        """Manual, resumable extended archive. No automatic caller."""
        if confirmed is not True or self.config.get("allow_monthly_history") is not True:
            raise ValueError("monthly archive requires confirmation and enabled history")
        if not shared_timing_active():
            raise ValueError("shared bus timing required")
        with self.lock:
            if self.state["status"] == "running" or self.stop.is_set() or self.blocked.is_set():
                raise ValueError("history unavailable")
            if self.migration_status(meter_id) != "complete":
                raise ValueError("retrieve ordinary monthly history first")
            self.state = {"status":"running","error":None,"captured_at_utc":None}
            self.archive_meter = meter_id
            self.archive_progress = {str(i):"waiting" for i in range(1,25)}
            self.archive_revision += 1
            self.worker = threading.Thread(target=self._extended_archive_worker,args=(meter_id,),daemon=True)
            self.worker.start()

    def _archive_row(self, position, status):
        with self.lock:
            self.archive_progress[str(position)] = status
            self.archive_revision += 1

    def _extended_archive_worker(self, meter_id):
        position = None
        try:
            path = history_file(self.root,meter_id)
            saved = json.loads(path.read_text(encoding="utf-8"))
            for row in saved["stands"]:
                if self.stop.is_set():
                    raise ValueError("archive stopped")
                position = row["month_back"]
                evidence = row.get("frame4") or {}
                maxima = evidence.get("maxima") or {}
                if (evidence.get("cumulative_m3") is not None and evidence.get("meter_storage_local_time")
                    and all(maxima.get(k,{}).get("value") is not None and
                            maxima.get(k,{}).get("meter_local_time") and maxima.get(k,{}).get("read_at_utc")
                            for k in ("power","flow","flow_temperature","return_temperature"))):
                    self._archive_row(position,"stored")
                    continue
                self._archive_row(position,"request")
                LOG.info("Extended archive: requesting position %d/24",position)
                saved = self.collect_archive_dev(meter_id,position,approved=True,_reserved=True)
                self._archive_row(position,"completed")
                LOG.info("Extended archive: position %d/24 validated and saved",position)
            with self.lock:
                self.state = {"status":"complete","error":None,"captured_at_utc":saved["captured_at_utc"]}
        except Exception as exc:
            if position is not None:
                self._archive_row(position,"failed")
            LOG.warning("Extended archive stopped at position %s: %s",position,type(exc).__name__)
            with self.lock:
                self.state = {"status":"restore_unverified" if self.blocked.is_set() or self.marker.exists() else "failed",
                              "error":"Extended archive stopped; previously saved data retained",
                              "captured_at_utc":None}

    def collect_archive_dev(self, meter_id, month_back, *, approved=False, reader=None, _reserved=False):
        """Single dev transaction only. No GUI, polling or startup caller.
        Explicit approval and shared timing mandatory; serialize against all
        collection and retain the existing durable normal-frame guard on failure.
        """
        if approved is not True or not shared_timing_active():
            raise ValueError("archive dev acquisition requires approval and shared timing")
        if self.config.get("allow_monthly_history") is not True:
            raise ValueError("monthly history disabled")
        if type(month_back) is not int or not 1 <= month_back <= 24:
            raise ValueError("invalid month")
        if reader is None:
            from archive_serial import read_archive
            reader = read_archive
        with self.lock:
            if (self.state["status"] == "running" and not _reserved) or self.stop.is_set() or self.blocked.is_set():
                raise ValueError("history unavailable")
            self.state = {"status":"running","error":None,"captured_at_utc":None}
        try:
            with self.bus_lock:
                with self.registry.lock:
                    address = self.registry.selected.get(meter_id)
                    if address is None or self.stop.is_set() or self.blocked.is_set():
                        raise ValueError("selected meter unavailable")
                path = history_file(self.root,meter_id)
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved.get("schema_version") != 3:
                    raise ValueError("migration required")
                if len(saved.get("stands",[])) != 24 or len(saved.get("bounded_periods",[])) != 23:
                    raise ValueError("incomplete existing history")
                self.root.mkdir(parents=True,exist_ok=True)
                with self.marker.open("w") as guard:
                    json.dump({"operation":"archive_frame4","meter_id":meter_id,"address":address},guard)
                    guard.flush()
                    os.fsync(guard.fileno())
                fd = os.open(self.root,os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                try:
                    updated = reader(saved,self.config["serial_port"],
                        int(self.config.get("baud",2400)),address,meter_id,month_back,
                        approved=True)
                    self.marker.unlink()
                except ArchiveDataError:
                    self.marker.unlink()
                    raise
                except Exception:
                    self.blocked.set()
                    raise
                with self.registry.lock:
                    if self.registry.selected.get(meter_id) != address:
                        raise ValueError("selected meter changed")
                    save_snapshot(path,updated)
            if self.on_complete:
                try:
                    self.on_complete(meter_id,updated)
                except (OSError,ValueError,ConnectionError,RuntimeError):
                    LOG.warning("Archive saved; MQTT publication pending")
            with self.lock:
                self.state = {"status":"running" if _reserved else "complete","error":None,
                              "captured_at_utc":updated["captured_at_utc"],
                              "archive_position":month_back}
            return updated
        except Exception:
            with self.lock:
                self.state = {"status":"restore_unverified" if self.marker.exists() else "failed",
                              "error":"Archive collection failed; existing history preserved",
                              "captured_at_utc":None}
            raise

    def start(self, meter_id, *, replace=False, settings_only=False):
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
            if self.migration_status(meter_id) in ("pending", "invalid"):
                raise ValueError("migrate saved history before collection")
            self.state = {"status": "running", "error": None, "captured_at_utc": None}
            self.archive_progress = {}
            self.archive_meter = None
            self.archive_revision += 1
            self.worker = threading.Thread(target=self._collect, args=(meter_id, address, replace, settings_only), daemon=True)
            self.worker.start()

    def _collect(self, meter_id, address, replace=False, settings_only=False):
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
                    kwargs = {"settings_only": True} if settings_only else {}
                    result = self.reader(self.config["serial_port"], int(self.config.get("baud", 2400)),
                                         address, meter_id, **kwargs)
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
                if settings_only:
                    if not observation or not observation.get("monthly_set_day"):
                        raise ValueError("monthly storage configuration unavailable")
                    path = history_file(self.root, meter_id)
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    if saved.get("schema_version") != 3:
                        raise ValueError("migration required")
                    saved["monthly_set_day"] = observation["monthly_set_day"]
                    saved["configuration_read_at_utc"] = captured_at
                    if observation.get("error_history") is not None:
                        saved["error_history"] = observation["error_history"]
                    save_snapshot(path, saved)
                    if self.on_complete:
                        try:
                            self.on_complete(meter_id, saved)
                        except (OSError, ValueError, ConnectionError):
                            LOG.warning("Configuration saved but MQTT publication failed")
                    with self.lock:
                        self.state = {"status": "complete", "error": None, "captured_at_utc": saved["captured_at_utc"]}
                    return
                trust_file = self.root / ("clock-trust-" + device_key(meter_id) + ".json")
                try:
                    trust_record = json.loads(trust_file.read_text(encoding="utf-8"))
                    clock_trusted = trust_record.get("status") == "verified"
                except (OSError, ValueError):
                    trust_record, clock_trusted = {}, False
                estimated_month = estimated_month_at_capture(
                    captured_at, observation, clock_trusted,
                    self.config.get("clock_timezone", "Europe/Oslo"), history_read_at)
                setting_requested = observation is not None and "monthly_set_day" in observation
                configured = configured_anchor(observation, history_read_at,
                    self.config.get("clock_timezone", "Europe/Oslo")) if setting_requested else None
                if setting_requested:
                    estimated_month = None
                snapshot = build_snapshot(months, captured_at, estimated_month, configured)
                snapshot["monthly_set_day"] = observation.get("monthly_set_day") if observation else None
                snapshot["configuration_read_at_utc"] = captured_at
                snapshot["date_provenance"] = {
                    "history_read_at_utc": history_read_at,
                    "normal_read_at_utc": observation.get("last_successful_read_utc") if observation else None,
                    "meter_local_time_at_normal": observation.get("meter_local_time") if observation else None,
                    "meter_summer_time_at_normal": observation.get("meter_summer_time") if observation else None,
                    "clock_trusted_at_capture": clock_trusted,
                    "clock_trust_verified_at_utc": trust_record.get("at_utc") if clock_trusted else None,
                    "timezone_assumed": self.config.get("clock_timezone", "Europe/Oslo"),
                    "rule": "current monthly set day; not independently read storage time" if setting_requested else "legacy first-of-month estimate",
                    "estimate_applied": estimated_month is not None or configured is not None,
                }
                path = history_file(self.root, meter_id)
                try:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    previous = None
                if observation and observation.get("error_history") is not None:
                    snapshot["error_history"] = observation["error_history"]
                elif previous and "error_history" in previous:
                    snapshot["error_history"] = previous["error_history"]
                snapshot["rollover_evidence"] = (
                    "confirmed_shift" if detect_month_shift(previous, snapshot) else "not_observed")
                snapshot = merge_history(previous, snapshot, history_read_at or captured_at, replace=replace)
                snapshot["schema_version"] = 3
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
