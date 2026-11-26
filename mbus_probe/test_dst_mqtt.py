import json
import unittest
from mqtt_bridge import discovery_messages, publish_dst_diagnostics, cleanup_discovery


class Receipt:
    rc = 0
    def wait_for_publish(self, timeout=None):
        pass


class Client:
    def __init__(self):
        self.messages = []
    def publish(self, topic, payload, qos=0, retain=False):
        self.messages.append((topic, payload, retain))
        return Receipt()


class DSTMQTTTests(unittest.TestCase):
    def test_discovery_and_cleanup(self):
        meter = "12345678"
        messages = [(topic, json.loads(payload)) for topic, payload, _ in discovery_messages(meter)
                    if "/binary_sensor/" in topic and "dst_" in topic]
        self.assertEqual(len(messages), 2)
        for topic, payload in messages:
            self.assertEqual(payload["entity_category"], "diagnostic")
            self.assertNotIn(meter, topic)
        client = Client()
        cleanup_discovery(client, meter)
        for topic, _ in messages:
            self.assertIn((topic, "", True), client.messages)

    def test_states_are_distinct(self):
        client = Client()
        publish_dst_diagnostics(client, "12345678", {
            "dst_transition_failed": True, "dst_clock_override": None})
        states = {topic.split("/")[-2]: value for topic, value, retain in client.messages
                  if topic.endswith("/state")}
        self.assertEqual(states, {"dst_transition_failed": "ON", "dst_clock_override": "None"})
        client = Client()
        publish_dst_diagnostics(client, "12345678", {
            "dst_transition_failed": False, "dst_clock_override": True})
        states = {topic.split("/")[-2]: value for topic, value, retain in client.messages
                  if topic.endswith("/state")}
        self.assertEqual(states, {"dst_transition_failed": "OFF", "dst_clock_override": "ON"})
