import json
from pathlib import Path
import unittest

from mbus_probe import validate
from mqtt_bridge import (availability_topic, cleanup_discovery, device_key, discovery_messages,
                         mark_unavailable, publish_reading, publish_history, history_discovery_messages)


class FakeResult:
    rc = 0
    def wait_for_publish(self, timeout=None):
        return None


class FakeClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos, retain):
        self.messages.append((topic, payload, qos, retain))
        return FakeResult()


class MqttTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).with_name("fixture_t230_sanitized.hex")
        cls.decoded = validate(bytes.fromhex(fixture.read_text()))

    def test_stable_discovery_and_units(self):
        first = discovery_messages("00000000")
        self.assertEqual(first, discovery_messages("00000000"))
        self.assertEqual(len(first), 17)
        self.assertEqual(len({json.loads(p)["unique_id"] for _, p, _ in first}), 17)
        by_kind = {json.loads(p)["name"]: json.loads(p) for _, p, _ in first}
        self.assertEqual(len(by_kind["Energy"]["availability"]), 2)
        self.assertEqual(by_kind["Energy"]["availability_mode"], "all")
        self.assertEqual(by_kind["Flow"]["device_class"], "volume_flow_rate")
        self.assertEqual(by_kind["Flow"]["unit_of_measurement"], "m³/h")
        self.assertEqual(by_kind["Energy"]["state_class"], "total_increasing")
        self.assertEqual(by_kind["Flow Temperature"]["unit_of_measurement"], "°C")
        self.assertEqual(by_kind["Flow Time"]["unit_of_measurement"], "h")
        self.assertNotIn("device_class", by_kind["Målerklokke (lokal tid)"])
        self.assertEqual(by_kind["Siste avlesning (UTC)"]["device_class"], "timestamp")

    def test_temperature_native_units_and_delta_class(self):
        configs = {json.loads(p)["unique_id"].removeprefix(
            "mbus_t230_" + device_key("00000000") + "_"): json.loads(p)
            for _, p, _ in discovery_messages("00000000")}
        for kind in ("flow_temperature", "return_temperature"):
            self.assertEqual(configs[kind]["device_class"], "temperature")
            self.assertEqual(configs[kind]["unit_of_measurement"], "°C")
        delta = configs["temperature_difference"]
        self.assertEqual(delta["device_class"], "temperature_delta")
        self.assertEqual(delta["unit_of_measurement"], "K")
        self.assertEqual(delta["state_class"], "measurement")
        client = FakeClient()
        values = publish_reading(client, self.decoded, "00000000")
        states = {t.rsplit("/", 2)[-2]: p for t, p, _, _ in client.messages
                  if t.endswith("/state")}
        for kind in ("flow_temperature", "return_temperature", "temperature_difference"):
            self.assertEqual(float(states[kind]), values[kind])

    def test_valid_read_online_after_states(self):
        client = FakeClient()
        values = publish_reading(client, self.decoded, "00000000")
        self.assertEqual(values["energy"], 12345)
        self.assertEqual(len(client.messages), 34)
        self.assertEqual(client.messages[-1],
                         (availability_topic(device_key("00000000")), "online", 1, True))
        self.assertFalse(any("wrong_installation" in t for t, _, _, _ in client.messages))
        self.assertTrue(all(not r for t, _, _, r in client.messages if t.endswith("/state")))

    def test_clock_uses_unzoned_text_and_separate_utc_read(self):
        client = FakeClient()
        publish_reading(client, self.decoded, "00000000",
                        read_at_utc="2026-11-23T14:35:00Z")
        states = {topic.rsplit("/", 2)[-2]: payload for topic, payload, _, _
                  in client.messages if topic.endswith("/state")}
        clock = [r for r in self.decoded["records"]
                 if r.get("kind") == "meter_local_time" and r.get("current_record")]
        self.assertEqual(len(clock), 1)
        self.assertEqual(states["meter_local_time"], clock[0]["value"])
        self.assertNotIn("Z", states["meter_local_time"])
        self.assertEqual(states["last_successful_read_utc"], "2026-11-23T14:35:00Z")
        self.assertEqual(states["meter_summer_time"],
                         "summer" if clock[0]["summer_time"] else "standard")

    def test_optional_counter_disappearing_does_not_leave_stale_ha_value(self):
        client = FakeClient()
        publish_reading(client, self.decoded, "00000000")
        reduced = {**self.decoded, "records": [r for r in self.decoded["records"]
                   if r.get("kind") not in ("operating_time", "flow_time", "missing_time")]}
        client.messages.clear()
        values = publish_reading(client, reduced, "00000000")
        self.assertNotIn("flow_time", values)
        states = {topic.rsplit("/", 2)[-2]: payload for topic, payload, _, _
                  in client.messages if topic.endswith("/state")}
        for kind in ("operating_time", "flow_time", "missing_time"):
            self.assertEqual(states[kind], "unknown")
        self.assertEqual(states["energy"], "12345.0")
        self.assertEqual(client.messages[-1][1], "online")

    def test_invalid_energy_does_not_hide_signed_power_and_clears_stale_energy(self):
        client = FakeClient()
        base = self.decoded["records"]
        modified = [
            {**r, "value": -10} if r.get("kind") == "energy" and r.get("current_record")
            else {**r, "value": -999999} if r.get("kind") == "power" and r.get("current_record")
            else r for r in base
        ]
        values = publish_reading(client, {**self.decoded, "records": modified}, "00000000")
        states = {topic.rsplit("/", 2)[-2]: payload for topic, payload, _, _
                  in client.messages if topic.endswith("/state")}
        self.assertNotIn("energy", values)
        self.assertEqual(states["energy"], "unknown")
        self.assertEqual(states["power"], "-999999")
        self.assertEqual(states["data_quality"], "Delvis")
        self.assertEqual(states["volume"], "123.45")
        self.assertEqual(client.messages[-1][1], "online")

    def test_invalid_clock_does_not_block_measurements(self):
        client = FakeClient()
        invalid = {**self.decoded, "records": [
            {**record, "kind": "invalid_meter_time"}
            if record.get("kind") == "meter_local_time" else record
            for record in self.decoded["records"]]}
        values = publish_reading(client, invalid, "00000000",
                                 read_at_utc="2026-11-23T14:35:00Z")
        states = {topic.rsplit("/", 2)[-2]: payload for topic, payload, _, _
                  in client.messages if topic.endswith("/state")}
        self.assertEqual(values["energy"], 12345)
        self.assertEqual(states["meter_local_time"], "unknown")
        self.assertEqual(states["meter_summer_time"], "unknown")
        self.assertEqual(states["last_successful_read_utc"], "2026-11-23T14:35:00Z")
        self.assertEqual(client.messages[-1][1], "online")

    def test_temporary_error_keeps_values_online_with_warning(self):
        client = FakeClient()
        publish_reading(client, {**self.decoded, "status": 0x10}, "00000000")
        states = {topic.rsplit("/", 2)[-2]: payload for topic, payload, _, _
                  in client.messages if topic.endswith("/state")}
        self.assertEqual(states["meter_status"], "0x10")
        self.assertEqual(states["data_quality"], "Advarsel")
        self.assertEqual(states["energy"], "12345.0")
        self.assertEqual(client.messages[-1][1], "online")

    def test_bad_status_does_not_publish(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            publish_reading(client, {**self.decoded, "status": 1}, "00000000")
        self.assertEqual(client.messages, [])
        mark_unavailable(client, "00000000")
        self.assertEqual(client.messages[-1][-3:], ("offline", 1, True))

    def test_historical_values_are_diagnostic_positions_not_energy_counters(self):
        from history_model import build_snapshot
        months = [{"month_back":n, "value":1000 - 10*n, "unit":"kWh"}
                  for n in range(1, 25)]
        snapshot = build_snapshot(months, "2026-11-23T03:00:00Z")
        client = FakeClient()
        publish_history(client, "12345678", snapshot)
        configs = [json.loads(payload) for topic, payload, _, _ in client.messages
                   if topic.endswith("/config")]
        self.assertEqual(len(configs), 47)
        self.assertEqual([config["name"] for config in configs[:2]],
                         ["Historisk målerstand −01", "Historisk målerstand −02"])
        self.assertEqual(configs[9]["name"], "Historisk målerstand −10")
        self.assertEqual(configs[23]["name"], "Historisk målerstand −24")
        self.assertEqual(configs[24]["name"], "Forbruk mellom −02 og −01")
        self.assertEqual(configs[24]["unique_id"].split("_")[-1], "1")
        self.assertRegex(configs[0]["default_entity_id"],
                         r"^sensor\.mbus_t230_[0-9a-f]{16}_historisk_malerstand_01$")
        self.assertTrue(configs[8]["default_entity_id"].endswith("_09"))
        self.assertTrue(configs[9]["default_entity_id"].endswith("_10"))
        self.assertTrue(configs[23]["default_entity_id"].endswith("_24"))
        self.assertTrue(configs[24]["default_entity_id"].endswith("_01"))
        self.assertTrue(configs[-1]["default_entity_id"].endswith("_23"))
        other = json.loads(next(history_discovery_messages("87654321"))[1])
        self.assertNotEqual(configs[0]["default_entity_id"], other["default_entity_id"])
        self.assertEqual(len([m for m in client.messages if m[0].endswith("/state")]), 47)
        attribute_messages = [m for m in client.messages if m[0].endswith("/attributes")]
        self.assertEqual(len(attribute_messages), 47)
        self.assertTrue(all("json_attributes_topic" in config for config in configs))
        stands = [json.loads(payload) for topic, payload, _, _ in attribute_messages
                  if "/history_stand_" in topic]
        periods = [json.loads(payload) for topic, payload, _, _ in attribute_messages
                   if "/history_period_" in topic]
        self.assertEqual(stands[0]["history_captured_at_utc"], "2026-11-23T03:00:00+00:00")
        self.assertEqual(stands[0]["archive_position"], 1)
        self.assertEqual(periods[0]["newer_archive_position"], 1)
        self.assertEqual(periods[0]["older_archive_position"], 2)
        self.assertTrue(all(a["meter_date_status"] == "unverified" and "meter_date" not in a
                            for a in stands + periods))
        self.assertTrue(all("state_class" not in config and "device_class" not in config
                            for config in configs))
        self.assertTrue(all("12345678" not in topic + str(payload)
                            for topic, payload, _, _ in client.messages))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            publish_history(FakeClient(), "12345678", {"stands":[]})

    def test_explicit_cleanup_clears_retained_discovery(self):
        client = FakeClient()
        cleanup_discovery(client, "00000000")
        self.assertEqual(len(client.messages), 68)
        self.assertTrue(all(payload == "" and retain
                            for _, payload, _, retain in client.messages[1:]))


class PassiveDiagnosticsTests(unittest.TestCase):
    def test_timing_projection_and_unknown(self):
        from mbus_records import decode_records, passive_diagnostics
        records = decode_records(bytes.fromhex("09 74 04 09 70 08"))
        self.assertEqual(passive_diagnostics({"records": records}), {
            "flow_measurement_interval_seconds": 4,
            "flow_averaging_interval_seconds": 8, "firmware_version": None,
            "extension_byte": None})
        self.assertIsNone(passive_diagnostics({"records": records + records})[
            "flow_measurement_interval_seconds"])
        self.assertIsNone(passive_diagnostics({"records": decode_records(
            bytes.fromhex("09 74 ff"))})["flow_measurement_interval_seconds"])
        self.assertIsNone(passive_diagnostics({"records": []})[
            "flow_averaging_interval_seconds"])

    def test_mqtt_attributes_and_identity(self):
        from mbus_records import decode_records
        decoded = validate(bytes.fromhex(Path(__file__).with_name(
            "fixture_t230_sanitized.hex").read_text()))
        decoded["records"] = [r for r in decoded["records"]
                              if r.get("vif") not in (0x70, 0x74)]
        decoded["records"] += decode_records(bytes.fromhex("09 74 04 09 70 08"))
        client = FakeClient()
        publish_reading(client, decoded, "00000000")
        attrs = [json.loads(p) for t,p,_,_ in client.messages
                 if t.endswith("/meter_status/attributes")]
        self.assertEqual(attrs[0]["flow_measurement_interval_seconds"], 4)
        self.assertEqual(attrs[0]["flow_averaging_interval_seconds"], 8)
        config = [json.loads(p) for t,p,_ in discovery_messages("00000000")
                  if t.endswith("_meter_status/config")][0]
        self.assertEqual(config["json_attributes_topic"],
                         f"mbus/t230/{device_key('00000000')}/meter_status/attributes")


class FooterAndHistoryTests(unittest.TestCase):
    def test_firmware_and_frame_guard(self):
        from mbus_records import decode_records, passive_diagnostics, t230_footer
        decoded = {"records": decode_records(bytes.fromhex("0f 12 07 00 62 01"))}
        self.assertEqual(passive_diagnostics(decoded)["firmware_version"], "7.12")
        self.assertEqual(passive_diagnostics(decoded)["extension_byte"], "0x62")
        self.assertIsNone(t230_footer(decoded, 2))
        self.assertIsNone(t230_footer({"records": decode_records(
            bytes.fromhex("0f fa 07 00 62 01"))}, 1))

    def test_history_labels_and_invalid_dates(self):
        from mbus_records import decode_records, historical_errors
        decoded = {"records": decode_records(bytes.fromhex(
            "34 fc 6e 02 54 46 03 13 56 3b "
            "34 fc 6e 02 53 46 00 00 00 00 "
            "34 fc 6e 02 45 46 00 00 41 3b "
            "34 fc 6e 03 31 46 46 00 00 41 3b "
            "34 fc 6e 03 32 46 46 20 10 56 3b 0f 12 07 00 63 02"))}
        result = historical_errors(decoded)
        self.assertEqual(result["FT"], "2026-11-22T19:03")
        self.assertIsNone(result["FS"])
        self.assertEqual(result["FF2"], "2026-11-22T16:32")
        self.assertEqual(result["FE"], "2026-11-01T00:00")

class ErrorHistoryPublicationTests(unittest.TestCase):
    def test_saved_history_is_timestamp_not_active_alarm(self):
        from history_model import build_snapshot
        snap = build_snapshot([{"month_back":n,"value":1000-10*n,"unit":"kWh"}
                               for n in range(1,25)], "2026-11-23T03:00:00Z")
        snap["error_history"] = {"read_at_utc":"2026-11-25T10:00:00+00:00",
                                 "last_occurrence_local":{"FT":"2026-11-22T19:03"}}
        client = FakeClient()
        publish_history(client, "12345678", snap)
        attrs = next(json.loads(p) for t,p,_,_ in client.messages
                     if t.endswith("/meter_error_history/attributes"))
        self.assertEqual(attrs["last_occurrence_local"]["FT"], "2026-11-22T19:03")
        self.assertIsNone(attrs["last_occurrence_local"]["FS"])
        self.assertEqual(attrs["active_faults"], "not_inferred")
