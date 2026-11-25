"""Validated frame-3 snapshot model. No HA Energy backfill or meter date inference."""
import json
import os
from datetime import datetime, timezone, date, timedelta
from calendar import monthrange
from zoneinfo import ZoneInfo
from pathlib import Path


def estimated_month_at_capture(captured_at, observation, clock_trusted, zone_name,
                               history_read_at=None):
    """Return a first-of-month estimate only when both clocks agree after grace."""
    if not clock_trusted or not observation or not history_read_at:
        return None
    try:
        zone = ZoneInfo(zone_name)
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        read_at = datetime.fromisoformat(observation["last_successful_read_utc"])
        history_at = datetime.fromisoformat(history_read_at)
        meter = datetime.fromisoformat(observation["meter_local_time"])
        if (captured.tzinfo is None or read_at.tzinfo is None or
                history_at.tzinfo is None or meter.tzinfo is not None):
            return None
        system = read_at.astimezone(zone)
        first_system = history_at.astimezone(zone)
        elapsed = (read_at - history_at).total_seconds()
        if not 0 <= elapsed <= 600 or first_system.utcoffset() != system.utcoffset():
            return None
        # The meter reports only whole minutes. Treat its reported time as a
        # lower bound and project it back to the earlier history telegram.
        meter_at_history = meter - (read_at - history_at)
        # Meter-local time has no encoded timezone. Compare local wall times.
        if abs((system.replace(tzinfo=None) - meter).total_seconds()) > 120:
            return None
        if observation["meter_summer_time"] != bool(system.dst()):
            return None
        end_system = captured.astimezone(zone)
        if any((t.year, t.month) != (system.year, system.month)
               for t in (meter, meter_at_history, first_system, end_system)):
            return None
        if any(t.day == 1 and t.hour == 0 and t.minute < 15
               for t in (first_system, meter_at_history, meter, system, end_system)):
            return None
        return date(system.year, system.month, 1)
    except (KeyError, ValueError, TypeError):
        return None


def _month_start(anchor, position):
    index = anchor.year * 12 + anchor.month - 1 - (position - 1)
    return date(index // 12, index % 12 + 1, 1).isoformat()


def configured_anchor(observation, history_read_at, zone_name):
    """Derive latest completed set day from meter wall clock; avoid ambiguous rollover."""
    try:
        setting = observation["monthly_set_day"]
        day, hour, minute = (setting[k] for k in ("day", "hour", "minute"))
        if not (1 <= day <= 31 and 0 <= hour < 24 and 0 <= minute < 60):
            return None
        meter = datetime.fromisoformat(observation["meter_local_time"])
        read_at = datetime.fromisoformat(observation["last_successful_read_utc"])
        history_at = datetime.fromisoformat(history_read_at)
        elapsed = read_at - history_at
        zone = ZoneInfo(zone_name)
        if not 0 <= elapsed.total_seconds() <= 600 or meter.tzinfo is not None:
            return None
        if read_at.astimezone(zone).utcoffset() != history_at.astimezone(zone).utcoffset():
            return None
        if abs((read_at.astimezone(zone).replace(tzinfo=None) - meter).total_seconds()) > 120:
            return None
        if observation["meter_summer_time"] != bool(read_at.astimezone(zone).dst()):
            return None
        at_history = meter - elapsed
        # Days beyond the end of shorter months are instrument-dependent.
        # Do not infer those dates until the meter's convention is verified.
        if day > 28:
            return None
        anchor = at_history.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if abs((at_history - anchor).total_seconds()) < 900:
            return None
        if at_history < anchor:
            index = anchor.year * 12 + anchor.month - 2
            anchor = anchor.replace(year=index // 12, month=index % 12 + 1)
        return anchor
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def configured_timestamp(anchor, position):
    index = anchor.year * 12 + anchor.month - position
    return anchor.replace(year=index // 12, month=index % 12 + 1).isoformat(timespec="minutes")


def build_snapshot(months, captured_at, estimated_month=None, configured=None):
    """Return 24 cumulative kWh stands and 23 bounded period differences."""
    stamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("capture timestamp must include a timezone")
    if len(months) != 24:
        raise ValueError("exactly 24 historical stands required")
    by_back = {}
    for item in months:
        n = item.get("month_back")
        value = item.get("value")
        if type(n) is not int or n not in range(1, 25) or n in by_back:
            raise ValueError("invalid or duplicate historical position")
        if item.get("unit") != "kWh" or type(value) not in (int, float) or not (0 <= value < 1e12):
            raise ValueError("invalid cumulative kWh")
        by_back[n] = value
    if set(by_back) != set(range(1, 25)):
        raise ValueError("missing historical position")
    stands = [
        {"storage": n + 1, "month_back": n, "cumulative_kwh": by_back[n],
         "meter_date": None,
         "estimated_date": _month_start(estimated_month, n) if estimated_month else None,
         "date_source": "estimated_first_of_month" if estimated_month else "unverified"}
        for n in range(1, 25)
    ]
    periods = []
    for n in range(1, 24):
        delta = by_back[n] - by_back[n + 1]
        if delta < 0:
            raise ValueError("historical stand decreased")
        periods.append({"newer_storage": n + 1, "older_storage": n + 2,
                        "period_kwh": delta, "meter_start_date": None,
                        "meter_end_date": None,
                        "estimated_start_date": _month_start(estimated_month, n + 1) if estimated_month else None,
                        "estimated_end_date": _month_start(estimated_month, n) if estimated_month else None,
                        "date_source": "estimated_first_of_month" if estimated_month else "unverified"})
    if configured is not None:
        for n, row in enumerate(stands, 1):
            row.update(estimated_date=configured_timestamp(configured, n),
                       date_source="derived_monthly_set_day")
        for n, row in enumerate(periods, 1):
            row.update(estimated_start_date=configured_timestamp(configured, n + 1),
                       estimated_end_date=configured_timestamp(configured, n),
                       date_source="derived_monthly_set_day")
    return {"schema_version": 2, "source": "T230 frame 3",
            "date_assumption": ("current meter set day assumed unchanged; no frame-4 storage time" if configured else "first of month inferred from capture clocks; no frame-4 storage time"), "captured_at_utc": stamp.astimezone(timezone.utc).isoformat(),
            "stands": stands, "bounded_periods": periods}


def detect_month_shift(previous, current):
    """Positive rollover evidence from two complete independent frame-3 snapshots."""
    if not previous or len(previous.get("stands", ())) != 24:
        return False
    older = {r.get("month_back"): r.get("cumulative_kwh") for r in previous["stands"]}
    newer = {r.get("month_back"): r.get("cumulative_kwh") for r in current["stands"]}
    if set(older) != set(range(1, 25)) or set(newer) != set(range(1, 25)):
        return False
    return (newer[1] > older[1] and
            all(newer[n + 1] == older[n] for n in range(1, 24)))


def save_snapshot(path, snapshot):
    """Replace a validated snapshot atomically; failed collection never erases it."""
    if len(snapshot.get("stands", [])) != 24 or len(snapshot.get("bounded_periods", [])) != 23:
        raise ValueError("incomplete snapshot")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(snapshot, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
