"""Offline candidate for operation-owned access to the common paced gate.

Not installed in the running app. The controller must own the shared bus lock.
A recovery permit is read-only with respect to instrument configuration.
"""
import threading
from bus_timing import AddressSafetyBlocked
from address_journal import Intent
from address_telegrams import deselect, select_exact, select_enhanced, selected_read, selected_address_record


class AddressPermit:
    def __init__(self, journal, intent, *, bus_lock, serial_number=None):
        if not isinstance(intent, Intent) or journal.load() != intent:
            raise AddressSafetyBlocked("matching durable intent required")
        self._bus_lock = bus_lock
        self._lease = bus_lock.current_lease()
        if self._lease is None:
            raise AddressSafetyBlocked('owned bus lease required')
        self._journal = journal
        self._intent = intent
        self._transaction_id = journal.transaction_id()
        self._owner = threading.get_ident()
        self._closed = False
        self._allowed = {
            deselect(), selected_read(), selected_read(0x7B),
            select_exact(intent.identity), select_exact(intent.identity, 0x73)
        } if serial_number is None else {
            deselect(), selected_read(), selected_read(0x7B),
            select_enhanced(intent.identity, serial_number),
            select_enhanced(intent.identity, serial_number, 0x73)
        }

    def check(self, frame):
        if (self._closed or threading.get_ident() != self._owner
                or self._bus_lock.current_lease() is not self._lease
                or not isinstance(frame, bytes) or frame not in self._allowed
                or self._journal.load() != self._intent
                or self._journal.transaction_id() != self._transaction_id):
            raise AddressSafetyBlocked("telegram not permitted by address operation")

    def consume(self, frame):
        self.check(frame)

    def close(self):
        self._closed = True


class FreshAddressPermit(AddressPermit):
    """Single-write candidate; only a fresh transaction owner may construct it.

    Fresh authorization is restricted to the journal creator and consumed durably.
    Actual exclusive selection proof must be integrated before live use.
    """
    def __init__(self, journal, intent, *, bus_lock, serial_number=None, shutdown=None):
        super().__init__(journal, intent, bus_lock=bus_lock, serial_number=serial_number)
        self.shutdown = shutdown
        if not journal.fresh_write_available(intent):
            raise AddressSafetyBlocked('no fresh write authorization')
        self._write_frames = {selected_address_record(intent.new_address),
                              selected_address_record(intent.new_address, 0x73)}
        self._allowed.update(self._write_frames)

    def check(self, frame):
        super().check(frame)
        if frame in self._write_frames and self.shutdown is not None and self.shutdown.is_set():
            raise AddressSafetyBlocked('shutdown requested; physical address write blocked')
        if frame in self._write_frames and not self._journal.fresh_write_available(self._intent):
            raise AddressSafetyBlocked('write authorization unavailable')

    def consume(self, frame):
        super().consume(frame)
        if frame in self._write_frames:
            self._journal.claim_write(self._intent)
            self._allowed.difference_update(self._write_frames)
            # The durable claim may itself block. Recheck before returning to TX.
            self.check_shutdown_before_transmit(frame)

    def check_shutdown_before_transmit(self, frame):
        if frame in self._write_frames and self.shutdown is not None and self.shutdown.is_set():
            raise AddressSafetyBlocked('shutdown requested after durable claim; recover without rewriting')


class QuarantineProbePermit:
    """One primary read only, while the selected quarantined meter is reconciled."""
    def __init__(self, journal, registry, bus_lock, identity, address):
        from address_policy import validate_address
        address = validate_address(address)
        self.journal, self.registry, self.bus_lock = journal, registry, bus_lock
        self.identity, self.address = identity, address
        self.owner = threading.get_ident()
        self.lease = bus_lock.current_lease()
        self.used = False
        self.frame = bytes((0x10, 0x5B, address, (0x5B + address) & 255, 0x16))
        self.check(self.frame)

    def check(self, frame):
        key = self.identity.meter_id
        if (self.used or self.owner != threading.get_ident()
                or self.lease is None or self.bus_lock.current_lease() is not self.lease
                or frame != self.frame or self.journal.blocked()
                or self.registry.persistence_failed or key not in self.registry.quarantined
                or self.registry.identities.get(key) != self.identity
                or key not in self.registry.selected):
            raise AddressSafetyBlocked("quarantine probe not authorized")

    def consume(self, frame):
        self.check(frame)
        self.used = True


class QuarantineEnrollmentPermit:
    """Single primary read of an existing, uniquely addressed but unenrolled peer."""
    def __init__(self, journal, registry, bus_lock, meter_id, address):
        from address_policy import validate_address
        address = validate_address(address)
        self.journal, self.registry, self.bus_lock = journal, registry, bus_lock
        self.meter_id, self.address = meter_id, address
        self.owner = threading.get_ident()
        self.lease = bus_lock.current_lease()
        self.used = False
        self.frame = bytes((0x10, 0x5B, address, (0x5B + address) & 255, 0x16))
        self.check(self.frame)

    def check(self, frame):
        r, key = self.registry, self.meter_id
        if (self.used or self.owner != threading.get_ident()
                or self.lease is None or self.bus_lock.current_lease() is not self.lease
                or frame != self.frame or self.journal.blocked()
                or r.persistence_failed or key not in r.quarantined
                or key in r.identities or r.selected.get(key) != self.address
                or any(k != key and a == self.address for k, a in r.selected.items())):
            raise AddressSafetyBlocked("quarantine enrollment probe not authorized")

    def consume(self, frame):
        self.check(frame)
        self.used = True


class PendingPrimaryPermit(AddressPermit):
    """Read only at the old/new address of the matching durable intent."""
    def __init__(self, journal, intent, address, *, bus_lock):
        super().__init__(journal,intent,bus_lock=bus_lock)
        if type(address) is not int or address not in (intent.old_address,intent.new_address):
            raise AddressSafetyBlocked("primary address outside pending intent")
        self.frame=bytes((0x10,0x5B,address,(0x5B+address)&255,0x16))
        self._allowed={self.frame}

    def consume(self,frame):
        super().consume(frame)
        self.close()
