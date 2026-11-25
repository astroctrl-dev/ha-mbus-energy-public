"""Single in-process transmission gate for the HA app.

All application serial writers pass through this gate. A conservative global
bus interval also protects the same meter if its address changes. Standalone
CLI usage outside the app must not share its serial device.
"""
from raw_telegram_log import capture
import logging
import os
import threading
import time
from pathlib import Path
from contextlib import contextmanager

LOG = logging.getLogger("mbus.bus")
MIN_INTERVAL = 61.0
_gate = None
_slot = threading.local()


class MissedSlot(RuntimeError):
    """No serial transmission was attempted for this expired poll."""


@contextmanager
def poll_slot(target):
    previous = getattr(_slot, 'target', None)
    _slot.target = target
    try:
        yield
    finally:
        _slot.target = previous


class BusTiming:
    def __init__(self, path="/data/analysis/last_bus_request",
                 monotonic=time.monotonic, wall=time.time, sleep=time.sleep):
        self.path = Path(path)
        self.monotonic, self.wall, self.sleep = monotonic, wall, sleep
        self.lock = threading.Lock()
        # A full startup guard is safe even after wall-clock adjustments or a
        # crash between persistence and serial transmission.
        self.eligible = monotonic() + MIN_INTERVAL

    def ready(self):
        return self.monotonic() >= self.eligible

    def write(self, serial, frame):
        with self.lock:
            target = getattr(_slot, 'target', None)
            if target is not None and (not self.ready() or not 0 <= self.wall() - target <= 1):
                raise MissedSlot('bus not eligible at planned slot')
            while self.monotonic() < self.eligible:
                self.sleep(self.eligible - self.monotonic())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            try:
                with temp.open("w", encoding="ascii") as out:
                    out.write(str(self.wall()) + "\n")
                    out.flush()
                    os.fsync(out.fileno())
                os.chmod(temp, 0o600)
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)
            # Count failed/partial sends too. Set the next eligible instant
            # after write returns, conservatively including transmission time.
            if callable(frame):
                frame = frame()
            LOG.info("M-Bus TX ready: %d bytes", len(frame))
            if target is not None and not 0 <= self.wall() - target <= 1:
                raise MissedSlot('serial preparation exceeded planned slot')
            try:
                written = serial.write(frame)
                capture("TX", frame, "sent" if written == len(frame) else "partial_write")
                return written
            except Exception:
                capture("TX", frame, "write_error")
                raise
            finally:
                self.eligible = self.monotonic() + MIN_INTERVAL


def shared_timing_active():
    return _gate is not None


def install_bus_timing(gate):
    global _gate
    _gate = gate


def write_frame(serial, frame):
    if _gate is None:
        return serial.write(frame() if callable(frame) else frame)
    return _gate.write(serial, frame)
