"""Pure address-change safety policy. No I/O and no write authorization."""
from dataclasses import dataclass
from enum import Enum
import re


@dataclass(frozen=True)
class SecondaryIdentity:
    meter_id: str
    manufacturer: str
    version: int
    medium: int

    def __post_init__(self):
        if not isinstance(self.meter_id, str) or not re.fullmatch(r"[0-9]{8}", self.meter_id):
            raise ValueError("invalid meter ID")
        if not isinstance(self.manufacturer, str) or not re.fullmatch(r"[A-Z]{3}", self.manufacturer):
            raise ValueError("invalid manufacturer")
        for value in (self.version, self.medium):
            # FF is a wildcard in secondary selection, not an exact selector.
            if type(value) is not int or not 0 <= value < 255:
                raise ValueError("invalid or wildcard identity byte")

    @classmethod
    def from_decoded(cls, decoded):
        if decoded.get("type") != "long" or decoded.get("control") not in (8, 24) or decoded.get("ci") != 0x72:
            raise ValueError("not a supported identity response")
        return cls(decoded.get("meter_id"), decoded.get("manufacturer"),
                   decoded.get("version"), decoded.get("medium_code"))


class Availability(Enum):
    OCCUPIED = "occupied"
    AMBIGUOUS = "ambiguous"
    NO_RESPONSE = "no_response"
    FAILED = "failed"


def validate_address(address):
    if type(address) is not int or not 0 <= address <= 250:
        raise ValueError("primary address must be an integer 0..250")
    return address


def assess_destination(address, selected, meter_id, frame, *, checked):
    """Classify a probe, not proof of availability. Registered conflict wins."""
    validate_address(address)
    if any(key != meter_id and value == address for key, value in selected.items()):
        return Availability.OCCUPIED
    if checked is not True:
        return Availability.FAILED
    if frame == b"":
        return Availability.NO_RESPONSE
    if not isinstance(frame, bytes):
        return Availability.FAILED
    from mbus_probe import validate
    try:
        decoded = validate(frame)
        SecondaryIdentity.from_decoded(decoded)
        if decoded.get("address") == address:
            return Availability.OCCUPIED
    except (ValueError, TypeError, IndexError):
        pass
    return Availability.AMBIGUOUS


def assess_intent(expected, observed, old_address, new_address, availability,
                  *, exclusive_selection, confirmed, override=False):
    """Evaluate prerequisites only; transport must enforce freshness and locking."""
    validate_address(old_address)
    validate_address(new_address)
    if not isinstance(expected, SecondaryIdentity) or expected != observed or exclusive_selection is not True:
        return "identity_blocked"
    if old_address == new_address:
        return "unchanged"
    if not isinstance(availability, Availability):
        return "destination_unchecked"
    if confirmed is not True:
        return "confirmation_required"
    if availability is not Availability.NO_RESPONSE and override is not True:
        return "override_required"
    return "prerequisites_met"


@dataclass(frozen=True)
class DeviceNumberBinding:
    """Externally verified binding; reference identifies the supporting evidence."""
    identity: SecondaryIdentity
    device_number: str
    evidence_reference: str

    def __post_init__(self):
        if not isinstance(self.identity, SecondaryIdentity):
            raise ValueError("complete instrument identity required")
        if not isinstance(self.device_number,str) or not re.fullmatch(r"[0-9]{8}",self.device_number):
            raise ValueError("exact device number required")
        if not isinstance(self.evidence_reference,str) or not self.evidence_reference.strip():
            raise ValueError("evidence reference required")


class DeviceNumberBindings:
    """Immutable-in-practice mapping for a verified test topology.

    Loading a binding does not establish physical exclusivity; the transport
    still requires independent evidence for each response.
    """
    def __init__(self, bindings):
        self._by_identity = {}
        numbers = set()
        for binding in bindings:
            if not isinstance(binding, DeviceNumberBinding):
                raise ValueError("verified binding required")
            if binding.identity in self._by_identity or binding.device_number in numbers:
                raise ValueError("ambiguous instrument/device number mapping")
            self._by_identity[binding.identity] = binding
            numbers.add(binding.device_number)

    def resolve(self, identity):
        binding = self._by_identity.get(identity)
        return binding.device_number if binding is not None else None
