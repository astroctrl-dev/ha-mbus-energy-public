"""MQTT Discovery adapter for validated, current T230 readings.

MQTT client is injected so message generation can be tested without a broker.
The caller must set a broker Last Will of 'offline' on availability_topic.
"""
import hashlib
import json
from datetime import datetime, timezone

from ha_measurements import REQUIRED_SENSORS, SENSORS, select_measurements
from temperature_units import DIFFERENCE
from mbus_records import passive_diagnostics
from maxima import project_maxima, FIELDS
from archive_view import archive_attributes, period_archive_attributes

HA_UNITS = {"kWh": "kWh", "m3": "m³", "kW": "kW", "m3/h": "m³/h",
            "C": "°C", "K": "K", "h": "h"}
BRIDGE_AVAILABILITY = "mbus/t230/bridge/availability"
ERROR_EVENTS = (
    ("FT", "last_negative_temperature_difference", "Last Negative Temperature Difference (FT)"),
    ("FF2", "last_reverse_flow", "Last Reverse Flow (FF2)"),
    ("FS", "last_sensor_error", "Last Sensor Error (FS)"),
    ("FE", "last_electronic_error", "Last Electronic Error (FE)"),
    ("FF1", "last_flow_rate_error", "Last Flow Rate Error (FF1)"),
)


def device_key(meter_id):
    if not (len(meter_id) == 8 and meter_id.isdigit()):
        raise ValueError("expected an 8-digit meter identity")
    return hashlib.sha256(("LUG:T230:" + meter_id).encode()).hexdigest()[:16]


def availability_topic(key):
    return f"mbus/t230/{key}/availability"


def discovery_messages(meter_id):
    key = device_key(meter_id)
    availability = availability_topic(key)
    device = {"identifiers": [f"mbus_t230_{key}"],
              "name": "Landis+Gyr T230", "manufacturer": "Landis+Gyr",
              "model": "T230"}
    messages = []
    for kind, (unit, device_class, state_class) in SENSORS.items():
        topic = f"homeassistant/sensor/mbus_t230_{key}_{kind}/config"
        payload = {
            "name": kind.replace("_", " ").title(),
            "unique_id": f"mbus_t230_{key}_{kind}",
            "device": device, "state_topic": f"mbus/t230/{key}/{kind}/state",
            "availability": [{"topic": availability}, {"topic": BRIDGE_AVAILABILITY}],
            "availability_mode": "all", "unit_of_measurement": HA_UNITS[unit],
            "state_class": state_class,
        }
        if kind in FIELDS:
            payload["json_attributes_topic"] = f"mbus/t230/{key}/{kind}/attributes"
        if kind == DIFFERENCE:
            # Keep the native K value and let HA convert intervals without an offset.
            payload["device_class"] = "temperature_delta"
        elif device_class:
            payload["device_class"] = device_class
        messages.append((topic, json.dumps(payload), True))
    for kind, label in (("meter_status", "M-Bus status"),
                        ("firmware_version", "Firmware Version"),
                        ("data_quality", "Datakvalitet"),
                        ("meter_local_time", "Målerklokke (lokal tid)"),
                        ("meter_summer_time", "Målerens sommertidbit"),
                        ("last_successful_read_utc", "Siste avlesning (UTC)")):
        topic = f"homeassistant/sensor/mbus_t230_{key}_{kind}/config"
        payload = {
            "name": label,
            "unique_id": f"mbus_t230_{key}_{kind}",
            "device": device,
            "state_topic": f"mbus/t230/{key}/{kind}/state",
            "availability": [{"topic": availability}, {"topic": BRIDGE_AVAILABILITY}],
            "availability_mode": "all",
            "entity_category": "diagnostic",
        }
        if kind in ("meter_local_time", "meter_status"):
            payload["json_attributes_topic"] = f"mbus/t230/{key}/{kind}/attributes"
        if kind == "last_successful_read_utc":
            payload["device_class"] = "timestamp"
        messages.append((topic, json.dumps(payload), True))
    for kind, label in (("dst_transition_failed", "DST Transition Failed"),
                        ("dst_clock_override", "DST Clock Override")):
        payload = {"name": label, "unique_id": f"mbus_t230_{key}_{kind}",
                   "device": device, "state_topic": f"mbus/t230/{key}/{kind}/state",
                   "json_attributes_topic": f"mbus/t230/{key}/{kind}/attributes",
                   "payload_on": "ON", "payload_off": "OFF",
                   "availability": [{"topic": availability}, {"topic": BRIDGE_AVAILABILITY}],
                   "availability_mode": "all", "entity_category": "diagnostic"}
        if kind == "dst_transition_failed":
            payload["device_class"] = "problem"
        messages.append((f"homeassistant/binary_sensor/mbus_t230_{key}_{kind}/config",
                         json.dumps(payload), True))
    return messages


