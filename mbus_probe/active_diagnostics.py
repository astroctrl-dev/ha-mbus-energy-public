"""Pure diagnostic projection; no bus access or guessed frame offsets."""
from mbus_records import decode_frame5_flags

FAULT_LABELS = (
    "Flow measurement error", "Flow temperature sensor interruption",
    "Return temperature sensor interruption", "Temperature electronics defective",
    "Battery exhausted", "Flow temperature sensor short circuit",
    "Return temperature sensor short circuit", "EEPROM error",
    "Eight-hour error", "Internal communication error",
)
FLOW_FIELDS = ("flow_fault", "flow_prewarning", "negative_flow",
               "negative_temperature_difference", "wrong_volume_installation",
               "wrong_sensor_installation")


def active_projection(extension, *, layout_verified=False):
    """Only verified ABCDEF bytes can establish active state."""
    if layout_verified is not True:
        raise ValueError("frame-5 layout not verified")
    flags = decode_frame5_flags(extension)
    codes = flags["active_fault_codes"]
    flow = {"flow_fault": "F0" in codes}
    flow.update({key: flags[key] for key in FLOW_FIELDS if key != "flow_fault"})
    installation = {
        "mounting_side": "flow" if flags["installation_in_flow"] else "return",
        **{key: flags[key] for key in (
            "wrong_sensor_installation", "wrong_volume_installation",
            "negative_flow", "negative_temperature_difference")},
    }
    return {
        "meter_installation_status": "warning" if any(
            value is True for value in installation.values()) else "normal",
        "installation_attributes": installation,
        "active_meter_faults": bool(codes),
        "fault_messages": [f"{code} - {FAULT_LABELS[int(code[1:])]}" for code in codes],
        "flow_warning": any(flow.values()),
        "flow_attributes": flow,
        "battery_prewarning": flags["battery_prewarning"],
        "battery_exhausted": flags["battery_exhausted"],
        "installation_in_flow": flags["installation_in_flow"],
    }


def extension_projection(raw):
    """TKB3462 p32: preserve raw bit values where polarity is unspecified."""
    if not isinstance(raw, str) or len(raw) != 4 or not raw.startswith("0x"):
        return {"extension_byte_warning": None, "operating_mode": None}
    try:
        value = int(raw[2:], 16)
    except ValueError:
        return {"extension_byte_warning": None, "operating_mode": None}
    if not 0 <= value <= 255:
        return {"extension_byte_warning": None, "operating_mode": None}
    mode = (value >> 6) & 3
    return {
        "extension_byte_warning": mode != 1,
        "operating_mode": "Nb" if mode == 1 else "unknown",
        "operating_mode_bits": mode,
        "calibration_seal_bit": bool(value & 0x20),
        "installation_side_bit": bool(value & 0x10),
        "secondary_selection_bit": bool(value & 4),
        "rolling_frame_oss_bit": bool(value & 2),
        "rolling_frame_mss_bit": bool(value & 1),
        "warning_scope": "operating_mode_only",
        "installation_side": None,
        "calibration_seal": None,
    }
