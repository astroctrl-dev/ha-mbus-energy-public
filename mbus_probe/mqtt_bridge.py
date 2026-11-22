"""MQTT Discovery adapter for validated, current T230 readings.

MQTT client is injected so message generation can be tested without a broker.
The caller must set a broker Last Will of 'offline' on availability_topic.
"""
import hashlib
import json

from ha_measurements import SENSORS, select_measurements

HA_UNITS = {"kWh": "kWh", "m3": "m³", "kW": "kW", "m3/h": "m³/h",
            "C": "°C", "K": "K"}
BRIDGE_AVAILABILITY = "mbus/t230/bridge/availability"


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
        if device_class:
            payload["device_class"] = device_class
        messages.append((topic, json.dumps(payload), True))
    for kind, label in (("meter_status", "M-Bus status"),
                        ("data_quality", "Datakvalitet")):
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
        messages.append((topic, json.dumps(payload), True))
    return messages


def publish_reading(client, decoded, meter_id):
    """Return selected values; availability goes online only after state messages."""
    values = select_measurements(decoded, meter_id)
    key = device_key(meter_id)
    for topic, payload, retain in discovery_messages(meter_id):
        result = client.publish(topic, payload, qos=1, retain=retain)
        if result.rc:
            raise ConnectionError("MQTT discovery publish failed")
        result.wait_for_publish(timeout=5)
    for kind, value in values.items():
        result = client.publish(f"mbus/t230/{key}/{kind}/state", str(value),
                                qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT state publish failed")
        result.wait_for_publish(timeout=5)
    for kind, value in (("meter_status", f"0x{decoded['status']:02X}"),
                        ("data_quality", "Advarsel" if decoded["status"] == 0x10 else "OK")):
        result = client.publish(f"mbus/t230/{key}/{kind}/state", value,
                                qos=1, retain=False)
        if result.rc:
            raise ConnectionError("MQTT diagnostic publish failed")
        result.wait_for_publish(timeout=5)
    result = client.publish(availability_topic(key), "online", qos=1, retain=True)
    if result.rc:
        raise ConnectionError("MQTT availability publish failed")
    result.wait_for_publish(timeout=5)
    return values


def mark_unavailable(client, meter_id):
    return client.publish(availability_topic(device_key(meter_id)),
                          "offline", qos=1, retain=True)


def cleanup_discovery(client, meter_id):
    """Remove retained discovery on explicit uninstall or identity change."""
    mark_unavailable(client, meter_id).wait_for_publish(timeout=5)
    for topic, _, _ in discovery_messages(meter_id):
        result = client.publish(topic, "", qos=1, retain=True)
        if result.rc:
            raise ConnectionError("MQTT discovery cleanup failed")
        result.wait_for_publish(timeout=5)
