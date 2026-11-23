"""Bounded, sanitized normal-read archive and Excel export for manual analysis."""
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path

ALLOWED_KINDS = {
    "energy", "volume", "power", "flow", "flow_temperature",
    "return_temperature", "temperature_difference", "operating_time",
    "flow_time", "missing_time", "actuality_duration", "averaging_interval",
}
HEADERS = ("alias", "read_at_utc", "meter_local_time", "summer_time",
           "status", "kind", "storage", "tariff", "subunit", "function",
           "value", "unit")


def _alias(meter_id, key_path):
    key_path = Path(key_path)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(secrets.token_bytes(32))
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError("invalid local alias key")
    return "Meter-" + hmac.new(key, meter_id.encode("ascii"), sha256).hexdigest()[:12]


def make_sample(decoded, meter_id, read_at, alias_key):
    """Call only after a validated normal frame passes select_measurements."""
    stamp = datetime.fromisoformat(read_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("read timestamp must include timezone")
    clock = [r for r in decoded["records"]
             if r.get("kind") == "meter_local_time"
             and r.get("storage") == 0 and r.get("tariff") == 0
             and r.get("subunit", 0) == 0 and r.get("function") == 0]
    local_time = clock[0].get("value") if len(clock) == 1 else None
    summer_time = clock[0].get("summer_time") if len(clock) == 1 else None
    records = []
    for r in decoded["records"]:
        if r.get("kind") not in ALLOWED_KINDS:
            continue
        value = r.get("value")
        if type(value) not in (int, float) or not (abs(value) < 1e15):
            continue
        records.append({k: r.get(k) for k in
                        ("kind", "storage", "tariff", "subunit", "function", "value", "unit")})
    return {"alias": _alias(meter_id, alias_key),
            "read_at_utc": stamp.astimezone(timezone.utc).isoformat(),
            "meter_local_time": local_time, "summer_time": summer_time,
            "status": decoded["status"], "records": records}


def append_sample(path, sample, limit=1000):
    """Keep at most the newest validated samples across app restarts."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    rows = (old[-(limit - 1):] if limit > 1 else []) + [
        json.dumps(sample, separators=(",", ":"), allow_nan=False)]
    temp = target.with_suffix(".tmp")
    try:
        temp.write_text("\n".join(rows) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()


def load_samples(path):
    target = Path(path)
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]


def make_xlsx(samples, history=None):
    """No macros, formulas, raw telegrams, actual IDs or network paths."""
    from openpyxl import Workbook
    if not samples and not history:
        raise ValueError("No validated analysis data available")
    wb = Workbook()
    info = wb.active
    info.title = "Info"
    for row in (("Field", "Value"),
                ("Normal read count", len(samples)),
                ("History status", "Validated snapshot" if history else "Not available"),
                ("Meter timezone", "Unspecified; local meter time is not UTC"),
                ("Historical dates", "Unverified unless explicitly documented"),
                ("Export", "Decoded values only; no raw frames or actual meter ID")):
        info.append(row)
    ws = wb.create_sheet("Normal records")
    ws.append(HEADERS)
    for sample in samples:
        for r in sample["records"]:
            ws.append((sample["alias"], sample["read_at_utc"],
                       sample.get("meter_local_time"), sample.get("summer_time"),
                       sample["status"], r["kind"], r["storage"], r["tariff"],
                       r["subunit"], r["function"], r["value"], r["unit"]))
    if history:
        histories = [("", history)] if isinstance(history, dict) else list(history)
        stands = wb.create_sheet("Månedshistorikk")
        stands.append(("alias", "storage", "month_back", "cumulative_kwh",
                       "meter_date", "date_source", "captured_at_utc"))
        periods = wb.create_sheet("Månedsforbruk")
        periods.append(("alias", "newer_storage", "older_storage", "period_kwh",
                        "meter_start_date", "meter_end_date", "date_source"))
        for alias, snapshot in histories:
            if (len(snapshot.get("stands", ())) != 24 or
                    len(snapshot.get("bounded_periods", ())) != 23):
                raise ValueError("incomplete history snapshot")
            for r in snapshot["stands"]:
                stands.append((alias, r["storage"], r["month_back"], r["cumulative_kwh"],
                               r["meter_date"], r["date_source"],
                               snapshot["captured_at_utc"]))
            for r in snapshot["bounded_periods"]:
                periods.append((alias,) + tuple(r.get(k) for k in
                               ("newer_storage", "older_storage", "period_kwh",
                                "meter_start_date", "meter_end_date", "date_source")))
    for sheet in wb:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
