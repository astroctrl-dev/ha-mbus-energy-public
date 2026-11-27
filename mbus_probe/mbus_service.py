"""Read-only, sequential M-Bus polling for selected T230 meters."""
import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from analysis_export import append_sample, make_sample
from pathlib import Path
from contextlib import nullcontext

from poll_schedule import next_aligned_poll_wait
from raw_telegram_log import RawLog, install
from bus_timing import BusTiming, install_bus_timing, MissedSlot, poll_slot, slot_tolerance, slot_open
from maintenance_schedule import MaintenanceSchedule
from clock_model import assess_clock
from dst_transition import TransitionStore

from ha_measurements import SENSORS, select_measurements
from mbus_probe import read_one, validate
from mqtt_bridge import (BRIDGE_AVAILABILITY, cleanup_discovery,
                         mark_unavailable, publish_reading, publish_dst_diagnostics)
from meter_registry import MeterRegistry
from address_journal import AddressJournal
from owned_bus_lock import OwnedBusLock
from meter_ui import serve
from history_controller import load_history
from mqtt_bridge import publish_history, publish_monthly_retry
from monthly_retry import MonthlyRetry

LOG = logging.getLogger("mbus")
STOP = threading.Event()
_STATUS_10_LOGGED = False  # One informational warning per process start.
_ANALYSIS_SAVE_ERROR_LOGGED = False


class RequestPacer:
    """Persist the last attempted normal read so a restart cannot poll immediately."""

    def __init__(self, path="/data/analysis/last_bus_request", clock=time.time):
        self.path = Path(path)
        self.clock = clock

    def before_request(self, stop):
        try:
            last = float(self.path.read_text(encoding="ascii"))
            if not 0 <= last < 1e12:
                raise ValueError("invalid last request time")
        except FileNotFoundError:
            last = None
        now = self.clock()
        # Missing/corrupt clock provenance must never shorten the interval.
        delay = 60.0 if last is None or now < last else max(0.0, 60.0 - (now - last))
        if stop.wait(delay):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="ascii") as stream:
                stream.write(str(self.clock()) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()
        return True


def load_config(path="/data/options.json"):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config.get("serial_port"), str) or not config["serial_port"].startswith("/dev/"):
        raise ValueError("select a serial device in the app options")
    if not config.get("mqtt_host") or not isinstance(config["mqtt_host"], str):
        raise ValueError("mqtt_host is required")
    # Obsolete options cannot select a meter in v3.0.0.
    config.pop("address", None)
    config.pop("meter_id", None)
    if int(config.get("interval_seconds", 120)) not in (60, 90, 120, 300, 600):
        raise ValueError("interval_seconds must be one of 60, 90, 120, 300, 600")
    if not isinstance(config.get("allow_clock_sync", False), bool) or not isinstance(config.get("auto_clock_sync", False), bool):
        raise ValueError("clock sync options must be boolean")
    # Legacy options must never override the HA wall-clock policy.
    config.pop("use_daylight_saving_time", None)
    if config.get("auto_clock_sync") and not config.get("allow_clock_sync"):
        raise ValueError("auto_clock_sync requires allow_clock_sync")
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    # Supervisor supplies the HA IANA timezone. Retain configured fallback for standalone use.
    config["clock_timezone"] = os.environ.get("TZ") or config.get("clock_timezone", "Europe/Oslo")
    try:
        ZoneInfo(config.get("clock_timezone", "Europe/Oslo"))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError("invalid clock_timezone")
    if not isinstance(config.get("allow_address_diagnostic", False), bool):
        raise ValueError("allow_address_diagnostic must be boolean")
    if not isinstance(config.get("allow_diagnostic_capture", False), bool):
        raise ValueError("allow_diagnostic_capture must be boolean")
    if not isinstance(config.get("allow_monthly_history", False), bool):
        raise ValueError("allow_monthly_history must be boolean")
    if not isinstance(config.get("auto_monthly_history", False), bool):
        raise ValueError("auto_monthly_history must be boolean")
    if config.get("auto_monthly_history") and not config.get("allow_monthly_history"):
        raise ValueError("auto_monthly_history requires allow_monthly_history")
    if not isinstance(config.get("read_before_full_hour", False), bool):
        raise ValueError("read_before_full_hour must be boolean")
    delay = config.get("seconds_before_full_hour", 5)
    if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= 300:
        raise ValueError("seconds_before_full_hour must be an integer 0..300")
    for key in ('log_measurement_data', 'raw_telegram_logging'):
        if not isinstance(config.get(key, key == 'log_measurement_data'), bool):
            raise ValueError(key + ' must be boolean')
    return config


def poll_once(config, client):
    tx, rx = read_one(config.get("serial_port", "/dev/ttyUSB0"),
                      int(config.get("baud", 2400)),
                      int(config.get("address", 0)), timeout=4)
    return publish_normal(config,client,validate(rx))


