"""Candidate byte-level address transport; not connected to production.

The injected exclusivity verifier must provide independent evidence. A valid
response or ACK alone is insufficient. The shared bus lock must be owned by
the calling controller for the entire operation.
"""
from address_controller import Proof
from address_policy import assess_destination, validate_address, SecondaryIdentity
from address_permit import AddressPermit, FreshAddressPermit, QuarantineProbePermit, QuarantineEnrollmentPermit, PendingPrimaryPermit
from address_response import clean_ack, readback_address, receive_window, reported_device_number
from address_telegrams import deselect, select_enhanced, selected_read, selected_address_record
from raw_telegram_log import capture


class CandidateTransport:
    def __init__(self, serial, gate, journal, bus_lock, serial_resolver, exclusivity, *, shutdown=None):
        self.serial, self.gate, self.journal = serial, gate, journal
        self.bus_lock = bus_lock
        if not callable(serial_resolver) or not callable(exclusivity):
            raise ValueError('instrument-specific evidence providers required')
        self.serial_resolver = serial_resolver
        self.exclusivity = exclusivity
        self.shutdown = shutdown
        self.proof = None
        self.permit = None
        self.selected = False

    def _serial_for(self, identity):
        import re
        serial = self.serial_resolver(identity)
        if not isinstance(serial,str) or not re.fullmatch(r"[0-9]{8}",serial):
            raise ValueError("verified instrument-specific device number required")
        return serial

    def _locked(self):
        if not self.bus_lock.owned_by_current_thread():
            raise RuntimeError("shared bus lock required")

    def _exchange(self, frame, permit=None):
        self._locked()
        try:
            if self.serial.in_waiting:
                raise ValueError("unexpected buffered input before address exchange")
            if self.gate.write(self.serial, frame, permit=permit, defer_completion=True,
                               reject_buffered=True) != len(frame):
                raise OSError("partial transmission")
            response = receive_window(self.serial)
            capture("RX", response)
            return response
        except Exception:
            # Reject this exchange; discard residual bytes only after failure.
            # A subsequent recovery must establish fresh selection and proof.
            self.serial.reset_input_buffer()
            raise
        finally:
            # A process crash before this point retains durable unknown timing.
            self.gate.complete_address_exchange()

    def check(self, address):
        address = validate_address(address)
        control = 0x5B
        frame = bytes((0x10, control, address, (control + address) & 255, 0x16))
        return assess_destination(address, {}, "", self._exchange(frame), checked=True)

    def check_quarantined(self, registry, identity, address):
        self._locked()
        if self.selected:
            raise RuntimeError("selection still active")
        permit = QuarantineProbePermit(self.journal, registry, self.bus_lock, identity, address)
        return assess_destination(address, {}, "", self._exchange(permit.frame, permit), checked=True)

    def verify_quarantined_primary(self, registry, identity, address):
        """Fresh exact primary response plus independently established exclusivity."""
        self._locked()
        if self.selected or registry.selected.get(identity.meter_id) != address:
            raise RuntimeError("primary verification unavailable")
        permit = QuarantineProbePermit(self.journal, registry, self.bus_lock, identity, address)
        raw = self._exchange(permit.frame, permit)
        observed_address = readback_address(raw, identity)
        return Proof(identity, observed_address,
                     self.exclusivity(identity, self._serial_for(identity), raw) is True)

    def inspect_unenrolled_peer(self, registry, meter_id, address):
        self._locked()
        if self.selected:
            raise RuntimeError("selection still active")
        permit = QuarantineEnrollmentPermit(self.journal, registry, self.bus_lock, meter_id, address)
        raw = self._exchange(permit.frame, permit)
        from mbus_probe import validate
        identity = SecondaryIdentity.from_decoded(validate(raw))
        if identity.meter_id != meter_id:
            raise ValueError("meter ID mismatch")
        observed_address = readback_address(raw, identity)
        return Proof(identity, observed_address,
                     self.exclusivity(identity, self._serial_for(identity), raw) is True)

    def verify_pending_primary(self, intent, address):
        self._locked()
        if self.selected:
            raise RuntimeError("selection still active")
        permit=PendingPrimaryPermit(self.journal,intent,address,bus_lock=self.bus_lock)
        raw=self._exchange(permit.frame,permit)
        observed=readback_address(raw,intent.identity)
        return Proof(intent.identity,observed,self.exclusivity(intent.identity,self._serial_for(intent.identity),raw) is True)

    def _select(self, identity, fresh):
        self._locked()
        intent = self.journal.load()
        if intent is None or intent.identity != identity or self.selected:
            raise RuntimeError("invalid selection state")
        serial_number = self._serial_for(identity)
        self.proof = None
        self.permit = AddressPermit(self.journal, intent, bus_lock=self.bus_lock, serial_number=serial_number)
        self.selected = True  # uncertain selection must always be released
        if not clean_ack(self._exchange(deselect(), self.permit)):
            raise ValueError('initial deselection not acknowledged cleanly')
        if not clean_ack(self._exchange(select_enhanced(identity, serial_number), self.permit)):
            raise ValueError("selection not acknowledged cleanly")
        raw = self._exchange(selected_read(0x7B), self.permit)
        address = readback_address(raw, identity)
        exclusive = (reported_device_number(raw, identity) == serial_number
                     and self.exclusivity(identity, serial_number, raw) is True)
        self.proof = Proof(identity, address, exclusive)
        if fresh and self.proof.matches(identity, intent.old_address):
            self.permit.close()
            self.permit = FreshAddressPermit(self.journal, intent, bus_lock=self.bus_lock, serial_number=serial_number, shutdown=self.shutdown)
        return self.proof

    def select(self, identity):
        return self._select(identity, True)

    def inspect(self, identity):
        self._locked()
        # Discard stale in-memory selection/permit, never its durable intent.
        # _select starts with a paced deselect using a new read-only permit.
        if self.permit is not None:
            self.permit.close()
        self.permit = None
        self.proof = None
        self.selected = False
        return self._select(identity, False)

    def write_selected(self, address):
        self._locked()
        intent = self.journal.load()
        if (intent is None or not self.selected or self.proof is None
                or not self.proof.matches(intent.identity, intent.old_address)
                or address != intent.new_address or type(self.permit) is not FreshAddressPermit):
            raise RuntimeError("write lacks verified selection")
        self.proof = None
        if not clean_ack(self._exchange(selected_address_record(address, 0x73), self.permit)):
            raise OSError("write acknowledgement uncertain")

    def release(self):
        self._locked()
        if not self.selected:
            return
        self.proof = None
        if not clean_ack(self._exchange(deselect(), self.permit)):
            raise OSError("deselection not acknowledged")
        self.permit.close()
        self.permit = None
        self.selected = False
