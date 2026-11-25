"""Bounded, sanitized normal-read archive and Excel export for manual analysis."""
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from ha_measurements import SENSORS
from mbus_records import passive_diagnostics
from i18n import resolve_language
from temperature_units import convert_temperature, UNITS

EXPORT_TEXT = {
    "Field": {
        "en-GB": "Field",
        "nb-NO": "Felt",
        "nn-NO": "Felt",
        "de-DE": "Feld"
    },
    "Value": {
        "en-GB": "Value",
        "nb-NO": "Verdi",
        "nn-NO": "Verdi",
        "de-DE": "Wert"
    },
    "Normal read count": {
        "en-GB": "Normal read count",
        "nb-NO": "Antall normalavlesninger",
        "nn-NO": "Tal på normalavlesingar",
        "de-DE": "Anzahl normaler Ablesungen"
    },
    "History status": {
        "en-GB": "History status",
        "nb-NO": "Historikkstatus",
        "nn-NO": "Historikkstatus",
        "de-DE": "Historiestatus"
    },
    "Validated snapshot": {
        "en-GB": "Validated snapshot",
        "nb-NO": "Validert historikk",
        "nn-NO": "Validert historikk",
        "de-DE": "Validierter Datenstand"
    },
    "Not available": {
        "en-GB": "Not available",
        "nb-NO": "Ikke tilgjengelig",
        "nn-NO": "Ikkje tilgjengeleg",
        "de-DE": "Nicht verfügbar"
    },
    "Meter timezone": {
        "en-GB": "Meter timezone",
        "nb-NO": "Målerens tidssone",
        "nn-NO": "Tidssona til målaren",
        "de-DE": "Zählerzeitzone"
    },
    "Unspecified; local meter time is not UTC": {
        "en-GB": "Unspecified; local meter time is not UTC",
        "nb-NO": "Uspesifisert; lokal målertid er ikke UTC",
        "nn-NO": "Uspesifisert; lokal målartid er ikkje UTC",
        "de-DE": "Nicht angegeben; lokale Zählerzeit ist nicht UTC"
    },
    "Historical dates": {
        "en-GB": "Historical dates",
        "nb-NO": "Historiske datoer",
        "nn-NO": "Historiske datoar",
        "de-DE": "Historische Daten"
    },
    "Meter storage time unverified; first-of-month estimates labeled separately": {
        "en-GB": "Meter storage time unverified; first-of-month estimates labeled separately",
        "nb-NO": "Målerens lagringstid er ikke verifisert; estimert første i måneden merkes separat",
        "nn-NO": "Lagringstida til målaren er ikkje verifisert; estimert første i månaden blir merkt separat",
        "de-DE": "Speicherzeitpunkt des Zählers nicht verifiziert; Schätzungen zum Monatsanfang separat gekennzeichnet"
    },
    "Export": {
        "en-GB": "Export",
        "nb-NO": "Eksport",
        "nn-NO": "Eksport",
        "de-DE": "Export"
    },
    "Decoded values only; no raw frames or actual meter ID": {
        "en-GB": "Decoded values only; no raw frames or actual meter ID",
        "nb-NO": "Kun dekodede verdier; ingen råtelegrammer eller faktisk måler-ID",
        "nn-NO": "Berre dekoda verdiar; ingen råtelegram eller faktisk målar-ID",
        "de-DE": "Nur dekodierte Werte; keine Rohtelegramme oder tatsächliche Zähler-ID"
    }
}

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


def make_sample(decoded, meter_id, read_at, alias_key, validated=None):
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
        kind = r.get("kind")
        if kind not in ALLOWED_KINDS:
            continue
        # An invalid or ambiguous current metric must not be exported as a
        # validated value just because another metric in the frame was valid.
        is_current = (r.get("storage") == 0 and r.get("tariff") == 0
                      and r.get("subunit", 0) == 0
                      and (r.get("function") == 0 or kind == "missing_time"
                           and r.get("function") == 3))
        if (validated is not None and kind in SENSORS and is_current
                and kind not in validated):
            continue
        value = r.get("value")
        if type(value) not in (int, float) or not (abs(value) < 1e15):
            continue
        records.append({k: r.get(k) for k in
                        ("kind", "storage", "tariff", "subunit", "function", "value", "unit")})
    return {"alias": _alias(meter_id, alias_key),
            "read_at_utc": stamp.astimezone(timezone.utc).isoformat(),
            "meter_local_time": local_time, "summer_time": summer_time,
            "status": decoded["status"], "records": records,
            "diagnostics": passive_diagnostics(decoded)}


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


