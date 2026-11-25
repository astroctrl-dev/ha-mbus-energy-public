"""Supplement a validated energy snapshot with frame-4 evidence, without rewriting it."""
from copy import deepcopy
from datetime import datetime
from math import isfinite

def supplement_month(snapshot, archive, read_at):
    """Require matching storage, cumulative energy and known calendar month.
    Existing non-null fields are immutable. Return new snapshot or raise.
    Caller must serialize access and atomically persist the returned snapshot.
    """
    stamp = datetime.fromisoformat(read_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("read timestamp must include offset")
    local = datetime.fromisoformat(archive["meter_storage_local_time"])
    if local.tzinfo is not None:
        raise ValueError("expected meter-local time")
    if type(archive["storage"]) is not int or not 2 <= archive["storage"] <= 25:
        raise ValueError("invalid storage")
    rows = snapshot["stands"]
    matches = [r for r in rows if r["storage"] == archive["storage"]]
    if len(matches) != 1:
        raise ValueError("archive position not unique")
    row = matches[0]
    if row["month_back"] != archive["month_back"] or row["month_back"] != row["storage"]-1:
        raise ValueError("archive position mismatch")
    if row["cumulative_kwh"] != archive["cumulative_kwh"]:
        raise ValueError("archive energy mismatch")
    expected = row.get("meter_date") or row.get("estimated_date")
    if not expected or expected[:7] != local.isoformat()[:7]:
        raise ValueError("archive calendar alignment not established")
    volume = archive["cumulative_m3"]
    if type(volume) not in (int, float) or not isfinite(volume) or volume < 0:
        raise ValueError("invalid archive volume")
    result = deepcopy(snapshot)
    target = next(r for r in result["stands"] if r["storage"] == archive["storage"])
    def fill(dst, src):
        for k, v in src.items():
            if v is None:
                continue
            if dst.get(k) is None:
                dst[k] = deepcopy(v)
            elif isinstance(v, dict) and isinstance(dst[k], dict):
                fill(dst[k], v)
            elif dst[k] != v:
                raise ValueError("archive conflict: "+k)
    evidence = target.setdefault("frame4", {})
    prior_maxima = deepcopy(evidence.get("maxima") or {})
    incoming_maxima = {kind: {k:v for k,v in fields.items() if k in ("value","unit","meter_local_time")}
                       for kind, fields in archive.get("maxima", {}).items()}
    fill(evidence, {"cumulative_m3": volume,
                    "meter_storage_local_time": archive["meter_storage_local_time"],
                    "maxima": incoming_maxima})
    for kind, fields in incoming_maxima.items():
        prior = prior_maxima.get(kind) or {}
        saved = evidence["maxima"][kind]
        if fields.get("value") is not None and prior.get("value") is None:
            saved["read_at_utc"] = stamp.isoformat()
        if fields.get("meter_local_time") is not None and prior.get("meter_local_time") is None:
            saved["meter_local_time_read_at_utc"] = stamp.isoformat()
    # Preserve first successful read; later completion does not replace it.
    if evidence.get("first_read_at_utc") is None:
        evidence["first_read_at_utc"] = stamp.isoformat()
    if result != snapshot:
        for period in result["bounded_periods"]:
            period["group_updated_at_utc"] = stamp.isoformat()
    return result