def publish_dst_diagnostics(client, meter_id, state):
    """Publish persisted evidence; unknown must never be represented as OFF."""
    key = device_key(meter_id)
    incidents = state.get("incidents") or []
    attributes = {"last_transition": state.get("last_transition"),
                  "last_incident": incidents[-1] if incidents else None,
                  "state_status": state.get("state_status", "stored")}
    for kind in ("dst_transition_failed", "dst_clock_override"):
        value = state.get(kind)
        payload = "ON" if value is True else "OFF" if value is False else "None"
        for suffix, data in (("attributes", json.dumps(attributes)), ("state", payload)):
            result = client.publish(f"mbus/t230/{key}/{kind}/{suffix}", data,
                                    qos=1, retain=False)
            if result.rc:
                raise ConnectionError("MQTT DST diagnostic publish failed")
            result.wait_for_publish(timeout=5)


def history_discovery_messages(meter_id):
    """Position labels deliberately do not claim calendar dates or HA Energy totals."""
    key = device_key(meter_id)
    device = {"identifiers": [f"mbus_t230_{key}"],
              "name": "Landis+Gyr T230", "manufacturer": "Landis+Gyr", "model": "T230"}
    for index in range(1, 25):
        kind = f"history_stand_{index}"
        yield (f"homeassistant/sensor/mbus_t230_{key}_{kind}/config",
               json.dumps({"name": f"Historisk målerstand −{index:02d}",
                           "unique_id": f"mbus_t230_{key}_{kind}", "device": device,
                           "default_entity_id": f"sensor.mbus_t230_{key}_historisk_malerstand_{index:02d}",
                           "state_topic": f"mbus/t230/{key}/{kind}/state",
                           "json_attributes_topic": f"mbus/t230/{key}/{kind}/attributes",
                           "availability": [{"topic": availability_topic(key)},
                                            {"topic": BRIDGE_AVAILABILITY}],
                           "availability_mode": "all", "unit_of_measurement": "kWh",
                           "entity_category": "diagnostic",
                           "icon": "mdi:counter"}), True)
    for index in range(1, 24):
        kind = f"history_period_{index}"
        yield (f"homeassistant/sensor/mbus_t230_{key}_{kind}/config",
               json.dumps({"name": f"Forbruk mellom −{index+1:02d} og −{index:02d}",
                           "unique_id": f"mbus_t230_{key}_{kind}", "device": device,
                           "default_entity_id": f"sensor.mbus_t230_{key}_manedsforbruk_{index:02d}",
                           "state_topic": f"mbus/t230/{key}/{kind}/state",
                           "json_attributes_topic": f"mbus/t230/{key}/{kind}/attributes",
                           "availability": [{"topic": availability_topic(key)},
                                            {"topic": BRIDGE_AVAILABILITY}],
                           "availability_mode": "all", "unit_of_measurement": "kWh",
                           "entity_category": "diagnostic",
                           "icon": "mdi:calendar-month"}), True)


