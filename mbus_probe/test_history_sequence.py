import sys
import types
import unittest
from unittest.mock import patch

from monthly_diagnostic import RestorationError, run


HISTORY_FRAME = bytes.fromhex("68 03 03 68 08 00 72 7a 16")
NORMAL_FRAME = bytes.fromhex("68 03 03 68 08 00 72 7a 16")


class SerialScript:
    def __init__(self, response):
        self.response = bytearray(response)
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, n):
        data = bytes(self.response[:n])
        del self.response[:n]
        return data

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass


class HistorySequenceTests(unittest.TestCase):
    def setUp(self):
        self.decoded = {
            "type": "long", "control": 8, "address": 0, "ci": 0x72,
            "meter_id": "00000000", "manufacturer": "LUG", "medium_code": 4,
            "status": 0,
            "records": [{"kind": "energy", "storage": n, "tariff": 0,
                         "function": 0, "subunit": 0, "unit": "kWh",
                         "value": float(1000 - n * 10)}
                        for n in range(2, 26)],
        }

    def test_select_read_restore_verify_normal_sequence(self):
        serial = SerialScript(b"\xe5" + HISTORY_FRAME + b"\xe5" + NORMAL_FRAME)
        module = types.SimpleNamespace(Serial=lambda *_a, **_kw: serial)
        with patch.dict(sys.modules, {"serial": module}), \
             patch("monthly_diagnostic.validate", return_value=self.decoded), \
             patch("monthly_diagnostic.verify_normal_frame", return_value={"energy": 1}) as verify, \
             patch("monthly_diagnostic.time.sleep") as sleep:
            months, normal_clock, history_read_at = run("/dev/test", 2400, 0, "00000000")
        self.assertEqual(len(months), 24)
        self.assertIsNone(normal_clock)
        self.assertIsInstance(history_read_at, str)
        self.assertEqual(len(serial.writes), 4)
        self.assertEqual(serial.writes[0], bytes.fromhex("68 04 04 68 53 00 50 03 a6 16"))
        self.assertEqual(serial.writes[2], bytes.fromhex("68 03 03 68 53 00 50 a3 16"))
        self.assertEqual(serial.writes[1], serial.writes[3])
        verify.assert_called_once_with(NORMAL_FRAME, 0, "00000000")
        self.assertEqual(sleep.call_count, 4)

    def test_all_commands_spaced_even_after_failed_selection(self):
        for response, expected_writes in ((b"\xe5" + HISTORY_FRAME + b"\xe5" + NORMAL_FRAME, 4),
                                          (b"\x00" + b"\xe5" + NORMAL_FRAME, 3)):
            with self.subTest(expected_writes=expected_writes):
                serial = SerialScript(response)
                module = types.SimpleNamespace(Serial=lambda *_a, **_kw: serial)
                clock = [0.0]
                stamps = []
                original_write = serial.write
                def write(data):
                    stamps.append(clock[0])
                    original_write(data)
                serial.write = write
                def sleep(seconds):
                    clock[0] += seconds
                with patch.dict(sys.modules, {"serial": module}), \
                     patch("monthly_diagnostic.validate", return_value=self.decoded), \
                     patch("monthly_diagnostic.verify_normal_frame", return_value={"energy": 1}), \
                     patch("monthly_diagnostic.time.monotonic", side_effect=lambda: clock[0]), \
                     patch("monthly_diagnostic.time.sleep", side_effect=sleep):
                    if expected_writes == 4:
                        run("/dev/test", 2400, 0, "00000000")
                    else:
                        with self.assertRaisesRegex(ValueError, "selection was not acknowledged"):
                            run("/dev/test", 2400, 0, "00000000")
                self.assertEqual(len(stamps), expected_writes)
                self.assertTrue(all(b-a >= 60 for a,b in zip(stamps, stamps[1:])))
                self.assertGreaterEqual(clock[0]-stamps[-1], 60)

    def test_optional_frame_two_preserves_restore_sequence(self):
        serial = SerialScript(b"\xe5" + HISTORY_FRAME + b"\xe5" + HISTORY_FRAME
                              + b"\xe5" + NORMAL_FRAME)
        module = types.SimpleNamespace(Serial=lambda *_a, **_kw: serial)
        set_day = {"day": 1, "hour": 0, "minute": 0}
        with patch.dict(sys.modules, {"serial": module}), \
             patch("monthly_diagnostic.validate", return_value=self.decoded), \
             patch("monthly_diagnostic.extract_monthly_set_day", return_value=set_day), \
             patch("monthly_diagnostic.verify_normal_frame", return_value={"energy": 1}), \
             patch("monthly_diagnostic.clock_observation", return_value={"meter_local_time": "2026-11-25T02:39"}), \
             patch("monthly_diagnostic.time.sleep") as sleep:
            months, clock, _ = run("/dev/test", 2400, 0, "00000000", read_set_day=True)
        self.assertEqual(len(months), 24)
        self.assertEqual(clock["monthly_set_day"], set_day)
        self.assertEqual(len(serial.writes), 6)
        self.assertEqual(serial.writes[0], bytes.fromhex("68 04 04 68 53 00 50 02 a5 16"))
        self.assertEqual(serial.writes[2], bytes.fromhex("68 04 04 68 53 00 50 03 a6 16"))
        self.assertEqual(serial.writes[4], bytes.fromhex("68 03 03 68 53 00 50 a3 16"))
        self.assertEqual(sleep.call_count, 6)

    def test_failed_restore_never_returns_months(self):
        serial = SerialScript(b"\xe5" + HISTORY_FRAME + b"\x00")
        module = types.SimpleNamespace(Serial=lambda *_a, **_kw: serial)
        with patch.dict(sys.modules, {"serial": module}), \
             patch("monthly_diagnostic.validate", return_value=self.decoded), \
             patch("monthly_diagnostic.time.sleep"):
            with self.assertRaises(RestorationError):
                run("/dev/test", 2400, 0, "00000000")


if __name__ == "__main__":
    unittest.main()
