"""Pure rolling-history merge; preserve original dates and physical read provenance.

Only preserve rows when an unambiguous alignment is demonstrated. No bus I/O.
"""
from copy import deepcopy


def merge_history(previous, incoming, read_at, *, replace=False):
    result = deepcopy(incoming)
    new = result["stands"]
    old = (previous or {}).get("stands", [])
    # Match the ordered overlapping sequence, not a single energy value:
    # flat consumption can produce repeated identical cumulative stands.
    shifts = []
    if len(old) == len(new) == 24:
        for shift in range(24):
            overlap = 24 - shift
            if overlap < 3:
                continue
            if all(new[i+shift]["cumulative_kwh"] == old[i]["cumulative_kwh"]
                   for i in range(overlap)):
                # Date agreement or explicit observed rollover is required.
                if (new[shift].get("estimated_date") and old[0].get("estimated_date")
                    and new[shift]["estimated_date"][:7] == old[0]["estimated_date"][:7]):
                    shifts.append(shift)
    shift = shifts[0] if len(shifts) == 1 else None
    if previous and shift is None and not replace:
        raise ValueError("cannot align saved history without overwriting existing dates")
    for i, row in enumerate(new):
        row["read_at_utc"] = read_at
        if not replace and shift is not None and i >= shift:
            prior = deepcopy(old[i-shift])
            prior.setdefault("read_at_utc", (previous.get("date_provenance") or {}).get("history_read_at_utc"))
            prior.update(storage=row["storage"], month_back=row["month_back"])
            new[i] = prior
    for i, period in enumerate(result["bounded_periods"]):
        newer, older = new[i:i+2]
        period.update(estimated_start_date=older.get("estimated_date"),
                      estimated_end_date=newer.get("estimated_date"),
                      newer_read_at_utc=newer.get("read_at_utc"),
                      older_read_at_utc=older.get("read_at_utc"))
        period["read_at_utc"] = newer.get("read_at_utc")
        period["estimated_date"] = newer.get("estimated_date")
        if newer.get("date_source") == older.get("date_source"):
            period["date_source"] = newer.get("date_source")
    return result
