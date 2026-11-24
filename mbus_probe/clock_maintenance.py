"""Manual T230 clock synchronization over wired M-Bus.

No clock command runs from ordinary polling or history export.
"""
import logging
import threading
import time
import json
import os
from pathlib import Path
from mqtt_bridge import device_key
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from clock_model import clock_observation
from ha_measurements import select_measurements
from mbus_probe import read_one, validate

LOG = logging.getLogger("mbus.clock")


def encode_type_f(local):
    """EN 13757 data type F: minute, hour/DST, day/year, month/year."""
    if local.tzinfo is None or local.utcoffset() is None:
        raise ValueError("timezone-aware clock required")
    year = local.year - 2000
    if not 0 <= year <= 99:
        raise ValueError("meter year outside 2000..2099")
    return bytes((local.minute,
                  local.hour | (0x80 if local.dst() else 0),
                  local.day | ((year & 7) << 5),
                  local.month | ((year >> 3) << 4)))


def set_clock_frame(address, local):
    if type(address) is not int or not 0 <= address <= 250:
        raise ValueError("invalid primary address")
    body = bytes((0x53, address, 0x51, 0x04, 0x6D)) + encode_type_f(local)
    return bytes((0x68, len(body), len(body), 0x68)) + body + bytes((sum(body) & 255, 0x16))


def _read_clock(port, baud, address, meter_id, reader):
    _request, response = reader(port, baud, address, timeout=5)
    decoded = validate(response)
    if decoded.get("address") != address:
        raise ValueError("meter address mismatch")
    select_measurements(decoded, meter_id)
    return clock_observation(decoded, datetime.now(timezone.utc).isoformat())


def sync_once(port, baud, address, meter_id, zone_name, *, reader=read_one,
              sleep=time.sleep, now=lambda: datetime.now(timezone.utc),
              serial_factory=None, on_write=None, auto=False, allow_auto_write=False):
    """Read, write once, then read back. An ACK alone never counts as success."""
    if baud not in (300, 2400):
        raise ValueError("unsupported baud rate")
    zone = ZoneInfo(zone_name)
    before = _read_clock(port, baud, address, meter_id, reader)
    old = datetime.fromisoformat(before["meter_local_time"]).replace(tzinfo=zone)
    current = now().astimezone(zone)
    if auto and abs((current - old).total_seconds()) <= 120:
        return {"before": before["meter_local_time"], "target": None,
                "after": before["meter_local_time"], "changed": False,
                "manual_required": before["meter_summer_time"] != bool(current.dst()),
                "verified_at_utc": now().astimezone(timezone.utc).isoformat(timespec="seconds")}
    if auto and (not allow_auto_write or abs((current - old).total_seconds()) > 300):
        return {"before": before["meter_local_time"], "target": None,
                "after": before["meter_local_time"], "changed": False,
                "manual_required": True,
                "verified_at_utc": now().astimezone(timezone.utc).isoformat(timespec="seconds")}
    sleep(61)  # Battery-powered meter; no back-to-back requests.
    target = now().astimezone(zone)
    command = set_clock_frame(address, target)
    if serial_factory is None:
        import serial
        serial_factory = serial.Serial
    if on_write:
        on_write(before["meter_local_time"], target.isoformat(timespec="minutes"))
    with serial_factory(port, baudrate=baud, bytesize=8, parity="E", stopbits=1,
                        timeout=5, write_timeout=5, exclusive=True) as ser:
        ser.reset_input_buffer()
        ser.write(command)
        ser.flush()
        if ser.read(1) != b"\xe5":
            raise ValueError("clock command not acknowledged")
    sleep(61)
    after = _read_clock(port, baud, address, meter_id, reader)
    actual = datetime.fromisoformat(after["meter_local_time"]).replace(tzinfo=zone)
    expected = now().astimezone(zone)
    drift = abs((expected - actual).total_seconds())
    if drift > 120 or after["meter_summer_time"] != bool(target.dst()):
        raise ValueError("clock readback differs from target")
    return {"before": before["meter_local_time"],
            "target": target.isoformat(timespec="minutes"), "changed": True,
            "manual_required": False,
            "after": after["meter_local_time"],
            "verified_at_utc": now().astimezone(timezone.utc).isoformat(timespec="seconds")}