def publish_normal(config,client,decoded,read_at_utc=None):
    global _STATUS_10_LOGGED, _ANALYSIS_SAVE_ERROR_LOGGED
    if decoded.get("address") != int(config.get("address", 0)):
        raise ValueError("response primary address mismatch")
    # Frame identity is mandatory; individual measurement errors stay isolated.
    selected = select_measurements(decoded, config["meter_id"])
    if decoded.get("status") == 0x10 and not _STATUS_10_LOGGED:
        _STATUS_10_LOGGED = True
        LOG.warning(
            "T230 meter at primary address %d status=0x10 observed. Its meaning is not conclusively "
            "identified as a fault; valid measurements are published with "
            "quality warning. This status may recur on subsequent reads. "
            "Intentionally logging only its first occurrence per app start "
            "to avoid flooding the log.", int(config.get("address", 0))
        )
    read_at_utc = read_at_utc or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    clock_attributes = assess_clock(decoded, read_at_utc, config.get("clock_timezone", "Europe/Oslo"))
    publish_reading(client, decoded, config["meter_id"], read_at_utc=read_at_utc,
                    clock_attributes=clock_attributes)
    diagnostic = config.get("_diagnostic_runtime")
    if diagnostic is not None:
        try:
            from mbus_records import passive_diagnostics
            from mqtt_bridge import publish_active_diagnostics
            diagnostic.observe_normal(config["meter_id"], passive_diagnostics(decoded)["extension_byte"], read_at_utc)
            raw, stamp = diagnostic.evidence(config["meter_id"])
            publish_active_diagnostics(client, config["meter_id"], raw, stamp,
                                       layout_verified=raw is not None, now=diagnostic.now())
        except (OSError, ValueError, ConnectionError, RuntimeError):
            LOG.warning("Active diagnostic publication failed; ordinary readings preserved")
    observer = config.get("_clock_observer")
    if observer:
        observer(config["meter_id"], dict(clock_attributes, observed_at_utc=read_at_utc))
    try:
        state = TransitionStore("/data/analysis", config["meter_id"]).load()
    except (OSError, ValueError, TypeError):
        state = {"state_status": "unavailable"}
    try:
        publish_dst_diagnostics(client, config["meter_id"], state)
    except (OSError, ConnectionError, RuntimeError):
        LOG.warning("DST diagnostic publication failed; ordinary readings preserved")
    try:
        import hashlib
        key = "history:" + hashlib.sha256(config["meter_id"].encode()).hexdigest()
        publish_monthly_retry(client, config["meter_id"], MonthlyRetry("/data/analysis").alarm(key))
    except (OSError, ValueError, ConnectionError, RuntimeError):
        LOG.warning("Monthly history diagnostic publication failed; ordinary readings preserved")
    if not config.get('log_measurement_data', True):
        return selected
    try:
        sample = make_sample(decoded, config["meter_id"],
                             read_at_utc,
                             "/data/analysis/alias.key", validated=selected)
        append_sample("/data/analysis/normal.jsonl", sample)
        _ANALYSIS_SAVE_ERROR_LOGGED = False
    except (OSError, ValueError) as exc:
        if not _ANALYSIS_SAVE_ERROR_LOGGED:
            _ANALYSIS_SAVE_ERROR_LOGGED = True
            LOG.warning("Analysis sample could not be saved: %s", type(exc).__name__)
    return selected


