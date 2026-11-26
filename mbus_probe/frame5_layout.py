"""Strict parser for the observed T230 firmware 7.12 frame-5 layout.

Candidate pending independent review; no live activation here.
"""
from frame5_capture import validate_capture

SEPARATORS = (26, 29, 31, 48, 73, 77, 96, 127, 140, 145, 153, 160, 163, 166)

def extract_abcdef(frame, address, meter_id):
    """Return three diagnostic bytes only for the supported physical layout."""
    if not isinstance(frame, bytes) or len(frame) != 176:
        raise ValueError("unsupported frame-5 length")
    decoded = validate_capture(frame, address, meter_id)
    if decoded.get("version") != 7 or frame[19] != 0x0f:
        raise ValueError("unsupported frame-5 header")
    if any(frame[i] != 0xff for i in SEPARATORS):
        raise ValueError("unsupported frame-5 block boundaries")
    if frame[167:170] != bytes.fromhex("12 07 00") or frame[171] != 5:
        raise ValueError("unsupported frame-5 firmware or marker")
    if frame[172:174] != bytes.fromhex("02 02"):
        raise ValueError("unsupported frame-5 trailer")
    return frame[74:77]
