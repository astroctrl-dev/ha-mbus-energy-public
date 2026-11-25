"""Read-only projection of validated saved frame-4 evidence."""
from math import isfinite
from decimal import Decimal

def archive_attributes(stand):
    evidence = stand.get("frame4") or {}
    return {"cumulative_m3": evidence.get("cumulative_m3"),
            "frame4_meter_storage_local_time": evidence.get("meter_storage_local_time"),
            "frame4_first_read_at_utc": evidence.get("first_read_at_utc"),
            "monthly_maxima": evidence.get("maxima") or {}}

def period_volume(newer, older):
    a,b = (archive_attributes(row)["cumulative_m3"] for row in (newer,older))
    if any(type(v) not in (int,float) or not isfinite(v) or v < 0 for v in (a,b)):
        return None
    if a < b:
        return None
    return float(Decimal(str(a))-Decimal(str(b)))


def period_archive_attributes(period, newer, older):
    """Small public projection; preserve all raw provenance in saved history."""
    evidence = archive_attributes(newer)
    instrument_date = evidence["frame4_meter_storage_local_time"]
    maxima = evidence["monthly_maxima"]
    # A shared timestamp is meaningful only when all four values have the
    # same proven physical observation timestamp. Never invent one.
    kinds = ("power", "flow", "flow_temperature", "return_temperature")
    stamps = [maxima.get(k, {}).get("read_at_utc") for k in kinds]
    shared = stamps[0] if stamps[0] and len(set(stamps)) == 1 and all(
        maxima.get(k, {}).get("value") is not None for k in kinds) else None
    public_maxima = {"read_at_utc": shared}
    for kind in kinds:
        fields = maxima.get(kind) or {}
        if fields.get("value") is not None:
            public_maxima[kind] = {k: fields.get(k) for k in ("value", "unit", "meter_local_time")}
            if shared is None:
                public_maxima[kind]["read_at_utc"] = fields.get("read_at_utc")
    return {
        "history_captured_at_utc": period.get("group_updated_at_utc") or period.get("read_at_utc"),
        "meter_date_status": "instrument_reported" if instrument_date else period.get("date_source", "unverified"),
        "meter_storage_date": instrument_date or period.get("meter_end_date") or period.get("estimated_end_date"),
        "period_m3": period_volume(newer, older),
        "monthly_maxima": public_maxima,
    }