def run(config, client, registry=None, bus_lock=None, history_controller=None,
        request_pacer=None, on_valid_round=None, timing=None):
    """Fail closed on any bad poll. MQTT Last Will also handles abrupt termination."""
    def wait_slot():
        now = time.time()
        delay = next_aligned_poll_wait(config.get("interval_seconds", 120),
                                       config.get("read_before_full_hour", False),
                                       config.get("seconds_before_full_hour", 5), now=now)
        target = now + delay
        if registry and timing:
            # Wake promptly when a new meter is selected, without sending
            # outside the common transmission gate.
            while not STOP.is_set():
                ids = {row["meter_id"] for row in registry.snapshot()["selected"]}
                if ids - attempted_meters:
                    return None
                remaining = target - time.time()
                if remaining <= 0:
                    break
                STOP.wait(min(1.0, remaining))
        else:
            STOP.wait(delay)
        return target

    attempted_meters = set()
    target = None
    last_served = None
    while not STOP.is_set():
        if timing and ((getattr(timing, 'address_blocked', None) and timing.address_blocked())
                       or (getattr(timing, 'diagnostic_guard', None) and timing.diagnostic_guard.blocked())):
            client.publish(BRIDGE_AVAILABILITY, 'offline', qos=1, retain=True)
            STOP.wait(5)
            continue
        if history_controller and history_controller.blocked.is_set():
            client.publish(BRIDGE_AVAILABILITY, "offline", qos=1, retain=True)
            if history_controller.recover_normal():
                client.publish(BRIDGE_AVAILABILITY, "online", qos=1, retain=True)
                for meter_id,address,decoded,read_at in getattr(history_controller,"take_startup_readings",lambda:[])():
                    try:
                        with bus_lock if bus_lock else nullcontext():
                            if STOP.is_set() or history_controller.blocked.is_set():
                                continue
                            if registry:
                                with registry.lock:
                                    if registry.selected.get(meter_id) != address:
                                        continue
                            if history_controller.migration_status(meter_id) in ("pending","invalid"):
                                continue
                            values = publish_normal(dict(config,meter_id=meter_id,address=address),
                                                    client,decoded,read_at)
                        attempted_meters.add(meter_id)
                        last_served = meter_id
                        LOG.info("Startup: published verified normal frame (%d measurements)",len(values))
                    except (OSError,ValueError,ConnectionError,RuntimeError):
                        LOG.warning("Startup publication failed; retry by ordinary polling")
                        mark_unavailable(client,meter_id)
            else:
                STOP.wait(120)
            if timing:
                target = wait_slot()
            continue
        if registry:
            for meter_id in list(registry.pending_cleanup):
                try:
                    with bus_lock, registry.lock:
                        if meter_id not in registry.pending_cleanup or meter_id in registry.selected:
                            continue
                        cleanup_discovery(client, meter_id)
                        registry.cleanup_done(meter_id)
                except (OSError, ValueError, ConnectionError, RuntimeError) as exc:
                    LOG.warning("Pending MQTT cleanup failed: %s", exc)
        selections = (registry.snapshot()["selected"] if registry else
                      [{"meter_id": config["meter_id"], "address": config.get("address", 0)}])
        if timing and selections and last_served is not None:
            # With a conservative bus-wide gate, rotate meters instead of
            # starving every meter after the first one in the registry.
            ids = [row["meter_id"] for row in selections]
            if last_served in ids:
                index = ids.index(last_served) + 1
                selections = selections[index:] + selections[:index]
        attempted_meters.intersection_update(row['meter_id'] for row in selections)
        valid_meter_ids = []
        for row in selections:
            if history_controller and hasattr(history_controller, "migration_status") and history_controller.migration_status(row["meter_id"]) in ("pending", "invalid"):
                attempted_meters.add(row["meter_id"])
                continue
            meter_config = dict(config, meter_id=row["meter_id"], address=row["address"])
            try:
                with bus_lock if bus_lock else nullcontext():
                    if STOP.is_set() or (history_controller and history_controller.blocked.is_set()):
                        continue
                    if registry:
                        with registry.lock:
                            if registry.selected.get(row["meter_id"]) != row["address"]:
                                continue
                    priority = timing is not None and row["meter_id"] not in attempted_meters
                    tolerance = slot_tolerance(config.get('read_before_full_hour', False), target)
                    if timing and not priority and (not timing.ready() or not slot_open(target, time.time(), tolerance)):
                        LOG.info("Scheduled polling slot skipped: bus busy or slot elapsed")
                        continue
                    if request_pacer and not request_pacer.before_request(STOP):
                        continue
                    attempted_meters.add(row['meter_id'])
                    with poll_slot(target, tolerance) if timing and not priority else nullcontext():
                        if timing:
                            last_served = row["meter_id"]
                        values = poll_once(meter_config, client)
                LOG.info("Valid T230 frame: %d current measurements, %d unavailable",
                         len(values), len(SENSORS) - len(values))
                valid_meter_ids.append(row["meter_id"])
            except MissedSlot:
                LOG.info("Scheduled polling slot skipped at serial transmission")
            except (OSError, ValueError, ConnectionError, RuntimeError) as exc:
                LOG.warning("T230 unavailable at primary address %d: %s", row["address"], exc)
                try:
                    mark_unavailable(client, row["meter_id"])
                except (OSError, ValueError, ConnectionError, RuntimeError) as mqtt_error:
                    LOG.warning("Cannot publish offline state: %s", mqtt_error)
        # Start optional clock checks only after every selected meter had its
        # chance to publish a fresh normal measurement in this round.
        if valid_meter_ids and on_valid_round:
            on_valid_round(valid_meter_ids)
        target = wait_slot()


def on_broker_connect(client, registry):
    """Keep stale values offline until each meter has a fresh valid read."""
    client.publish(BRIDGE_AVAILABILITY, "offline", qos=1, retain=True)
    for row in registry.snapshot()["selected"]:
        mark_unavailable(client, row["meter_id"])
    client.publish(BRIDGE_AVAILABILITY, "online", qos=1, retain=True)



