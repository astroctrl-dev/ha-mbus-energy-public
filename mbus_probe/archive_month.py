"""Offline frame-4 archive decoder, TKB3462 pp25–27. No bus I/O."""
from math import isfinite
from datetime import datetime
from mbus_records import t230_footer
from maxima import FIELDS

def decode_month(decoded, month_back):
    if type(month_back) is not int or not 1 <= month_back <= 24:
        raise ValueError("invalid archive position")
    if not t230_footer(decoded, 4):
        raise ValueError("not verified frame 4 footer")
    storage = month_back + 1
    records = decoded.get("records", ())
    def find(dif, vif, tariff=0, extension=""):
        # DIF storage bit differs for odd storage positions.
        matches = [r for r in records if r.get("dif", 0) & 0xbf == dif
                   and r.get("storage") == storage and r.get("tariff") == tariff
                   and r.get("subunit") == 0 and r.get("vif") == vif
                   and r.get("vife_hex") == extension]
        if len(matches) > 1:
            raise ValueError("ambiguous archive field")
        return matches[0] if matches else {}
    def number(record, kind, unit, signed=False):
        v = record.get("value")
        if (record.get("kind") == kind and record.get("unit") == unit
                and type(v) in (int, float) and isfinite(v) and (signed or v >= 0)):
            return v
        return None
    def time(record):
        try:
            raw = bytes.fromhex(record.get("raw_hex", ""))
            if len(raw) != 4 or raw[0] & 128:
                return None
            year = (raw[2] >> 5) | ((raw[3] >> 4) << 3)
            if year > 99:
                return None
            return datetime(2000+year, raw[3]&15, raw[2]&31, raw[1]&31,
                            raw[0]&63).isoformat(timespec="minutes")
        except (TypeError, ValueError):
            return None
    energy = number(find(0x8c, 0x06), "energy", "kWh")
    volume = number(find(0x8c, 0x14), "volume", "m3")
    date = time(find(0x84, 0x6d))
    if energy is None or volume is None or date is None:
        raise ValueError("missing verified monthly anchor, energy or volume")
    result = {"month_back": month_back, "storage": storage,
              "cumulative_kwh": energy, "cumulative_m3": volume,
              "meter_storage_local_time": date, "maxima": {}}
    for kind, (vif, unit) in FIELDS.items():
        value = number(find(0x9b, vif, 1), kind, unit, kind.endswith("_temperature"))
        result["maxima"][kind] = {"value": value, "unit": unit,
            "meter_local_time": time(find(0x94, vif|128, 1, "6f")) if value is not None else None}
    return result
