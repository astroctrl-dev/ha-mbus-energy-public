"""Conservative T230 response validation for an isolated transport candidate.

No live serial adapter or write path is installed. A clean byte stream cannot
prove uniqueness when identical devices transmit identical bytes.
"""
from address_policy import SecondaryIdentity, validate_address
from mbus_probe import validate


def readback_address(frame, expected):
    """Require a complete, single response with matching full secondary ID."""
    if not isinstance(expected, SecondaryIdentity) or not isinstance(frame, bytes):
        raise ValueError("complete identity and response required")
    decoded = validate(frame)
    if SecondaryIdentity.from_decoded(decoded) != expected:
        raise ValueError("secondary identity mismatch")
    # T230 documents A as meter address. FD is not a physical primary address.
    # Actual secondary-addressed A-field semantics must be validated on hardware.
    return validate_address(decoded.get("address"))


def clean_ack(response):
    return isinstance(response, bytes) and response == b"\xe5"


def receive_window(serial, *, limit=262):
    """Read an entire bounded response window, not just the first valid frame.

    Caller must configure a finite serial timeout and establish the response
    window for the baud rate. An extra byte invalidates an otherwise valid frame.
    """
    if type(limit) is not int or not 1 <= limit <= 262:
        raise ValueError("invalid response limit")
    timeout = serial.timeout
    if type(timeout) not in (int, float) or not 0 < timeout <= 10:
        raise ValueError("finite positive response timeout required")
    data = serial.read(limit + 1)
    if len(data) > limit:
        raise ValueError("excess response bytes")
    return bytes(data)


def reported_device_number(frame, expected):
    """Extract exactly one current DIF 0C / VIF 78 fabrication number.

    Reported number is not independent physical exclusivity evidence.
    Preserve leading zeroes; reject invalid, negative or duplicate records.
    """
    decoded = validate(frame)
    if SecondaryIdentity.from_decoded(decoded) != expected:
        raise ValueError("secondary identity mismatch")
    records = [r for r in decoded.get("records", ())
               if r.get("dif") == 0x0c and r.get("vif") == 0x78
               and r.get("current_record") is True
               and r.get("dife_hex") == "" and r.get("vife_hex") == ""]
    if len(records) != 1:
        raise ValueError("unique fabrication number required")
    raw = bytes.fromhex(records[0]["raw_hex"])
    if len(raw) != 4 or any(b >> 4 > 9 or b & 15 > 9 for b in raw):
        raise ValueError("invalid fabrication number BCD")
    return raw[::-1].hex()
