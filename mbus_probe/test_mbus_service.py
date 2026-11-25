import unittest
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from mbus_probe import validate
from mbus_service import STOP, RequestPacer, on_broker_connect, poll_once, run
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
    def setUp(self):
        # Capture persistence is tested separately without writing to HAOS /data.
        capture = patch("mbus_service.append_sample")
        capture.start()
        self.addCleanup(capture.stop)
        sample = patch("mbus_service.make_sample", return_value={"alias": "Meter-test", "records": []})
        sample.start()
        self.addCleanup(sample.stop)

    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).with_name("fixture_t230_sanitized.hex")
        cls.decoded = validate(bytes.fromhex(fixture.read_text()))

    def test_restart_waits_for_prior_bus_request(self):
        class Waiter:
            def __init__(self):
                self.delays = []
            def wait(self, seconds):
                self.delays.append(seconds)
                return False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "last_bus_request"
            clock = [1000.0]
            first = Waiter()
            self.assertTrue(RequestPacer(path, clock=lambda: clock[0]).before_request(first))
            self.assertEqual(first.delays, [61.0])
            self.assertEqual(float(path.read_text()), 1000.0)
            clock[0] = 1009.0
            after_restart = Waiter()
            self.assertTrue(RequestPacer(path, clock=lambda: clock[0]).before_request(after_restart))
            self.assertEqual(after_restart.delays, [52.0])
            clock[0] = 1080.0
            next_cycle = Waiter()
            self.assertTrue(RequestPacer(path, clock=lambda: clock[0]).before_request(next_cycle))
            self.assertEqual(next_cycle.delays, [0.0])

    def test_valid_poll(self):
        client = FakeClient()
        with patch("mbus_service.read_one", return_value=(b"", b"frame")), \
             patch("mbus_service.validate", return_value=self.decoded):
            values = poll_once({"meter_id": "00000000", "address": 0}, client)
        self.assertEqual(values["energy"], 12345)
        # 17 discovery configs, 15 regular states, clock attributes, availability, 4 DST messages
        self.assertEqual(len(client.messages), 39)
        states = {topic.rsplit("/", 2)[-2]: payload for topic, payload, _, _
                  in client.messages if topic.endswith("/state")}
        self.assertRegex(states["last_successful_read_utc"],
                         r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
        self.assertIn(("mbus/t230/" + __import__("mqtt_bridge").device_key("00000000") + "/availability", "online", 1, True), client.messages)

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

    def test_analysis_save_error_warns_once_without_blocking_mqtt(self):
        client = FakeClient()
        with patch("mbus_service._ANALYSIS_SAVE_ERROR_LOGGED", False), \
             patch("mbus_service.read_one", return_value=(b"", b"frame")), \
             patch("mbus_service.validate", return_value=self.decoded), \
             patch("mbus_service.append_sample", side_effect=OSError("disk unavailable")), \
             patch("mbus_service.LOG.warning") as warning:
            poll_once({"meter_id": "00000000", "address": 0}, client)
            poll_once({"meter_id": "00000000", "address": 0}, client)
            warning.assert_called_once()
            self.assertEqual(sum(payload == "online" for _, payload, _, _ in client.messages), 2)

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

    def test_startup_clock_waits_for_first_fresh_measurement(self):
        initial_read = threading.Event()
        checked = []
        class ObservedClient(FakeClient):
            def publish(self, topic, payload, qos, retain):
                self_outer.assertFalse(initial_read.is_set()) if payload == "online" else None
                return super().publish(topic, payload, qos, retain)
        self_outer = self
        client = ObservedClient()
        class StopAfterTwo:
            calls = 0
            def is_set(self):
                return self.calls >= 2
            def wait(self, _seconds):
                self.calls += 1
                if self.calls == 1:
                    self_outer.assertFalse(initial_read.is_set())
                else:
                    self_outer.assertTrue(initial_read.is_set())
        def on_valid_round(meter_ids):
            checked.append(meter_ids)
            initial_read.set()
        with patch("mbus_service.STOP", StopAfterTwo()), \
             patch("mbus_service.read_one", side_effect=[OSError("timeout"), (b"", b"frame")]), \
             patch("mbus_service.validate", return_value=self.decoded):
            run({"meter_id": "00000000", "address": 0, "interval_seconds": 120},
                client, on_valid_round=on_valid_round)
        self.assertTrue(initial_read.is_set())
        self.assertEqual(checked, [["00000000"]])
        self.assertTrue(any(topic.endswith("/availability") and payload == "online"
                            for topic, payload, _, _ in client.messages))

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

    def test_unverified_restore_keeps_ui_alive_and_never_polls(self):
        class StopAfterOne:
            calls = 0
            def is_set(self):
                return self.calls > 0
            def wait(self, _seconds):
                self.calls += 1
        blocked = threading.Event()
        blocked.set()
        client = FakeClient()
        with patch("mbus_service.STOP", StopAfterOne()), \
             patch("mbus_service.read_one") as reader:
            run({"meter_id": "00000000", "address": 0}, client,
                history_controller=SimpleNamespace(blocked=blocked, recover_normal=lambda: False))
        reader.assert_not_called()
        self.assertIn(("mbus/t230/bridge/availability", "offline", 1, True), client.messages)

    def test_broker_reconnect_invalidates_all_meter_states(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = MeterRegistry(Path(directory) / "meters.json")
            registry.set_found([{"meter_id": "00000000", "address": 0, "supported": True},
                                {"meter_id": "12345678", "address": 1, "supported": True}])
            registry.select("00000000")
            registry.select("12345678")
            client = FakeClient()
            with patch("mbus_service.publish_history") as history:
                on_broker_connect(client, registry)
                history.assert_not_called()  # No QoS waits on Paho callback thread.
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
