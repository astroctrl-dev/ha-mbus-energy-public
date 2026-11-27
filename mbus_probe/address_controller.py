"""Offline orchestration of address changes. No production transport is supplied.

Transport contract: inspect(identity) returns fresh exclusive physical address proof;
check(address) returns Availability; select(identity) returns fresh proof and
maintains selection until write_selected; release() must restore normal selection.
All methods execute under the shared bus lock. Never use an unverified adapter.
"""
from dataclasses import dataclass
from address_policy import Availability, SecondaryIdentity, assess_intent, validate_address
from address_journal import Intent


@dataclass(frozen=True)
class Proof:
    identity: SecondaryIdentity
    address: int
    exclusive: bool

    def matches(self, identity, address):
        return (self.exclusive is True and self.identity == identity
                and type(self.address) is int and self.address == address)


class AddressController:
    def __init__(self, registry, journal, bus_lock, transport):
        self.registry, self.journal = registry, journal
        self.bus_lock, self.transport = bus_lock, transport
        self.failed = False
        self.destination_evidence = None

    def change(self, meter_id, new_address, *, expected_old, confirmed=False, override=False, accepted_risk=None, resolve_conflict=False):
        validate_address(new_address)
        validate_address(expected_old)
        with self.bus_lock, self.registry.lock:
            self.destination_evidence = None
            if self.failed or self.journal.blocked() or self.registry.persistence_failed:
                return "recovery_required"
            identity = self.registry.identities.get(meter_id)
            if identity is None or self.registry.selected.get(meter_id) != expected_old:
                return "identity_blocked"
            if self.registry.quarantined:
                if resolve_conflict is not True or meter_id not in self.registry.quarantined:
                    return "quarantine_required"
            elif resolve_conflict is True:
                return "quarantine_required"
            if new_address == expected_old:
                return "unchanged"
            if confirmed is not True:
                return "confirmation_required"
            try:
                availability = (self.transport.check_quarantined(self.registry, identity, new_address)
                                if resolve_conflict is True else self.transport.check(new_address))
            except (OSError, ValueError, RuntimeError):
                availability = Availability.FAILED
            if any(k != meter_id and a == new_address for k, a in self.registry.selected.items()):
                availability = Availability.OCCUPIED
            if not isinstance(availability, Availability):
                availability = Availability.FAILED
            peers = sorted(k for k, a in self.registry.selected.items() if k != meter_id and a == new_address)
            self.destination_evidence = {"meter_id": meter_id, "old_address": expected_old,
                                         "new_address": new_address, "status": availability.value,
                                         "registered_peers": peers}
            if resolve_conflict is True and availability is not Availability.NO_RESPONSE:
                return "destination_blocked"
            if availability is not Availability.NO_RESPONSE and (override is not True or accepted_risk != self.destination_evidence):
                return "override_required"
            try:
                intent = Intent(identity, expected_old, new_address,
                                availability is not Availability.NO_RESPONSE)
                self.journal.begin(intent)
                proof = self.transport.select(identity)
                if not isinstance(proof, Proof) or not proof.matches(identity, expected_old):
                    self.transport.release()
                    # No write attempted. Retain intent until fresh read-only recovery.
                    return "identity_blocked"
                if assess_intent(identity, proof.identity, expected_old, new_address, availability,
                                 exclusive_selection=proof.exclusive, confirmed=confirmed,
                                 override=override) != "prerequisites_met":
                    self.transport.release()
                    return "identity_blocked"
                # A lost ACK is an uncertain outcome; never repeat the write.
                try:
                    self.transport.write_selected(new_address)
                except (OSError, ValueError, RuntimeError):
                    pass
                self.transport.release()
                return self._recover_locked(intent)
            except (OSError, ValueError, RuntimeError):
                self.failed = True
                try:
                    self.transport.release()
                except (OSError, ValueError, RuntimeError):
                    pass
                return "recovery_required"

    def enroll_quarantined_peer(self, meter_id, *, expected_address, confirmed=False):
        validate_address(expected_address)
        with self.bus_lock, self.registry.lock:
            if self.failed or self.journal.blocked() or self.registry.persistence_failed:
                return "recovery_required"
            if (confirmed is not True or meter_id not in self.registry.quarantined
                    or meter_id in self.registry.identities
                    or self.registry.selected.get(meter_id) != expected_address
                    or any(k != meter_id and a == expected_address for k, a in self.registry.selected.items())):
                return "identity_blocked"
            try:
                proof = self.transport.inspect_unenrolled_peer(self.registry, meter_id, expected_address)
                if (not isinstance(proof, Proof) or not isinstance(proof.identity, SecondaryIdentity)
                        or proof.identity.meter_id != meter_id or not proof.matches(proof.identity, expected_address)):
                    return "identity_blocked"
                self.registry.enroll_quarantined_identity(meter_id, proof.identity,
                    exclusive=proof.exclusive, confirmed=True, physical_address=proof.address)
                return "identity_enrolled"
            except (OSError, ValueError, RuntimeError):
                return "identity_blocked"

    def verify_quarantine(self, meter_id, *, expected_address, confirmed=False):
        validate_address(expected_address)
        with self.bus_lock, self.registry.lock:
            if self.failed or self.journal.blocked() or self.registry.persistence_failed:
                return "recovery_required"
            identity = self.registry.identities.get(meter_id)
            if (confirmed is not True or identity is None or meter_id not in self.registry.quarantined
                    or self.registry.selected.get(meter_id) != expected_address
                    or any(k != meter_id and a == expected_address for k, a in self.registry.selected.items())):
                return "quarantine_required"
            try:
                proof = self.transport.verify_quarantined_primary(self.registry, identity, expected_address)
                if not isinstance(proof, Proof) or not proof.matches(identity, expected_address):
                    return "quarantine_required"
                self.registry.clear_verified_quarantine(meter_id, proof.identity, proof.address,
                    exclusive=proof.exclusive, primary_verified=True)
                return "quarantine_cleared"
            except (OSError, ValueError, RuntimeError):
                return "quarantine_required"

    def recover(self, *, expected_meter=None, expected_transaction=None):
        with self.bus_lock, self.registry.lock:
            try:
                intent = self.journal.load()
                if intent is None:
                    return "recovery_required" if self.failed else "no_pending"
                if expected_meter is not None and (intent.identity.meter_id != expected_meter or
                        self.journal.transaction_id() != expected_transaction):
                    return "recovery_required"
                result = self._recover_locked(intent)
                if result in ("verified_new", "verified_old"):
                    self.failed = False
                return result
            except (OSError, ValueError, RuntimeError, TypeError, KeyError):
                self.failed = True
                return "recovery_required"

    def _recover_locked(self, intent):
        key = intent.identity.meter_id
        if self.registry.persistence_failed or self.registry.identities.get(key) != intent.identity:
            return "recovery_required"
        try:
            proof = self.transport.inspect(intent.identity)
        finally:
            self.transport.release()
        if not isinstance(proof, Proof):
            return "recovery_required"
        if proof.matches(intent.identity, intent.new_address):
            # An explicitly accepted destination risk still requires quarantine;
            # otherwise verify independently at the new primary address.
            if not intent.destination_risk:
                try:
                    primary=self.transport.verify_pending_primary(intent,intent.new_address)
                except (OSError,ValueError,RuntimeError):
                    return "recovery_required"
                if not isinstance(primary,Proof) or not primary.matches(intent.identity,intent.new_address):
                    return "recovery_required"
            self.registry.record_verified_address(intent, proof.identity, proof.address,
                exclusive=True, destination_risk=intent.destination_risk)
        elif not proof.matches(intent.identity, intent.old_address):
            return "recovery_required"
        return self.journal.finish(proof.identity, proof.address, exclusive=proof.exclusive,
            registry_address=self.registry.selected.get(key),
            registry_durable=not self.registry.persistence_failed)
