"""Regression: history entities exist before the first history capture."""
import unittest
from unittest.mock import patch
from mbus_service import publish_saved_history
from mqtt_bridge import history_discovery_messages


class PublishResult:
    rc = 0

    def wait_for_publish(self, timeout=None):
        return True

    def is_published(self):
        return True


class Client:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.messages.append((topic, payload, qos, retain))
        return PublishResult()


class Registry:
    def snapshot(self):
        return {"selected": [{"meter_id": "12345678", "address": 1}]}


class HistoryDiscoveryTests(unittest.TestCase):
    @patch("mbus_service.load_history", return_value=[])
    def test_discovery_without_saved_history(self, _load):
        client = Client()
        publish_saved_history(client, Registry())
        expected = list(history_discovery_messages("12345678"))
        self.assertEqual(len(client.messages), 47)
        self.assertEqual({topic for topic, _, _, _ in client.messages},
                         {topic for topic, _, _ in expected})
        self.assertTrue(all(qos == 1 and retain
                            for _, _, qos, retain in client.messages))

    @patch("mbus_service.LOG.warning")
    @patch("mbus_service.load_history", return_value=[])
    def test_missing_puback_is_reported(self, _load, warning):
        class TimeoutClient(Client):
            def publish(self, topic, payload, qos=0, retain=False):
                result = super().publish(topic, payload, qos, retain)
                result.is_published = lambda: False
                return result

        client = TimeoutClient()
        publish_saved_history(client, Registry())
        self.assertEqual(len(client.messages), 1)
        warning.assert_called_once()
        self.assertIn("publish failed", warning.call_args.args[0])

    @patch("mbus_service.load_history", return_value=[])
    def test_discovery_is_idempotent(self, _load):
        client = Client()
        publish_saved_history(client, Registry())
        publish_saved_history(client, Registry())
        self.assertEqual(len(client.messages), 94)
        self.assertEqual([m[0] for m in client.messages[:47]],
                         [m[0] for m in client.messages[47:]])


if __name__ == "__main__":
    unittest.main()
