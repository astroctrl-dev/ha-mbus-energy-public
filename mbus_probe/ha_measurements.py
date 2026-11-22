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
}


def select_measurements(decoded, expected_id):
    """Fail closed on identity/ambiguity; allow only 0x10 as dev warning."""
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
    for record in decoded.get("records", ()):
        kind = record.get("kind")
        if kind not in SENSORS or not record.get("current_record"):
            continue
        unit = SENSORS[kind][0]
        value = record.get("value")
        if record.get("unit") != unit or type(value) not in (int, float):
            raise ValueError(f"invalid current {kind} record")
        if kind in selected:
            raise ValueError(f"ambiguous duplicate current {kind}")
        selected[kind] = value
    missing = SENSORS.keys() - selected.keys()
    if missing:
        raise ValueError("missing valid current records: " + ", ".join(sorted(missing)))
    return selected
