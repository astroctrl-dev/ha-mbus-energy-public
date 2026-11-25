"""Synthetic T230 monthly configuration records; not physical test evidence."""
import unittest
from mbus_records import decode_records


class MonthlySetDayTests(unittest.TestCase):
    def test_first_day_midnight(self):
        record, = decode_records(bytes.fromhex("c4 8f 0f 6d 00 00 e1 ff"))
        self.assertEqual(record["kind"], "monthly_set_day")
        self.assertEqual(record["storage"], 511)
        self.assertEqual((record["day"], record["hour"], record["minute"]), (1, 0, 0))

    def test_other_day_and_time(self):
        record, = decode_records(bytes.fromhex("c4 8f 0f 6d 1e 06 ef ff"))
        self.assertEqual(record["kind"], "monthly_set_day")
        self.assertEqual((record["day"], record["hour"], record["minute"]), (15, 6, 30))

    def test_invalid_and_annual_are_not_monthly(self):
        for raw in ("c4 8f 0f 6d 80 00 e1 ff", "c4 8f 0f 6d 00 00 e0 ff",
                    "c4 8f 0f 6d 3f 00 e1 ff", "84 8f 0f 6d 00 00 e1 f1"):
            with self.subTest(raw=raw):
                record, = decode_records(bytes.fromhex(raw))
                self.assertNotEqual(record["kind"], "monthly_set_day")
