import threading
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from clock_maintenance import ClockController, encode_type_f, set_clock_frame, sync_once


class FakeSerial:
    def __init__(self, *args, response=b"\xe5", **kwargs):
        self.response, self.sent = response, []
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def reset_input_buffer(self): pass
    def write(self, data): self.sent.append(data)
    def flush(self): pass
    def read(self, count): return self.response


class ClockMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneInfo("Europe/Oslo")
        self.now = datetime(2026, 11, 23, 4, 0, tzinfo=self.zone)

    def test_type_f_frame_and_checksum(self):
        field = encode_type_f(self.now)
        self.assertEqual(field, bytes((0, 4, 23 | ((26 & 7) << 5),
                                       11 | ((26 >> 3) << 4))))
        frame = set_clock_frame(7, self.now)
        self.assertEqual(frame[0:4], bytes((0x68, 9, 9, 0x68)))
        self.assertEqual(frame[4:9], bytes((0x53, 7, 0x51, 4, 0x6d)))
        self.assertEqual(frame[-2], sum(frame[4:-2]) & 255)
        self.assertEqual(frame[-1], 0x16)
        summer = datetime(2026, 6, 23, 4, 0, tzinfo=self.zone)
        self.assertEqual(encode_type_f(summer)[1] & 0x80, 0x80)

    @patch("clock_maintenance._read_clock")
    def test_manual_write_reads_back_and_never_accepts_ack_alone(self, read_clock):
        read_clock.side_effect = [
            {"meter_local_time": "2026-11-23T00:10", "meter_summer_time": False},
            {"meter_local_time": "2026-11-23T04:00", "meter_summer_time": False}]
        ser = FakeSerial()
        events = []
        result = sync_once("/dev/ttyUSB0", 2400, 7, "12345678", "Europe/Oslo",
                           serial_factory=lambda *a, **k: ser, sleep=lambda n: events.append(n),
                           now=lambda: self.now, on_write=lambda before, target: events.append((before, target)))
        self.assertTrue(result["changed"])
        self.assertEqual(result["before"], "2026-11-23T00:10")
        self.assertEqual(result["after"], "2026-11-23T04:00")
        self.assertEqual(events[0], 61)
        self.assertEqual(events[-1], 61)
        self.assertEqual(len(ser.sent), 1)

    @patch("clock_maintenance._read_clock")
    def test_auto_check_skips_write_when_already_in_sync(self, read_clock):
        read_clock.return_value = {"meter_local_time": "2026-11-23T03:59", "meter_summer_time": False}
        result = sync_once("/dev/ttyUSB0", 2400, 7, "12345678", "Europe/Oslo",
                           sleep=lambda n: self.fail("unexpected wait"),
                           serial_factory=lambda *a, **k: self.fail("unexpected write"),
                           now=lambda: self.now, auto=True)
        self.assertFalse(result["changed"])
        self.assertEqual(read_clock.call_count, 1)

    def test_auto_check_waits_for_valid_round_after_selection(self):
        class Registry:
            lock = threading.Lock()
            selected = {"12345678": 7}
        completed = threading.Event()
        calls = []
        def operation(*args, **kwargs):
            calls.append(kwargs["auto"])
            completed.set()
            return {"changed": False, "manual_required": False,
                    "before": "2026-11-23T04:00", "target": None,
                    "after": "2026-11-23T04:00"}
        with tempfile.TemporaryDirectory() as directory:
            controller = ClockController(
                Registry(), {"serial_port": "/dev/ttyUSB0", "allow_clock_sync": True,
                             "auto_clock_sync": True}, threading.Lock(), threading.Event(),
                operation=operation, pause=lambda _: None, root=directory)
            controller.defer_auto("12345678")
            controller.on_valid_round([])
            self.assertFalse(completed.is_set())
            controller.on_valid_round(["12345678"])
            self.assertTrue(completed.wait(2))
            controller.worker.join(2)
            controller.on_valid_round(["12345678"])
            self.assertEqual(calls, [True])

    def test_manual_clock_check_does_not_drop_pending_auto_check(self):
        class Registry:
            lock = threading.Lock()
            selected = {"12345678": 7, "00000000": 8}
        manual_started = threading.Event()
        release_manual = threading.Event()
        auto_completed = threading.Event()
        calls = []
        def operation(*args, **kwargs):
            calls.append(kwargs["auto"])
            if kwargs["auto"]:
                auto_completed.set()
            else:
                manual_started.set()
                self.assertTrue(release_manual.wait(2))
            return {"changed": False, "manual_required": False,
                    "before": "2026-11-23T04:00", "target": None,
                    "after": "2026-11-23T04:00"}
        with tempfile.TemporaryDirectory() as directory:
            controller = ClockController(
                Registry(), {"serial_port": "/dev/ttyUSB0", "allow_clock_sync": True,
                             "auto_clock_sync": True}, threading.Lock(), threading.Event(),
                operation=operation, pause=lambda _: None, root=directory)
            controller.start("12345678")
            self.assertTrue(manual_started.wait(2))
            controller.defer_auto("00000000")
            controller.on_valid_round(["00000000"])
            self.assertFalse(auto_completed.is_set())
            release_manual.set()
            self.assertTrue(auto_completed.wait(2))
            self.assertEqual(calls, [False, True])

    @patch("clock_maintenance._read_clock")
    def test_auto_requires_manual_seed_and_bounded_drift(self, read_clock):
        read_clock.return_value = {"meter_local_time": "2026-11-23T00:10", "meter_summer_time": False}
        for trusted in (False, True):
            result = sync_once("/dev/ttyUSB0", 2400, 7, "12345678", "Europe/Oslo",
                               sleep=lambda n: self.fail("unexpected wait"),
                               serial_factory=lambda *a, **k: self.fail("unexpected write"),
                               now=lambda: self.now, auto=True, allow_auto_write=trusted)
            self.assertTrue(result["manual_required"])
            self.assertFalse(result["changed"])

    @patch("clock_maintenance._read_clock")
    def test_no_ack_does_not_claim_success(self, read_clock):
        read_clock.return_value = {"meter_local_time": "2026-11-23T00:10", "meter_summer_time": False}
        with self.assertRaisesRegex(ValueError, "not acknowledged"):
            sync_once("/dev/ttyUSB0", 2400, 7, "12345678", "Europe/Oslo",
                      serial_factory=lambda *a, **k: FakeSerial(response=b""),
                      sleep=lambda n: None, now=lambda: self.now)

    @patch("clock_maintenance._read_clock")
    def test_wrong_readback_does_not_claim_success(self, read_clock):
        read_clock.side_effect = [
            {"meter_local_time": "2026-11-23T00:10", "meter_summer_time": False},
            {"meter_local_time": "2026-11-23T00:11", "meter_summer_time": False}]
        with self.assertRaisesRegex(ValueError, "readback differs"):
            sync_once("/dev/ttyUSB0", 2400, 7, "12345678", "Europe/Oslo",
                      serial_factory=lambda *a, **k: FakeSerial(),
                      sleep=lambda n: None, now=lambda: self.now)

    def test_manual_success_seeds_auto_and_uncertain_write_survives_restart(self):
        class Registry:
            lock = threading.Lock()
            selected = {"12345678": 7}
        cfg = {"allow_clock_sync": True, "auto_clock_sync": True,
               "serial_port": "/dev/ttyUSB0", "clock_timezone": "Europe/Oslo"}
        with tempfile.TemporaryDirectory() as directory:
            def verified(*args, on_write, **kwargs):
                on_write("2026-11-23T00:10", "2026-11-23T04:00")
                return {"changed": True, "manual_required": False, "before": "2026-11-23T00:10",
                        "target": "2026-11-23T04:00", "after": "2026-11-23T04:00"}
            first = ClockController(Registry(), cfg, threading.Lock(), threading.Event(),
                                    operation=verified, pause=lambda n: None, root=directory)
            first.start("12345678")
            first.worker.join()
            self.assertEqual(first.snapshot()["status"], "verified")
            self.assertTrue(first._trusted("12345678"))
            seen = []
            def uncertain(*args, on_write, allow_auto_write, **kwargs):
                seen.append(allow_auto_write)
                on_write("2026-11-23T04:00", "2026-11-23T04:04")
                raise ValueError("readback failed")
            second = ClockController(Registry(), cfg, threading.Lock(), threading.Event(),
                                     operation=uncertain, pause=lambda n: None, root=directory)
            second.start("12345678", auto=True)
            second.worker.join()
            self.assertEqual(seen, [True])
            self.assertEqual(second.snapshot()["status"], "unverified")
            self.assertFalse(second._trusted("12345678"))

    def test_disabled_by_default(self):
        class Registry:
            lock = threading.Lock()
            selected = {"12345678": 7}
        controller = ClockController(Registry(), {}, threading.Lock(), threading.Event())
        with self.assertRaisesRegex(ValueError, "Configuration"):
            controller.start("12345678")
        self.assertEqual(controller.snapshot()["status"], "not_started")


if __name__ == "__main__":
    unittest.main()


class MinuteBoundaryTests(unittest.TestCase):
    @patch("clock_maintenance._read_clock")
    def test_write_waits_for_minute(self, read_clock):
        from datetime import timedelta, timezone
        current = [datetime(2026, 11, 23, 3, 0, 20, tzinfo=timezone.utc)]
        waits = []
        def sleep(seconds):
            waits.append(seconds)
            current[0] += timedelta(seconds=seconds)
        read_clock.side_effect = [
            {"meter_local_time": "2026-11-23T03:00", "meter_summer_time": False},
            {"meter_local_time": "2026-11-23T04:03", "meter_summer_time": False}]
        ser = FakeSerial()
        result = sync_once("/dev/ttyUSB0", 2400, 7, "12345678", "Europe/Oslo",
                           serial_factory=lambda *a, **k: ser, sleep=sleep,
                           now=lambda: current[0])
        self.assertEqual(waits, [61, 39, 61])
        self.assertEqual(result["target"], "2026-11-23T04:02+01:00")
        self.assertEqual(ser.sent[0][9], 2)