def make_xlsx(samples, history=None, language='en-GB', temperature_unit=None):
    """No macros, formulas, raw telegrams, actual IDs or network paths."""
    from openpyxl import Workbook
    if not samples and not history:
        raise ValueError("No validated analysis data available")
    language = resolve_language(language)
    if temperature_unit is not None and temperature_unit not in UNITS:
        raise ValueError('unsupported temperature unit')
    wb = Workbook()
    info = wb.active
    info.title = "Info"
    for row in (("Field", "Value"),
                ("Normal read count", len(samples)),
                ("History status", "Validated snapshot" if history else "Not available"),
                ("Meter timezone", "Unspecified; local meter time is not UTC"),
                ("Historical dates", "Meter storage time unverified; first-of-month estimates labeled separately"),
                ("Export", "Decoded values only; no raw frames or actual meter ID")):
        info.append(tuple(EXPORT_TEXT.get(v, {}).get(language, v) if isinstance(v, str) else v for v in row))
    ws = wb.create_sheet("Normal records")
    ws.append(HEADERS)
    for sample in samples:
        for r in sample["records"]:
            value, unit = r["value"], r["unit"]
            if temperature_unit is not None:
                value, unit = convert_temperature(r["kind"], value, unit, temperature_unit)
            ws.append((sample["alias"], sample["read_at_utc"],
                       sample.get("meter_local_time"), sample.get("summer_time"),
                       sample["status"], r["kind"], r["storage"], r["tariff"],
                       r["subunit"], r["function"], value, unit))
    if any("diagnostics" in sample for sample in samples):
        diag = wb.create_sheet("Diagnostics")
        diag.append(("alias", "read_at_utc", "flow_measurement_interval_seconds",
                     "flow_averaging_interval_seconds", "firmware_version", "extension_byte"))
        for sample in samples:
            data = sample.get("diagnostics", {})
            diag.append((sample["alias"], sample["read_at_utc"]) + tuple(
                data.get(key) for key in ("flow_measurement_interval_seconds",
                "flow_averaging_interval_seconds", "firmware_version", "extension_byte")))
    if history:
        histories = [("", history)] if isinstance(history, dict) else list(history)
        stands = wb.create_sheet("Månedshistorikk")
        stands.append(("alias", "storage", "month_back", "cumulative_kwh",
                       "meter_date", "estimated_date", "date_source", "captured_at_utc",
                       "rollover_evidence"))
        periods = wb.create_sheet("Månedsforbruk")
        periods.append(("alias", "newer_storage", "older_storage", "period_kwh",
                        "meter_start_date", "meter_end_date", "estimated_start_date",
                        "estimated_end_date", "date_source", "rollover_evidence"))
        errors = None
        if any(snapshot.get("error_history") for _, snapshot in histories):
            errors = wb.create_sheet("Error history")
            errors.append(("alias", "read_at_utc", "code", "last_occurrence_meter_local", "active_status"))
        for alias, snapshot in histories:
            if errors is not None and snapshot.get("error_history"):
                data = snapshot["error_history"]
                for code in ("FT", "FS", "FE", "FF1", "FF2"):
                    errors.append((alias, data.get("read_at_utc"), code,
                                   data.get("last_occurrence_local", {}).get(code), "not_inferred"))
            provenance = snapshot.get("date_provenance", {})
            for field in ("history_read_at_utc", "normal_read_at_utc",
                          "meter_local_time_at_normal", "meter_summer_time_at_normal",
                          "clock_trusted_at_capture", "clock_trust_verified_at_utc",
                          "timezone_assumed", "rule", "estimate_applied"):
                info.append((f"{alias} / {field}", provenance.get(field)))
            if (len(snapshot.get("stands", ())) != 24 or
                    len(snapshot.get("bounded_periods", ())) != 23):
                raise ValueError("incomplete history snapshot")
            for r in snapshot["stands"]:
                stands.append((alias, r["storage"], r["month_back"], r["cumulative_kwh"],
                               r["meter_date"], r.get("estimated_date"), r["date_source"],
                               snapshot["captured_at_utc"], snapshot.get("rollover_evidence", "not_observed")))
            for r in snapshot["bounded_periods"]:
                periods.append((alias,) + tuple(r.get(k) for k in
                               ("newer_storage", "older_storage", "period_kwh",
                                "meter_start_date", "meter_end_date", "estimated_start_date",
                                "estimated_end_date", "date_source")) +
                               (snapshot.get("rollover_evidence", "not_observed"),))
    for sheet in wb:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
