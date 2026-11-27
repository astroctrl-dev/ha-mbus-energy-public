"""T230 address telegram construction only; no transport or physical write."""
import re
from address_policy import SecondaryIdentity, validate_address

SECONDARY = 0xFD


def _long(control, ci, payload):
    if control not in (0x53, 0x73):
        raise ValueError("invalid SND_UD control")
    body = bytes((control, SECONDARY, ci)) + payload
    return bytes((0x68, len(body), len(body), 0x68)) + body + bytes((sum(body) & 255, 0x16))


def select_exact(identity, control=0x53):
    if not isinstance(identity, SecondaryIdentity):
        raise ValueError("complete identity required")
    # Revalidate at the encoding boundary.
    SecondaryIdentity(identity.meter_id, identity.manufacturer, identity.version, identity.medium)
    manufacturer = 0
    for letter in identity.manufacturer:
        manufacturer = (manufacturer << 5) | (ord(letter) - 64)
    encoded = bytes.fromhex(identity.meter_id)[::-1] + manufacturer.to_bytes(2, "little")
    return _long(control, 0x52, encoded + bytes((identity.version, identity.medium)))


def select_enhanced(identity, serial_number, control=0x53):
    if not isinstance(serial_number, str) or not re.fullmatch(r"[0-9]{8}", serial_number):
        raise ValueError("exact eight-digit device number required")
    standard = select_exact(identity, control)
    return _long(control, 0x52, standard[7:-2] + b"\x0c\x78" + bytes.fromhex(serial_number)[::-1])


def deselect():
    return bytes((0x10, 0x40, SECONDARY, (0x40 + SECONDARY) & 255, 0x16))


def selected_read(control=0x5B):
    if control not in (0x5B, 0x7B):
        raise ValueError("invalid REQ_UD2 control")
    return bytes((0x10, control, SECONDARY, (control + SECONDARY) & 255, 0x16))


def selected_address_record(address, control=0x53):
    """Construct bytes only; caller must establish and verify exclusive selection."""
    return _long(control, 0x51, bytes((0x01, 0x7A, validate_address(address))))
