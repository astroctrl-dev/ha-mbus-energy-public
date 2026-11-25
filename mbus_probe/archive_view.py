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
    """Associate monthly maxima with the period ending at the newer stand."""
    evidence = archive_attributes(newer)
    return {"period_m3": period_volume(newer, older),
            "monthly_maxima": evidence["monthly_maxima"],
            "instrument_storage_local_time": evidence["frame4_meter_storage_local_time"],
            "frame4_first_read_at_utc": evidence["frame4_first_read_at_utc"],
            "group_updated_at_utc": period.get("group_updated_at_utc")}
