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
MIN_INTERVAL = 60.0
PRIMARY_PROBE_INTERVAL = 2.0
POLL_SLOT_TOLERANCE = 10.0


def slot_tolerance(before_hour=False, target=None):
    # Limit shifted slots to their own hour, never send at/after rollover.
    if before_hour and target is not None:
        return min(POLL_SLOT_TOLERANCE, 3600 - target % 3600)
    return POLL_SLOT_TOLERANCE


def slot_open(target, now, tolerance):
    return target is not None and 0 <= now - target < tolerance
_gate = None
_slot = threading.local()


class AddressSafetyBlocked(RuntimeError):
    """Transmission inhibited by persistent address safety state."""


class MissedSlot(RuntimeError):
    """No serial transmission was attempted for this expired poll."""


@contextmanager
def poll_slot(target, tolerance=1.0):
    previous = getattr(_slot, 'target', None)
    previous_tolerance = getattr(_slot, 'tolerance', 1.0)
    _slot.target = target
    _slot.tolerance = tolerance
    try:
        yield
    finally:
        _slot.target = previous
        _slot.tolerance = previous_tolerance


class BusTiming:
    def __init__(self, path="/data/analysis/last_bus_request",
                 monotonic=time.monotonic, wall=time.time, sleep=time.sleep,
                 *, resume=False, fresh=False, boot_id=None, address_blocked=None, diagnostic_guard=None):
        self.path = Path(path)
        self.monotonic, self.wall, self.sleep = monotonic, wall, sleep
        self.lock = threading.Lock()
        self.address_blocked = address_blocked
        # Fast path is deliberately volatile: restart and ordinary traffic
        # retain the full global guard. Only completed silent primary probes
        # can authorize a shorter interval for a different primary address.
        self._probe_times = {}
        self._silent_probe = None
        self._pending_probe = None
        self.diagnostic_guard = diagnostic_guard
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

    def check_address_safety(self, permit=None, frame=None):
        if self.diagnostic_guard is not None:
            from address_diagnostic import DiagnosticPermit
            if type(permit) is DiagnosticPermit:
                if permit.guard is not self.diagnostic_guard or (self.address_blocked is not None and self.address_blocked()):
                    raise AddressSafetyBlocked("diagnostic safety conflict")
                permit.check(frame)
                return
            if self.diagnostic_guard.blocked():
                raise AddressSafetyBlocked("diagnostic recovery required")
        if permit is not None:
            from address_permit import AddressPermit, FreshAddressPermit, QuarantineProbePermit, QuarantineEnrollmentPermit, PendingPrimaryPermit
            if type(permit) not in (AddressPermit, FreshAddressPermit, QuarantineProbePermit, QuarantineEnrollmentPermit, PendingPrimaryPermit):
                raise AddressSafetyBlocked('unrecognized address permit')
            permit.check(frame)
            return
        if self.address_blocked is not None and self.address_blocked():
            raise AddressSafetyBlocked('address safety state requires reconciliation')

    def write_primary_probe(self, serial, frame):
        if (type(frame) is not bytes or len(frame) != 5 or frame[:2] != b'\x10\x5b'
                or frame[2] > 250 or frame[3] != (0x5b + frame[2]) & 255 or frame[4] != 0x16):
            raise ValueError('only exact individually addressed read-only probe permitted')
        return self.write(serial, frame, _primary_probe=frame[2])

    def complete_primary_probe(self, address, raw):
        # Called by the exclusive read-only transport only after its full
        # bounded receive window and successful serial close. A response,
        # collision, partial exchange or any exception keeps global pacing.
        with self.lock:
            if self._pending_probe == address and raw == b'':
                self._silent_probe = (address, self.monotonic())
            self._pending_probe = None

    def write(self, serial, frame, *, permit=None, _primary_probe=None):
        attempted = False
        written = None
        try:
            with self.lock:
                self.check_address_safety(permit, frame)
                target = getattr(_slot, 'target', None)
                if target is not None and (not self.ready() or not slot_open(target, self.wall(), getattr(_slot, 'tolerance', 1.0))):
                    raise MissedSlot('bus not eligible at planned slot')
                eligible = self.eligible
                if _primary_probe is not None and permit is None and target is None and self._silent_probe is not None:
                    previous, response_completed = self._silent_probe
                    if previous != _primary_probe:
                        eligible = min(eligible, max(response_completed + 0.0,
                            self.eligible - MIN_INTERVAL + PRIMARY_PROBE_INTERVAL,
                            self._probe_times.get(_primary_probe, float('-inf')) + MIN_INTERVAL))
                self._silent_probe = None
                self._pending_probe = None
                while self.monotonic() < eligible:
                    self.sleep(eligible - self.monotonic())
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
                if target is not None and not slot_open(target, self.wall(), getattr(_slot, 'tolerance', 1.0)):
                    raise MissedSlot('serial preparation exceeded planned slot')
                self._persist_resume(None)  # Durable uncertain state before any send.
                if target is not None and not slot_open(target, self.wall(), getattr(_slot, 'tolerance', 1.0)):
                    raise MissedSlot('durable preparation exceeded planned slot')
                self.check_address_safety(permit, frame)
                LOG.info("M-Bus TX ready: %d bytes", len(frame))
                if permit is not None:
                    permit.consume(frame)
                attempted = True
                try:
                    written = serial.write(frame)
                    # Wait for the serial output to drain before starting the
                    # 60-second quiet period. Start-to-start spacing therefore
                    # includes transmission time and exceeds one minute.
                    drain = getattr(serial, "flush", None)
                    if drain is not None:
                        drain()
                    return written
                finally:
                    completed = self.monotonic()
                    self.eligible = completed + MIN_INTERVAL
                    self._persist_resume(completed)
                    if _primary_probe is None:
                        # A global operation (possibly broadcast/selected) resets
                        # fast discovery and imposes a full bus-wide guard.
                        self._probe_times.clear()
                    else:
                        self._probe_times[_primary_probe] = completed
                        if written == len(frame):
                            self._pending_probe = _primary_probe
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
