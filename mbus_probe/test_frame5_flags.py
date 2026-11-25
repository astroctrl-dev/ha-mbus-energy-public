import unittest
from mbus_records import decode_frame5_flags


class Frame5FlagsTests(unittest.TestCase):
    def test_all_fault_bits(self):
        for index in range(10):
            mask = 1 << index
            result = decode_frame5_flags(bytes((0, mask >> 8, mask & 255)))
            self.assertEqual(result["active_fault_codes"], [f"F{index}"])
            self.assertEqual(result["battery_exhausted"], index == 4)

    def test_battery_warning_and_exhaustion(self):
        self.assertEqual(decode_frame5_flags(bytes.fromhex("02 00 00"))["battery_status"], "warning")
        self.assertEqual(decode_frame5_flags(bytes.fromhex("02 00 10"))["battery_status"], "exhausted")
        self.assertEqual(decode_frame5_flags(bytes.fromhex("00 00 00"))["battery_status"], "no_warning_reported")

    def test_unrelated_bits_and_invalid_length(self):
        result = decode_frame5_flags(bytes.fromhex("fc fc 00"))
        self.assertEqual(result["active_fault_codes"], [])
        self.assertFalse(result["battery_prewarning"])
        for invalid in (None, b"", b"1234", "000000"):
            with self.assertRaises(ValueError):
                decode_frame5_flags(invalid)