class ClockController:
    def __init__(self, registry, config, bus_lock, stop, operation=sync_once, pause=time.sleep,
                 history_blocked=None, root="/data/analysis",
                 now=lambda: datetime.now(timezone.utc)):
        self.registry, self.config, self.bus_lock, self.stop = registry, config, bus_lock, stop
        self.operation, self.pause, self.history_blocked = operation, pause, history_blocked
        self.root = Path(root)
        self.lock = threading.Lock()
        self.state = {"status": "not_started", "error": None, "result": None}
        self.worker = None
        self.auto_pending = set()
        self.auto_ready = []
        self.auto_worker = None
        self.now = now
        self.daily_slots = {}
        self.daily_retry_at = {}

    def defer_auto(self, meter_id):
        """Wait for a fresh normal measurement before reserving the bus."""
        if self.config.get("auto_clock_sync"):
            with self.lock:
                self.auto_pending.add(meter_id)

    def on_valid_round(self, meter_ids):
        """Called after all selected meters complete a normal polling round."""
        if self.stop.is_set() or not self.config.get('auto_clock_sync') or not self.config.get('allow_clock_sync'):
            return
        local = self.now().astimezone(ZoneInfo(self.config.get('clock_timezone', 'Europe/Oslo')))
        with self.lock:
            for meter_id in meter_ids:
                if (local.hour >= 23 and self.daily_slots.get(meter_id) != local.date()
                        and self.now().timestamp() >= self.daily_retry_at.get(meter_id, 0)):
                    self.daily_slots[meter_id] = local.date()
                    self.auto_pending.add(meter_id)
                if meter_id in self.auto_pending:
                    self.auto_pending.remove(meter_id)
                    if meter_id not in self.auto_ready:
                        self.auto_ready.append(meter_id)
            if self.auto_ready and (self.auto_worker is None or not self.auto_worker.is_alive()):
                self.auto_worker = threading.Thread(target=self._run_auto_queue, daemon=True)
                self.auto_worker.start()

    def _run_auto_queue(self):
        while not self.stop.is_set():
            with self.lock:
                if not self.auto_ready:
                    self.auto_worker = None
                    return
                meter_id = self.auto_ready.pop(0)
            try:
                self.start(meter_id, auto=True)
                self.worker.join()
                with self.lock:
                    if self.state['status'] == 'failed':
                        self.daily_slots.pop(meter_id, None)
                        self.daily_retry_at[meter_id] = self.now().timestamp() + 900
            except ValueError as exc:
                if str(exc) == "clock sync already running" and self.worker:
                    # A manual operation has priority; retry after it finishes.
                    self.worker.join()
                    with self.lock:
                        self.auto_ready.insert(0, meter_id)
                else:
                    with self.lock:
                        self.daily_slots.pop(meter_id, None)
                        self.daily_retry_at[meter_id] = self.now().timestamp() + 900
                    LOG.warning("Automatic clock check skipped: %s", type(exc).__name__)

    def _path(self, meter_id):
        return self.root / ("clock-trust-" + device_key(meter_id) + ".json")

    def _trusted(self, meter_id):
        try:
            return json.loads(self._path(meter_id).read_text(encoding="utf-8")).get("status") == "verified"
        except (OSError, ValueError):
            return False

    def _save(self, meter_id, status):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(meter_id)
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps({"status": status,
                                        "at_utc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, meter_id, auto=False):
        if auto and self.config.get("auto_clock_sync") is not True:
            return
        if self.config.get("allow_clock_sync") is not True:
            raise ValueError("Aktiver klokkesynkronisering i Configuration først")
        if self.stop.is_set() or (self.history_blocked and self.history_blocked.is_set()):
            raise ValueError("app is stopping")
        with self.registry.lock:
            address = self.registry.selected.get(meter_id)
            if address is None:
                raise ValueError("select a meter before clock sync")
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("clock sync already running")
            self.state = {"status": "running", "error": None, "result": None}
            self.worker = threading.Thread(target=self._run, args=(meter_id, address, auto), daemon=True)
            self.worker.start()

    def _run(self, meter_id, address, auto):
        write_attempted = False
        before_and_target = {}
        def on_write(before, target):
            nonlocal write_attempted
            self._save(meter_id, "unverified")  # Survives crash after a possible write.
            write_attempted = True
            before_and_target.update(before=before, target=target)
            LOG.info("Clock sync command initiated; before=%s target=%s",
                     before, target)
        try:
            with self.bus_lock:
                with self.registry.lock:
                    if self.registry.selected.get(meter_id) != address or self.stop.is_set():
                        raise ValueError("selected meter changed or app is stopping")
                self.pause(61)  # Previous normal poll/scan may have just finished.
                if self.stop.is_set() or (self.history_blocked and self.history_blocked.is_set()):
                    raise ValueError("app stopping or normal frame unverified")
                try:
                    result = self.operation(
                        self.config["serial_port"], int(self.config.get("baud", 2400)),
                        address, meter_id, self.config.get("clock_timezone", "Europe/Oslo"),
                        on_write=on_write, auto=auto,
                        allow_auto_write=self._trusted(meter_id))
                finally:
                    self.pause(61)  # Preserve spacing even after a failed read or write.
            if result["changed"]:
                self._save(meter_id, "verified")
            LOG.info("Clock check completed; changed=%s manual_required=%s before=%s target=%s after=%s",
                     result["changed"], result["manual_required"],
                     result["before"], result["target"], result["after"])
            with self.lock:
                self.state = {"status": ("manual_required" if result["manual_required"] else "verified"),
                              "error": "Stor tidsforskjell eller ingen manuell førstegongssynk; bruk knappen" if result["manual_required"] else None,
                              "result": result}
        except Exception as exc:
            # Never put meter identity, raw telegram or serial path in UI/logs.
            LOG.error("Clock sync failed: %s; write_attempted=%s",
                      type(exc).__name__, write_attempted)
            with self.lock:
                self.state = {
                    "status": "unverified" if write_attempted else "failed",
                    "error": "Klokka kan ha blitt endret; kontroller avlesningen" if write_attempted
                             else "Klokkesynkronisering feilet før skrivekommando",
                    "result": before_and_target or None}
