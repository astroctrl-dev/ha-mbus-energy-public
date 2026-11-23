"""Conservative projection of clock fields from a validated normal T230 frame.

Meter-local time has no encoded timezone. Never infer an absolute offset.
"""
from datetime import datetime, timezone


def clock_observation(decoded, read_at):
    stamp = datetime.fromisoformat(read_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("read_at must be timezone-aware")
    records = [r for r in decoded.get("records", ())
               if r.get("kind") == "meter_local_time"
               and r.get("storage") == 0 and r.get("tariff") == 0
               and r.get("subunit", 0) == 0 and r.get("function") == 0]
    if len(records) != 1 or records[0].get("timezone") != "unspecified":
        raise ValueError("missing or ambiguous meter-local clock")
    r = records[0]
    datetime.fromisoformat(r["value"])  # Reject malformed source before presentation.
    if type(r.get("summer_time")) is not bool:
        raise ValueError("invalid summer-time bit")
    return {"meter_local_time": r["value"],
            "meter_timezone": "unspecified",
            "meter_summer_time": r["summer_time"],
            "last_successful_read_utc": stamp.astimezone(timezone.utc).isoformat(),
            "clock_offset_seconds": None}
