import unittest
from mbus_records import decode_records
from archive_month import decode_month

class ArchiveMonthTests(unittest.TestCase):
    def test_first_month_and_midmonth_exclusion(self):
        records = decode_records(bytes.fromhex(
            "8c 01 06 00 10 00 00 8c 01 14 34 12 00 00 "
            "84 01 6d 00 00 41 3b 9b 11 2d 20 01 00 "
            "94 11 ad 6f 00 0b 92 29 "
            "8c 81 40 14 99 99 00 00 0f 12 07 00 62 04"))
        decoded = {"records": records}
        result = decode_month(decoded, 1)
        self.assertEqual(result["cumulative_kwh"], 1000)
        self.assertAlmostEqual(result["cumulative_m3"], 12.34)
        self.assertEqual(result["meter_storage_local_time"], "2026-11-01T00:00")
        self.assertEqual(result["maxima"]["power"]["value"], 12)
        with self.assertRaises(ValueError):
            decode_month(decoded, 2)

    def test_wrong_frame(self):
        with self.assertRaises(ValueError):
            decode_month({"records": decode_records(bytes.fromhex("0f 12 07 00 62 03"))}, 1)