def publish_history(client, meter_id, snapshot):
    """Publish validated saved history; never feed historical values into energy totals."""
    stands = snapshot.get("stands", [])
    periods = snapshot.get("bounded_periods", [])
    if len(stands) != 24 or len(periods) != 23:
        raise ValueError("incomplete monthly history")
    by_stand = {s["month_back"]: s for s in stands}
    by_period = {p["newer_storage"] - 1: p for p in periods}
    if set(by_stand) != set(range(1, 25)) or set(by_period) != set(range(1, 24)):
        raise ValueError("invalid monthly positions")
    capture = snapshot.get("captured_at_utc")
    if not isinstance(capture, str) or not capture:
        raise ValueError("missing history capture timestamp")
    key = device_key(meter_id)
    for topic, payload, retain in history_discovery_messages(meter_id):
        result = client.publish(topic, payload, qos=1, retain=retain)
        if result.rc:
            raise ConnectionError("MQTT history discovery publish failed")
        result.wait_for_publish(timeout=5)
    errors = snapshot.get("error_history")
    if isinstance(errors, dict) and isinstance(errors.get("read_at_utc"), str):
        for code, kind, label in ERROR_EVENTS:
            root = f"mbus/t230/{key}/{kind}"
            payload = {"name": label, "unique_id": f"mbus_t230_{key}_{kind}",
                       "device": {"identifiers": [f"mbus_t230_{key}"]},
                       "state_topic": root + "/state", "json_attributes_topic": root + "/attributes",
                       "entity_category": "diagnostic",
                       "availability": [{"topic": availability_topic(key)}, {"topic": BRIDGE_AVAILABILITY}],
                       "availability_mode": "all"}
            # Meter-local wall time has no proven UTC offset. Publish text.
            value = errors.get("last_occurrence_local", {}).get(code)
            for target, data in (
                    (f"homeassistant/sensor/mbus_t230_{key}_{kind}/config", json.dumps(payload)),
                    (root + "/attributes", json.dumps({"code": code, "read_at_utc": errors["read_at_utc"],
                        "time_basis": "meter_local_unspecified", "active_faults": "not_inferred"})),
                    (root + "/state", value or "unknown")):
                result = client.publish(target, data, qos=1, retain=True)
                if result.rc:
                    raise ConnectionError("MQTT error event publish failed")
                result.wait_for_publish(timeout=5)
        for topic in obsolete_error_topics(key):
            result = client.publish(topic, "", qos=1, retain=True)
            if result.rc:
                raise ConnectionError("MQTT obsolete error history cleanup failed")
            result.wait_for_publish(timeout=5)
    setting = snapshot.get("monthly_set_day")
    if isinstance(setting, dict) and all(type(setting.get(k)) is int for k in ("day", "hour", "minute")):
        kind = "monthly_storage_time"
        topic = f"mbus/t230/{key}/{kind}/state"
        payload = {"name": "Monthly storage time", "unique_id": f"mbus_t230_{key}_{kind}",
                   "device": {"identifiers": [f"mbus_t230_{key}"]}, "state_topic": topic,
                   "entity_category": "diagnostic", "availability": [{"topic": availability_topic(key)}, {"topic": BRIDGE_AVAILABILITY}], "availability_mode": "all"}
        for target, value, retain in ((f"homeassistant/sensor/mbus_t230_{key}_{kind}/config", json.dumps(payload), True),
                                      (topic, f"Day {setting['day']}, {setting['hour']:02d}:{setting['minute']:02d}", True)):
            result = client.publish(target, value, qos=1, retain=retain)
            if result.rc:
                raise ConnectionError("MQTT configuration publish failed")
            result.wait_for_publish(timeout=5)
    for index in range(1, 25):
        value = by_stand[index]["cumulative_kwh"]
        if type(value) not in (int, float) or value < 0:
            raise ValueError("invalid historical stand")
        stand = by_stand[index]
        attributes = {"history_captured_at_utc": capture,
                      "meter_date_status": stand.get("date_source", "unverified"),
                      "archive_position": index,
                      "rollover_evidence": snapshot.get("rollover_evidence", "not_observed")}
        attributes["meter_storage_date"] = stand.get("meter_date") or stand.get("estimated_date")
        attributes["read_at_utc"] = stand.get("read_at_utc", snapshot.get("date_provenance", {}).get("history_read_at_utc"))
        if stand.get("date_source") in ("estimated_first_of_month", "derived_monthly_set_day") and stand.get("estimated_date"):
            attributes["estimated_date"] = stand["estimated_date"]
            attributes["date_assumption"] = "first_of_month"
        if stand.get("date_source") == "meter_verified" and stand.get("meter_date"):
            attributes["meter_date"] = stand["meter_date"]
        attributes.update(archive_attributes(stand))
        result = client.publish(f"mbus/t230/{key}/history_stand_{index}/attributes",
                                json.dumps(attributes), qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT history attributes publish failed")
        result.wait_for_publish(timeout=5)
        result = client.publish(f"mbus/t230/{key}/history_stand_{index}/state",
                                str(value), qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT history state publish failed")
        result.wait_for_publish(timeout=5)
    for index in range(1, 24):
        value = by_period[index]["period_kwh"]
        if type(value) not in (int, float) or value < 0:
            raise ValueError("invalid historical period")
        period = by_period[index]
        attributes = period_archive_attributes(period, by_stand[index], by_stand[index+1])
        attributes.update(newer_archive_position=index, older_archive_position=index+1)
        if attributes["history_captured_at_utc"] is None:
            attributes["history_captured_at_utc"] = snapshot.get("date_provenance", {}).get("history_read_at_utc") or capture
        result = client.publish(f"mbus/t230/{key}/history_period_{index}/attributes",
                                json.dumps(attributes), qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT history attributes publish failed")
        result.wait_for_publish(timeout=5)
        result = client.publish(f"mbus/t230/{key}/history_period_{index}/state",
                                str(value), qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT history state publish failed")
        result.wait_for_publish(timeout=5)


def publish_reading(client, decoded, meter_id, read_at_utc=None, clock_attributes=None):
    """Return selected values; availability goes online only after state messages."""
    values = select_measurements(decoded, meter_id)
    key = device_key(meter_id)
    if read_at_utc is None:
        read_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    # A wall clock without an offset is text, never a HA timestamp. Require an
    # unambiguous current record; a malformed clock does not block energy reads.
    clocks = [record for record in decoded.get("records", [])
              if record.get("kind") == "meter_local_time" and record.get("current_record")]
    clock = clocks[0] if len(clocks) == 1 else None
    clock_value = clock.get("value", "unknown") if clock else "unknown"
    summer_time = ("summer" if clock["summer_time"] else "standard") if clock and isinstance(clock.get("summer_time"), bool) else "unknown"
    for topic, payload, retain in discovery_messages(meter_id):
        result = client.publish(topic, payload, qos=1, retain=retain)
        if result.rc:
            raise ConnectionError("MQTT discovery publish failed")
        result.wait_for_publish(timeout=5)
    # Invalidate each missing or rejected metric independently so a stale
    # value cannot appear current while other valid measurements stay online.
    states = {kind: values.get(kind, "unknown") for kind in SENSORS}
    for kind, value in states.items():
        result = client.publish(f"mbus/t230/{key}/{kind}/state", str(value),
                                qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT state publish failed")
        result.wait_for_publish(timeout=5)
    for kind, value in (("meter_status", f"0x{decoded['status']:02X}"),
                        ("data_quality", "Delvis" if REQUIRED_SENSORS - values.keys() else
                         "Advarsel" if decoded["status"] == 0x10 else "OK"),
                        ("meter_local_time", clock_value),
                        ("meter_summer_time", summer_time),
                        ("last_successful_read_utc", read_at_utc)):
        result = client.publish(f"mbus/t230/{key}/{kind}/state", value,
                                qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT diagnostic publish failed")
        result.wait_for_publish(timeout=5)
    diagnostics = passive_diagnostics(decoded)
    maxima = project_maxima(decoded)
    maxima["flow"].update({name: diagnostics[name] for name in
                           ("flow_measurement_interval_seconds", "flow_averaging_interval_seconds")})
    for kind, attrs in maxima.items():
        attrs["maximum_unit"] = HA_UNITS[attrs.pop("unit")]
        attrs["maximum_time_basis"] = "meter_local_unspecified"
        attrs["maximum_read_at_utc"] = read_at_utc if attrs["maximum"] is not None else None
        attrs["previous_annual_maximum_read_at_utc"] = read_at_utc if attrs["previous_annual_maximum"] is not None else None
        result = client.publish(f"mbus/t230/{key}/{kind}/attributes",
                                json.dumps(attrs), qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT maximum attributes publish failed")
        result.wait_for_publish(timeout=5)
    for suffix, payload in (
            ("meter_status/attributes", json.dumps({
                "extension_byte": diagnostics["extension_byte"], "read_at_utc": read_at_utc})),
            ("firmware_version/state", diagnostics["firmware_version"] or "unknown")):
        result = client.publish(f"mbus/t230/{key}/{suffix}", payload, qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT meter diagnostic publish failed")
        result.wait_for_publish(timeout=5)
    if clock_attributes is not None:
        result = client.publish(f"mbus/t230/{key}/meter_local_time/attributes",
                                json.dumps(clock_attributes), qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT clock attributes publish failed")
        result.wait_for_publish(timeout=5)
    result = client.publish(availability_topic(key), "online", qos=1, retain=True)
    if result.rc:
        raise ConnectionError("MQTT availability publish failed")
    result.wait_for_publish(timeout=5)
    return values


def mark_unavailable(client, meter_id):
    return client.publish(availability_topic(device_key(meter_id)),
                          "offline", qos=1, retain=True)


def obsolete_error_topics(key):
    return (f"homeassistant/sensor/mbus_t230_{key}_meter_error_history/config",
            f"mbus/t230/{key}/meter_error_history/state",
            f"mbus/t230/{key}/meter_error_history/attributes")


def cleanup_discovery(client, meter_id):
    """Remove retained discovery on explicit uninstall or identity change."""
    mark_unavailable(client, meter_id).wait_for_publish(timeout=5)
    key = device_key(meter_id)
    history_cleanup = [(topic, "", True) for topic in obsolete_error_topics(key)]
    for _, kind, _ in ERROR_EVENTS:
        history_cleanup.extend((topic, "", True) for topic in (
            f"homeassistant/sensor/mbus_t230_{key}_{kind}/config",
            f"mbus/t230/{key}/{kind}/state",
            f"mbus/t230/{key}/{kind}/attributes"))
    for topic, _, _ in list(discovery_messages(meter_id)) + list(history_discovery_messages(meter_id)) + history_cleanup:
        result = client.publish(topic, "", qos=1, retain=True)
        if result.rc:
            raise ConnectionError("MQTT discovery cleanup failed")
        result.wait_for_publish(timeout=5)
