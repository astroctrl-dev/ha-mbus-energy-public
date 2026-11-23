import json
import tempfile
import unittest
from pathlib import Path

from history_model import build_snapshot, save_snapshot


class HistoryModelTests(unittest.TestCase):
    def setUp(self):
        self.months = [{"month_back": n, "value": 60000 - 100 * n, "unit": "kWh"}
                       for n in range(1, 25)]

    def test_24_stands_yield_23_only_and_no_invented_dates(self):
        result = build_snapshot(self.months, "2026-11-23T02:00:00+01:00")
        self.assertEqual(len(result["stands"]), 24)
        self.assertEqual(len(result["bounded_periods"]), 23)
        self.assertEqual(result["bounded_periods"][0]["period_kwh"], 100)
        self.assertEqual(result["captured_at_utc"], "2026-11-23T01:00:00+00:00")
        self.assertTrue(all(row["meter_date"] is None for row in result["stands"]))
        self.assertTrue(all(row["meter_start_date"] is None for row in result["bounded_periods"]))

    def test_invalid_and_decreasing_read_never_replaces_saved_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            good = build_snapshot(self.months, "2026-11-23T01:00:00Z")
            save_snapshot(path, good)
            original = path.read_text()
            with self.assertRaisesRegex(ValueError, "exactly 24"):
                build_snapshot(self.months[:-1], "2026-11-23T01:00:00Z")
            bad = [dict(row) for row in self.months]
            bad[1]["value"] = bad[0]["value"] + 1
            with self.assertRaisesRegex(ValueError, "decreased"):
                build_snapshot(bad, "2026-11-23T01:00:00Z")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                save_snapshot(path, {"stands": [], "bounded_periods": []})
            self.assertEqual(path.read_text(), original)
            self.assertEqual(len(json.loads(original)["stands"]), 24)

    def test_rejects_duplicate_units_and_naive_timestamp(self):
        bad = [dict(row) for row in self.months]
        bad[1]["month_back"] = 1
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_snapshot(bad, "2026-11-23T01:00:00Z")
        bad = [dict(row) for row in self.months]
        bad[0]["unit"] = "MJ"
        with self.assertRaisesRegex(ValueError, "kWh"):
            build_snapshot(bad, "2026-11-23T01:00:00Z")
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_snapshot(self.months, "2026-11-23T01:00:00")
