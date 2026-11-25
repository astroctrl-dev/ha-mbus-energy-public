"""Conservative projection of clock fields from a validated normal T230 frame.

Meter-local time has no encoded timezone. Never infer an absolute offset.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


def configured_local(stamp, zone_name, use_dst=True):
    local = stamp.astimezone(ZoneInfo(zone_name))
    if use_dst:
        return local
    return stamp.astimezone(timezone(local.utcoffset() - (local.dst() or timedelta(0))))



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


def assess_clock(decoded, read_at, zone_name, use_dst=True):
    """Compare meter wall time to configured zone, without claiming meter UTC."""
    from zoneinfo import ZoneInfo
    try:
        obs = clock_observation(decoded, read_at)
        local = configured_local(datetime.fromisoformat(read_at.replace("Z", "+00:00")), zone_name, use_dst)
        meter = datetime.fromisoformat(obs["meter_local_time"])
        if meter.tzinfo is not None:
            raise ValueError("unexpected meter offset")
        offset = int((meter - local.replace(tzinfo=None)).total_seconds())
        dst_mismatch = obs["meter_summer_time"] != bool(local.dst())
        return {"clock_offset_seconds": offset,
                "clock_out_of_sync": abs(offset) > 120,
                "clock_dst_mismatch": dst_mismatch}
    except (ValueError, TypeError, KeyError):
        return {"clock_offset_seconds": None, "clock_out_of_sync": None,
                "clock_dst_mismatch": None}


def seasonal_key(stamp, zone_name, use_dst=True):
    """Stable key for the current seasonal policy, including configuration changes."""
    local = configured_local(stamp, zone_name, use_dst)
    return f"{zone_name}:{int(use_dst)}:{local.year}:{int(bool(local.dst()))}:{local.utcoffset().total_seconds()}"


def seasonal_offset(stamp, zone_name, use_dst, meter_dst, delta):
    """Recognize only a directionally consistent seasonal offset and DST bit."""
    if not use_dst:
        return False
    local = configured_local(stamp, zone_name, True)
    if meter_dst == bool(local.dst()):
        return False
    # Find the most recent opposite season, using actual IANA offsets.
    for days in range(1, 371):
        prior = (stamp.astimezone(timezone.utc) - timedelta(days=days)).astimezone(ZoneInfo(zone_name))
        if bool(prior.dst()) == meter_dst:
            shift = (local.utcoffset() - prior.utcoffset()).total_seconds()
            return shift != 0 and abs(delta - shift) <= 300
    return False
