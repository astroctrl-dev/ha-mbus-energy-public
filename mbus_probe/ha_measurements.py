"""Conservative Home Assistant measurement projection for validated T230 frames.

Only call this with the result of mbus_probe.validate on a checksum-verified frame.
Unknown VIFs, maxima, historical records, tariff registers and errors are excluded.
"""

SENSORS = {
    "energy": ("kWh", "energy", "total_increasing"),
    "volume": ("m3", "volume", "total_increasing"),
    "power": ("kW", "power", "measurement"),
    "flow": ("m3/h", "volume_flow_rate", "measurement"),
    "flow_temperature": ("C", "temperature", "measurement"),
    "return_temperature": ("C", "temperature", "measurement"),
    "temperature_difference": ("K", None, "measurement"),
    "operating_time": ("h", None, "total_increasing"),
    "flow_time": ("h", None, "total_increasing"),
    "missing_time": ("h", None, "total_increasing"),
}

OPTIONAL_SENSORS = frozenset({"operating_time", "flow_time", "missing_time"})
REQUIRED_SENSORS = frozenset(SENSORS) - OPTIONAL_SENSORS


def select_measurements(decoded, expected_id):
    """Reject bad frames/identity; validate each measurement independently."""
    # Report only the failed check, never the actual/expected meter identifier.
    # All failures remain fail-closed; no measurement is published.
    checks = (
        ("frame_type", decoded.get("type") == "long"),
        ("control", decoded.get("control") in (8, 24)),
        ("ci", decoded.get("ci") == 0x72),
        ("manufacturer", decoded.get("manufacturer") == "LUG"),
        ("meter_id", decoded.get("meter_id") == expected_id),
        ("medium", decoded.get("medium_code") == 4),
    )
    for field, valid in checks:
        if not valid:
            raise ValueError("invalid T230 " + field)
    if decoded.get("status") not in (0, 0x10):
        status = decoded.get("status")
        if type(status) is int and 0 <= status <= 255:
            raise ValueError(f"invalid T230 status=0x{status:02x}")
        raise ValueError("invalid T230 status")
    selected = {}
    invalid = set()
    for record in decoded.get("records", ()):
        kind = record.get("kind")
        if kind not in SENSORS:
            continue
        if kind == "missing_time":
            # T230 marks current missing hours as a value-during-error record.
            if not (record.get("storage") == 0 and record.get("tariff") == 0
                    and record.get("subunit", 0) == 0 and record.get("function") == 3):
                continue
        elif not record.get("current_record"):
            continue
        unit = SENSORS[kind][0]
        value = record.get("value")
        if kind in invalid:
            continue
        if kind in selected:
            selected.pop(kind)
            invalid.add(kind)
            continue
        if (record.get("unit") != unit or type(value) not in (int, float)
                or not float("-inf") < value < float("inf")
                or (value < 0 and kind not in ("power", "temperature_difference"))):
            invalid.add(kind)
            continue
        selected[kind] = value
    if not selected:
        raise ValueError("no valid current measurements")
    return selected
