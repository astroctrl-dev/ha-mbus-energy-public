"""Frame-5 battery evidence projection. Never infer charge or remaining life.

Only accept a verified three-byte ABCDEF field from a validated physical
frame layout. No automatic extraction by searching FF separators.
"""
from datetime import datetime
from mbus_records import decode_frame5_flags

def battery_evidence(extension, read_at_utc, *, layout_verified=False):
    if layout_verified is not True:
        raise ValueError("frame-5 layout not verified")
    stamp = datetime.fromisoformat(read_at_utc.replace("Z","+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timestamp requires offset")
    flags = decode_frame5_flags(extension)
    return {"battery_prewarning":flags["battery_prewarning"],
            "battery_exhausted":flags["battery_exhausted"],
            "read_at_utc":stamp.isoformat(),
            "source":"T230 frame 5 ABCDEF"}

def battery_state(evidence, field):
    if field not in ("battery_prewarning","battery_exhausted"):
        raise ValueError("unsupported battery field")
    value = (evidence or {}).get(field)
    return "ON" if value is True else "OFF" if value is False else "None"
