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

from poll_schedule import next_poll_wait

from ha_measurements import SENSORS, select_measurements
from mbus_probe import read_one, validate
from mqtt_bridge import (BRIDGE_AVAILABILITY, cleanup_discovery,
                         mark_unavailable, publish_reading)
from meter_registry import MeterRegistry
from meter_ui import serve
from history_controller import load_history
from mqtt_bridge import publish_history

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
        delay = 61.0 if last is None or now < last else max(0.0, 61.0 - (now - last))
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
    if not 0 <= int(config.get("address", 0)) <= 250:
        raise ValueError("address outside 0..250")
    if int(config.get("interval_seconds", 120)) not in (90, 120, 300, 600):
        raise ValueError("interval_seconds must be one of 90, 120, 300, 600")
    if not isinstance(config.get("allow_clock_sync", False), bool) or not isinstance(config.get("auto_clock_sync", False), bool):
        raise ValueError("clock sync options must be boolean")
    if config.get("auto_clock_sync") and not config.get("allow_clock_sync"):
        raise ValueError("auto_clock_sync requires allow_clock_sync")
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(config.get("clock_timezone", "Europe/Oslo"))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError("invalid clock_timezone")
    if not isinstance(config.get("allow_monthly_history", False), bool):
        raise ValueError("allow_monthly_history must be boolean")
    if not isinstance(config.get("read_before_full_hour", False), bool):
        raise ValueError("read_before_full_hour must be boolean")
    delay = config.get("seconds_before_full_hour", 5)
    if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= 300:
        raise ValueError("seconds_before_full_hour must be an integer 0..300")
    return config


def poll_once(config, client):
    global _STATUS_10_LOGGED, _ANALYSIS_SAVE_ERROR_LOGGED
    tx, rx = read_one(config.get("serial_port", "/dev/ttyUSB0"),
                      int(config.get("baud", 2400)),
                      int(config.get("address", 0)), timeout=4)
    decoded = validate(rx)
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
    read_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    publish_reading(client, decoded, config["meter_id"], read_at_utc=read_at_utc)
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
        request_pacer=None, on_valid_round=None):
    """Fail closed on any bad poll. MQTT Last Will also handles abrupt termination."""
    while not STOP.is_set():
        if history_controller and history_controller.blocked.is_set():
            client.publish(BRIDGE_AVAILABILITY, "offline", qos=1, retain=True)
            STOP.wait(5)
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
        valid_meter_ids = []
        for row in selections:
            meter_config = dict(config, meter_id=row["meter_id"], address=row["address"])
            try:
                with bus_lock if bus_lock else nullcontext():
                    if STOP.is_set() or (history_controller and history_controller.blocked.is_set()):
                        continue
                    if registry:
                        with registry.lock:
                            if registry.selected.get(row["meter_id"]) != row["address"]:
                                continue
                    if request_pacer and not request_pacer.before_request(STOP):
                        continue
                    values = poll_once(meter_config, client)
                LOG.info("Valid T230 frame: %d current measurements, %d unavailable",
                         len(values), len(SENSORS) - len(values))
                valid_meter_ids.append(row["meter_id"])
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
        STOP.wait(next_poll_wait(config.get("interval_seconds", 120),
                                 config.get("read_before_full_hour", False),
                                 config.get("seconds_before_full_hour", 5)))


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
    except (OSError, ValueError, ConnectionError):
        LOG.warning("Saved monthly history could not be published after broker reconnect")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    registry = MeterRegistry()
    registry.migrate_legacy(config.get("meter_id"), int(config.get("address", 0)))
    bus_lock = threading.Lock()
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
                        publish_saved_history(mqtt_client, registry)
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
    server = serve(registry, config, client, bus_lock, STOP)
    if config.get("auto_clock_sync"):
        for row in registry.snapshot()["selected"]:
            server.clock_controller.defer_auto(row["meter_id"])
    try:
        run(config, client, registry, bus_lock, server.history_controller, RequestPacer(),
            server.clock_controller.on_valid_round)
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
