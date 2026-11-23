"""Validated frame-3 snapshot model. No HA Energy backfill or meter date inference."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def build_snapshot(months, captured_at):
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
         "meter_date": None, "date_source": "unverified"}
        for n in range(1, 25)
    ]
    periods = []
    for n in range(1, 24):
        delta = by_back[n] - by_back[n + 1]
        if delta < 0:
            raise ValueError("historical stand decreased")
        periods.append({"newer_storage": n + 1, "older_storage": n + 2,
                        "period_kwh": delta, "meter_start_date": None,
                        "meter_end_date": None, "date_source": "unverified"})
    return {"schema_version": 1, "source": "T230 frame 3", "captured_at_utc": stamp.astimezone(timezone.utc).isoformat(),
            "stands": stands, "bounded_periods": periods}


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
