import unittest
import tempfile
import threading
from unittest.mock import patch
from pathlib import Path

from mbus_probe import validate
from mbus_service import STOP, on_broker_connect, poll_once, run
from meter_registry import MeterRegistry


class FakeClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos, retain):
        self.messages.append((topic, payload, qos, retain))
        class Result:
            rc = 0
            def wait_for_publish(self, timeout=None):
                pass
        return Result()


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).with_name("fixture_t230_sanitized.hex")
        cls.decoded = validate(bytes.fromhex(fixture.read_text()))

    def test_valid_poll(self):
        client = FakeClient()
        with patch("mbus_service.read_one", return_value=(b"", b"frame")), \
             patch("mbus_service.validate", return_value=self.decoded):
            values = poll_once({"meter_id": "00000000", "address": 0}, client)
        self.assertEqual(values["energy"], 12345)
        # 9 Discovery configs + 7 measurements + 2 diagnostics + availability
        self.assertEqual(len(client.messages), 19)
        self.assertEqual(client.messages[-1][1], "online")

    def test_status_0x10_warns_only_once_per_process(self):
        client = FakeClient()
        warning = {**self.decoded, "status": 0x10}
        with patch("mbus_service._STATUS_10_LOGGED", False), \
             patch("mbus_service.read_one", return_value=(b"", b"frame")), \
             patch("mbus_service.validate", return_value=warning), \
             patch("mbus_service.LOG.warning") as log_warning:
            poll_once({"meter_id": "00000000", "address": 0}, client)
            poll_once({"meter_id": "00000000", "address": 0}, client)
            poll_once({"meter_id": "00000000", "address": 0}, client)
            log_warning.assert_called_once()
            self.assertIn("not conclusively", log_warning.call_args.args[0])
            self.assertIn("first occurrence", log_warning.call_args.args[0])
        self.assertEqual(sum(payload == "online" for _, payload, _, _ in client.messages), 3)

    def test_status_0x10_warning_reappears_on_new_process(self):
        client = FakeClient()
        warning = {**self.decoded, "status": 0x10}
        with patch("mbus_service.read_one", return_value=(b"", b"frame")), \
             patch("mbus_service.validate", return_value=warning), \
             patch("mbus_service.LOG.warning") as log_warning:
            with patch("mbus_service._STATUS_10_LOGGED", False):
                poll_once({"meter_id": "00000000", "address": 0}, client)
            with patch("mbus_service._STATUS_10_LOGGED", False):
                poll_once({"meter_id": "00000000", "address": 0}, client)
            self.assertEqual(log_warning.call_count, 2)

    def test_wrong_address_never_publishes(self):
        client = FakeClient()
        with patch("mbus_service.read_one", return_value=(b"", b"frame")), \
             patch("mbus_service.validate", return_value={**self.decoded, "address": 1}):
            with self.assertRaisesRegex(ValueError, "address mismatch"):
                poll_once({"meter_id": "00000000", "address": 0}, client)
        self.assertEqual(client.messages, [])

    def test_timeout_marks_offline_then_recovery_online(self):
        client = FakeClient()
        attempts = [OSError("timeout: no meter bytes received"),
                    (b"", b"frame")]
        def read_side_effect(*args, **kwargs):
            result = attempts.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        class StopAfterTwo:
            calls = 0
            def is_set(self):
                return self.calls >= 2
            def wait(self, seconds):
                self.calls += 1

        fake_stop = StopAfterTwo()
        with patch("mbus_service.STOP", fake_stop), \
             patch("mbus_service.read_one", side_effect=read_side_effect), \
             patch("mbus_service.validate", return_value=self.decoded):
            run({"meter_id": "00000000", "address": 0,
                 "interval_seconds": 10}, client)
        availability = [payload for topic, payload, _, _ in client.messages
                        if topic.endswith("/availability")]
        self.assertEqual(availability, ["offline", "online"])

    def test_two_selected_meters_poll_sequentially_with_distinct_topics(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = MeterRegistry(Path(directory) / "meters.json")
            registry.set_found([{"meter_id": "00000000", "address": 0, "supported": True},
                                {"meter_id": "12345678", "address": 1, "supported": True}])
            registry.select("00000000")
            registry.select("12345678")
            class StopAfterOne:
                calls = 0
                def is_set(self):
                    return self.calls > 0
                def wait(self, _seconds):
                    self.calls += 1
            client = FakeClient()
            decoded = [{**self.decoded, "address": address, "meter_id": meter_id}
                       for meter_id, address in (("00000000", 0), ("12345678", 1))]
            with patch("mbus_service.STOP", StopAfterOne()), \
                 patch("mbus_service.read_one", side_effect=[(b"", b"a"), (b"", b"b")]) as reader, \
                 patch("mbus_service.validate", side_effect=decoded):
                run({"serial_port": "/dev/ttyUSB0", "interval_seconds": 120},
                    client, registry, threading.Lock())
            self.assertEqual([call.args[2] for call in reader.call_args_list], [0, 1])
            online = [topic for topic, payload, _, _ in client.messages
                      if topic.endswith("/availability") and payload == "online"]
            self.assertEqual(len(online), 2)
            self.assertNotEqual(*online)

    def test_broker_reconnect_invalidates_all_meter_states(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = MeterRegistry(Path(directory) / "meters.json")
            registry.set_found([{"meter_id": "00000000", "address": 0, "supported": True},
                                {"meter_id": "12345678", "address": 1, "supported": True}])
            registry.select("00000000")
            registry.select("12345678")
            client = FakeClient()
            on_broker_connect(client, registry)
            self.assertEqual([payload for _, payload, _, _ in client.messages],
                             ["offline", "offline", "offline", "online"])
            self.assertEqual(len({topic for topic, payload, _, _ in client.messages
                                  if payload == "offline"}), 3)

    def test_pending_cleanup_is_serialized_and_rechecked(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = MeterRegistry(Path(directory) / "meters.json")
            registry.set_found([{"meter_id": "12345678", "address": 1, "supported": True}])
            registry.select("12345678")
            registry.remove("12345678")
            lock = threading.Lock()
            class StopAfterOne:
                calls = 0
                def is_set(self):
                    return self.calls > 0
                def wait(self, _seconds):
                    self.calls += 1
            def check_cleanup(_client, meter_id):
                self.assertTrue(lock.locked())
                self.assertIn(meter_id, registry.pending_cleanup)
            with patch("mbus_service.STOP", StopAfterOne()), \
                 patch("mbus_service.cleanup_discovery", side_effect=check_cleanup) as cleanup:
                run({"interval_seconds": 120}, FakeClient(), registry, lock)
            cleanup.assert_called_once()
            self.assertEqual(registry.pending_cleanup, [])
