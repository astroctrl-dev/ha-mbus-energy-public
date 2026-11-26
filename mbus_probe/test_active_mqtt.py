import json
import unittest
from datetime import datetime, timezone
from mqtt_bridge import discovery_messages, publish_active_diagnostics
from test_mqtt_bridge import FakeClient


class ActiveMQTTTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)

    def publish(self, raw=None, stamp=None, verified=False):
        publish_active_diagnostics(self.client, "00000000", raw, stamp,
                                   layout_verified=verified, now=self.now)
        return {topic.rsplit("/", 2)[-2] + "/" + topic.rsplit("/", 1)[-1]: payload
                for topic, payload, _, _ in self.client.messages}

    def test_discovery(self):
        configs = {json.loads(p)["name"]: (topic, json.loads(p))
                   for topic, p, _ in discovery_messages("00000000")}
        for label in ("Active Meter Faults", "Flow Warning"):
            topic, config = configs[label]
            self.assertIn("/binary_sensor/", topic)
            self.assertEqual(config["device_class"], "problem")
        topic, config = configs["Battery Status"]
        self.assertIn("/sensor/", topic)
        self.assertNotIn("unit_of_measurement", config)

    def test_unknown_without_verified_layout(self):
        for raw, stamp, verified in ((None,None,False), (bytes(3),self.now.isoformat(),False),
                                     (bytes(3),"2026-11-24T12:00:00Z",True),
                                     (bytes(3),"2026-11-27T12:00:00Z",True),
                                     (bytes(2),self.now.isoformat(),True)):
            p = self.publish(raw, stamp, verified)
            self.assertEqual(p["active_meter_faults/state"], "None")
            self.assertEqual(p["flow_warning/state"], "None")
            self.assertEqual(p["battery_status/state"], "unknown")

    def test_verified_sample_and_precedence(self):
        p = self.publish(bytes.fromhex("02 02 11"), self.now.isoformat(), True)
        self.assertEqual(p["active_meter_faults/state"], "ON")
        self.assertEqual(p["flow_warning/state"], "ON")
        self.assertEqual(p["battery_status/state"], "exhausted")
        self.assertIn("F9 - Internal communication error",
                      json.loads(p["active_meter_faults/attributes"])["fault_messages"])
        self.assertTrue(all(not retained for _, _, _, retained in self.client.messages))

    def test_normal(self):
        p = self.publish(bytes(3), self.now.isoformat(), True)
        self.assertEqual(p["active_meter_faults/state"], "OFF")
        self.assertEqual(p["flow_warning/state"], "OFF")
        self.assertEqual(p["battery_status/state"], "normal")
