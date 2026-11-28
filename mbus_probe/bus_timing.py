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
        self.persistence_failed = False
        # Fast path is deliberately volatile: restart and ordinary traffic
        # retain the full global guard. Only completed silent primary probes
        # can authorize a shorter interval for a different primary address.
        self._probe_times = {}
        self._normal_candidate = None
        self._normal_pending = None
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
        try:
            self._write_resume_record(completed)
        except OSError:
            self.persistence_failed = True
            self._silent_probe = None
            self._pending_probe = None
            self.eligible = max(self.eligible, self.monotonic()+MIN_INTERVAL)
            raise

    def _write_resume_record(self, completed):
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
        return not self.persistence_failed and self.monotonic() >= self.eligible

    def check_address_safety(self, permit=None, frame=None):
        if self.persistence_failed:
            raise AddressSafetyBlocked('timing state persistence failed; restart after storage recovery')
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

    def write_primary_probe(self, serial, frame, *, interval=PRIMARY_PROBE_INTERVAL, quiet=0.0, defer_completion=False, scan_transition=False):
        if type(quiet) not in (int,float) or not math.isfinite(quiet) or not 0 <= quiet <= 2:
            raise ValueError('invalid post-exchange quiet interval')
        if type(interval) not in (int,float) or not math.isfinite(interval) or not 0.2 <= interval <= PRIMARY_PROBE_INTERVAL:
            raise ValueError('invalid experimental probe interval')
        if (type(frame) is not bytes or len(frame) != 5 or frame[:2] != b'\x10\x5b'
                or frame[2] > 250 or frame[3] != (0x5b + frame[2]) & 255 or frame[4] != 0x16):
            raise ValueError('only exact individually addressed read-only probe permitted')
        return self.write(serial, frame, _primary_probe=frame[2], _probe_interval=interval, _probe_quiet=quiet, defer_completion=defer_completion, scan_transition=scan_transition)

    def complete_normal_read(self, address, raw, expected_meter_id):
        from mbus_probe import validate
        from address_policy import SecondaryIdentity
        with self.lock:
            pending=self._normal_pending
            self._normal_pending=None
            try:
                decoded=validate(raw)
                identity=SecondaryIdentity.from_decoded(decoded)
                valid=(pending==address and decoded.get('address')==address and identity.meter_id==expected_meter_id)
            except (ValueError,TypeError,IndexError):
                valid=False
            completed=self.monotonic()
            self.eligible=max(self.eligible,completed+MIN_INTERVAL)
            self._persist_resume(completed)
            self._normal_candidate=(address,completed) if valid else None
            if valid:
                self._probe_times[address]=completed

    def invalidate_primary_probe(self):
        with self.lock:
            self._silent_probe=None
            self._pending_probe=None
            self._normal_candidate=None
            self._normal_pending=None
            self.eligible=max(self.eligible,self.monotonic()+MIN_INTERVAL)
            self._persist_resume(self.eligible-MIN_INTERVAL)

    def remaining_guard(self):
        return max(0.0,self.eligible-self.monotonic())

    def complete_read_exchange(self):
        # Called only after serial RX and close completed under the shared lease.
        # Persist the conservative completion instant without altering the
        # ordinary distinct-address silent-probe pacing in this process.
        with self.lock:
            self._persist_resume(self.monotonic())

    def complete_address_exchange(self):
        """Conservative full guard from bounded RX completion, including errors."""
        with self.lock:
            completed = self.monotonic()
            self.eligible = max(self.eligible, completed + MIN_INTERVAL)
            self._persist_resume(completed)

    def complete_primary_probe(self, address, raw, *, fast_response=False):
        # Fast discovery records the completed bounded receive window even
        # when its bytes are ambiguous. Classification/rechecks are separate.
        # Transport errors never reach this completion path. The shortcut
        # applies only to a different experimental primary probe.
        with self.lock:
            matched = self._pending_probe == address
            completed = self.monotonic()
            if matched and raw == b'':
                self._silent_probe = (address, completed)
            if matched:
                self._probe_times[address] = completed
            self._pending_probe = None
            if matched and fast_response is True and raw:
                self.eligible = max(self.eligible, completed + MIN_INTERVAL)
                self._normal_candidate = (address, completed)
                return True
            return False

    def write(self, serial, frame, *, permit=None, _primary_probe=None, _probe_interval=PRIMARY_PROBE_INTERVAL, _probe_quiet=0.0, defer_completion=False, scan_transition=False, normal_address=None, reject_buffered=False):
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
                        eligible = min(eligible, max(response_completed + _probe_quiet,
                            self.eligible - MIN_INTERVAL + _probe_interval,
                            self._probe_times.get(_primary_probe, float('-inf')) + MIN_INTERVAL))
                if (_primary_probe is not None and scan_transition and permit is None and target is None
                        and self._normal_candidate is not None):
                    previous, completed=self._normal_candidate
                    if previous!=_primary_probe:
                        eligible=min(eligible,max(completed+max(.01,_probe_quiet),
                            self._probe_times.get(_primary_probe,float('-inf'))+MIN_INTERVAL))
                if _primary_probe is not None:
                    eligible=max(eligible,self._probe_times.get(_primary_probe,float('-inf'))+MIN_INTERVAL)
                self._normal_candidate=None
                self._normal_pending=None
                self._silent_probe = None
                self._pending_probe = None
                while self.monotonic() < eligible:
                    self.sleep(eligible - self.monotonic())
                if (reject_buffered or (_primary_probe is not None and _probe_quiet)) and serial.in_waiting:
                    self.eligible=max(self.eligible,self.monotonic()+MIN_INTERVAL)
                    raise ValueError('unexpected buffered input after guard wait')
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
                if _primary_probe is not None and _probe_quiet and serial.in_waiting:
                    self.eligible=max(self.eligible,self.monotonic()+MIN_INTERVAL)
                    raise ValueError('unexpected buffered input before transmission')
                LOG.info("M-Bus TX ready: %d bytes", len(frame))
                if permit is not None:
                    permit.consume(frame)
                if reject_buffered and serial.in_waiting:
                    self.eligible=max(self.eligible,self.monotonic()+MIN_INTERVAL)
                    raise ValueError('unexpected buffered input after authorization')
                # The serial buffer query above can block. Check STOP again
                # after it, immediately before the physical mutation.
                from address_permit import FreshAddressPermit
                if type(permit) is FreshAddressPermit:
                    permit.check_shutdown_before_transmit(frame)
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
                    self._persist_resume(None if defer_completion else completed)
                    if _primary_probe is None:
                        # A global operation (possibly broadcast/selected) resets
                        # fast discovery and imposes a full bus-wide guard.
                        self._probe_times.clear()
                        if normal_address is not None and written==len(frame) and frame==bytes((0x10,0x5b,normal_address,(0x5b+normal_address)&255,0x16)):
                            self._normal_pending=normal_address
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


def write_frame(serial, frame, **kwargs):
    if _gate is None:
        return serial.write(frame() if callable(frame) else frame)
    return _gate.write(serial, frame, **kwargs)


def complete_normal_read(address, raw, expected_meter_id):
    if _gate is not None:
        _gate.complete_normal_read(address,raw,expected_meter_id)


def invalidate_normal_read():
    if _gate is not None:
        _gate.invalidate_primary_probe()
