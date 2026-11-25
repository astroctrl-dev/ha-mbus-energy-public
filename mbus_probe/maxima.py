"""T230 frame-1 maximum projection. No bus I/O or current-value mutation."""
from datetime import datetime
from math import isfinite
from mbus_records import t230_footer

FIELDS = {
    "power": (0x2d, "kW"),
    "flow": (0x3b, "m3/h"),
    "flow_temperature": (0x5a, "C"),
    "return_temperature": (0x5e, "C"),
}


def project_maxima(decoded):
    """Return independent maxima; timestamps are unzoned meter wall times."""
    out = {kind: {"maximum": None, "maximum_meter_local_time": None,
                  "previous_annual_maximum": None, "unit": unit}
           for kind, (_, unit) in FIELDS.items()}
    if not t230_footer(decoded, 1):
        return out
    records = decoded.get("records", ())
    def unique(dif, vif, vife=""):
        matches = [r for r in records if r.get("dif") == dif
                   and r.get("dife_hex") == "10" and r.get("vif") == vif
                   and r.get("vife_hex") == vife]
        return matches[0] if len(matches) == 1 else {}
    for kind, (vif, unit) in FIELDS.items():
        for dif, field in ((0x9b, "maximum"), (0xdb, "previous_annual_maximum")):
            record = unique(dif, vif)
            v = record.get("value")
            if (record.get("kind") == kind and record.get("unit") == unit
                    and type(v) in (int, float) and isfinite(v)
                    and (v >= 0 or kind.endswith("_temperature"))):
                out[kind][field] = v
        stamp = unique(0x94, vif | 0x80, "6f")
        if out[kind]["maximum"] is None:
            continue
        try:
            raw = bytes.fromhex(stamp.get("raw_hex", ""))
            if len(raw) != 4 or raw[0] & 0x80:
                continue
            year = (raw[2] >> 5) | ((raw[3] >> 4) << 3)
            if year > 99:
                continue
            out[kind]["maximum_meter_local_time"] = datetime(
                2000+year, raw[3]&15, raw[2]&31, raw[1]&31, raw[0]&63
            ).isoformat(timespec="minutes")
        except (TypeError, ValueError):
            pass
    return out
