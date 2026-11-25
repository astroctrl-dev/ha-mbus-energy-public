"""Single in-process transmission gate for the HA app.

All application serial writers pass through this gate. A conservative global
bus interval also protects the same meter if its address changes. Standalone
CLI usage outside the app must not share its serial device.
"""
from raw_telegram_log import capture
import logging
import json
import math
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
                 monotonic=time.monotonic, wall=time.time, sleep=time.sleep,
                 *, resume=False, fresh=False, boot_id=None):
        self.path = Path(path)
        self.monotonic, self.wall, self.sleep = monotonic, wall, sleep
        self.lock = threading.Lock()
        # A full startup guard is safe even after wall-clock adjustments or a
        # crash between persistence and serial transmission.
        self.eligible = monotonic() + MIN_INTERVAL
        self.resume_path = self.path.with_name(self.path.name + ".resume")
        self.boot_id = boot_id
        if resume and self.boot_id is None:
            try:
                self.boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            except OSError:
                pass
        if resume:
            try:
                state = json.loads(self.resume_path.read_text())
                completed = state["completed"]
                now = monotonic()
                if (self.boot_id and state["boot_id"] == self.boot_id
                        and type(completed) in (float, int)
                        and math.isfinite(completed) and 0 <= completed <= now):
                    self.eligible = max(now, completed + MIN_INTERVAL)
            except FileNotFoundError:
                if fresh and not self.path.exists():
                    self.eligible = monotonic()
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def _persist_resume(self, completed):
        if not self.boot_id:
            return
        self.resume_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.resume_path.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="ascii") as out:
                json.dump({"boot_id": self.boot_id, "completed": completed}, out)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, self.resume_path)
            fd = os.open(self.resume_path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temp.unlink(missing_ok=True)

    def ready(self):
        return self.monotonic() >= self.eligible

    def write(self, serial, frame):
        attempted = False
        written = None
        try:
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
                self._persist_resume(None)  # Durable uncertain state before any send.
                attempted = True
                try:
                    written = serial.write(frame)
                    return written
                finally:
                    completed = self.monotonic()
                    self.eligible = completed + MIN_INTERVAL
                    self._persist_resume(completed)
        finally:
            if attempted:
                capture("TX", frame, "write_error" if written is None else
                        "sent" if written == len(frame) else "partial_write")


def shared_timing_active():
    return _gate is not None


def install_bus_timing(gate):
    global _gate
    _gate = gate


def write_frame(serial, frame):
    if _gate is None:
        return serial.write(frame() if callable(frame) else frame)
    return _gate.write(serial, frame)