def publish_saved_history(client, registry):
    """Run outside Paho's on_connect callback so PUBACKs can be processed."""
    try:
        for alias, snapshot in load_history("/data/analysis", registry.snapshot()["selected"]):
            # Match saved alias to the selected meter without exposing its ID.
            from history_controller import history_file
            for row in registry.snapshot()["selected"]:
                if history_file("/data/analysis", row["meter_id"]).stem == alias:
                    publish_history(client, row["meter_id"], snapshot)
                    break
        return True
    except (OSError, ValueError, ConnectionError, RuntimeError):
        LOG.warning("Saved monthly history could not be published; retry pending")
        return False


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    fresh = (not Path('/data/analysis').exists() and not Path('/data/meters.json').exists()
             and not Path('/data/address-change.json').exists()
             and not Path('/data/address-diagnostic.json').exists())
    registry = MeterRegistry()
    journal = AddressJournal('/data/address-change.json')
    def address_blocked():
        # Conservative bus-wide quarantine until targeted recovery is verified.
        with registry.lock:
            return journal.blocked() or registry.persistence_failed or bool(registry.quarantined)
    from address_diagnostic import DiagnosticGuard
    diagnostic_guard = DiagnosticGuard('/data/address-diagnostic.json')
    timing = BusTiming(resume=True, fresh=fresh, address_blocked=address_blocked, diagnostic_guard=diagnostic_guard)
    install_bus_timing(timing)
    bus_lock = OwnedBusLock()
    import paho.mqtt.client as mqtt
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id="mbus_t230_bridge")
    history_publish_lock = threading.Lock()
    def on_connect(mqtt_client, _userdata, _flags, reason_code, _properties):
        if not reason_code.is_failure:
            on_broker_connect(mqtt_client, registry)
            if history_publish_lock.acquire(blocking=False):
                def republish():
                    try:
                        while not STOP.is_set():
                            if publish_saved_history(mqtt_client, registry):
                                break
                            if STOP.wait(120):
                                break
                    finally:
                        history_publish_lock.release()
                threading.Thread(target=republish, daemon=True).start()
    client.on_connect = on_connect
    username = config.get("mqtt_username")
    if username:
        client.username_pw_set(username, config.get("mqtt_password") or None)
    client.will_set(BRIDGE_AVAILABILITY, "offline", qos=1, retain=True)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: STOP.set())
    client.connect(config["mqtt_host"], int(config.get("mqtt_port", 1883)),
                   keepalive=60)
    client.loop_start()
    raw_log = RawLog()
    raw_log.set_enabled(config.get('raw_telegram_logging', False))
    install(raw_log)
    from history_controller import HistoryController
    history_controller = HistoryController(registry,config,bus_lock,STOP,
        on_complete=lambda meter_id,snapshot: publish_history(client,meter_id,snapshot))
    history_controller.require_startup_normal()
    from diagnostic_runtime import DiagnosticRuntime
    # Release candidate: strict observed firmware layout only.
    config["_frame5_layout_approved"] = True
    config["_diagnostic_runtime"] = DiagnosticRuntime(
        root="/data/analysis" if config.get("_frame5_layout_approved") is True else None)
    from address_runtime import build_read_only_jobs
    address_search_job, address_change_job = build_read_only_jobs(config,registry,timing,bus_lock,STOP)
    def diagnostic_factory(admission,history_blocked):
        from address_diagnostic_job import AddressDiagnosticJob
        from address_runtime import run_isolated_diagnostic
        def runner(**kwargs):
            return run_isolated_diagnostic(config,registry,timing,bus_lock,STOP,admission,**kwargs)
        return AddressDiagnosticJob(runner,diagnostic_guard,STOP,history_blocked,
                                    enabled=config.get("allow_address_diagnostic") is True,
                                    recovery_history_blocked=lambda: history_controller.marker.exists() or
                                    (history_controller.blocked.is_set() and not history_controller.startup_pending))
    server = serve(registry, config, client, bus_lock, STOP, raw_log=raw_log,
                   address_diagnostic_factory=diagnostic_factory,
                   address_search_job=address_search_job, address_change_job=address_change_job,
                   history_controller=history_controller, address_safety_blocked=lambda: address_blocked() or diagnostic_guard.blocked())
    maintenance = MaintenanceSchedule(config, server.clock_controller, server.history_controller, STOP)
    config["_clock_observer"] = maintenance.observe_clock
    def valid_round(meter_ids):
        maintenance.on_valid_round(meter_ids)
    try:
        run(config, client, registry, bus_lock, server.history_controller, None,
            valid_round, timing=timing)
    finally:
        try:
            server.shutdown()
            for row in registry.snapshot()["selected"]:
                mark_unavailable(client, row["meter_id"]).wait_for_publish(timeout=5)
            client.publish(BRIDGE_AVAILABILITY, "offline", qos=1, retain=True).wait_for_publish(timeout=5)
        finally:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
