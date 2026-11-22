import json
from pathlib import Path
import unittest

from mbus_probe import validate
from mqtt_bridge import (availability_topic, cleanup_discovery, device_key, discovery_messages,
                         mark_unavailable, publish_reading)


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
        self.assertEqual(len(first), 9)
        self.assertEqual(len({json.loads(p)["unique_id"] for _, p, _ in first}), 9)
        by_kind = {json.loads(p)["name"]: json.loads(p) for _, p, _ in first}
        self.assertEqual(len(by_kind["Energy"]["availability"]), 2)
        self.assertEqual(by_kind["Energy"]["availability_mode"], "all")
        self.assertEqual(by_kind["Flow"]["device_class"], "volume_flow_rate")
        self.assertEqual(by_kind["Flow"]["unit_of_measurement"], "m³/h")
        self.assertEqual(by_kind["Energy"]["state_class"], "total_increasing")
        self.assertEqual(by_kind["Flow Temperature"]["unit_of_measurement"], "°C")

    def test_valid_read_online_after_states(self):
        client = FakeClient()
        values = publish_reading(client, self.decoded, "00000000")
        self.assertEqual(values["energy"], 12345)
        self.assertEqual(len(client.messages), 19)
        self.assertEqual(client.messages[-1],
                         (availability_topic(device_key("00000000")), "online", 1, True))
        self.assertFalse(any("wrong_installation" in t for t, _, _, _ in client.messages))
        self.assertTrue(all(not r for t, _, _, r in client.messages if t.endswith("/state")))

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

    def test_explicit_cleanup_clears_retained_discovery(self):
        client = FakeClient()
        cleanup_discovery(client, "00000000")
        self.assertEqual(len(client.messages), 10)
        self.assertTrue(all(payload == "" and retain
                            for _, payload, _, retain in client.messages[1:]))
