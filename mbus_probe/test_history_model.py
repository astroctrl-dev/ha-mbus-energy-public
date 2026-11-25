import json
import tempfile
import unittest
from pathlib import Path

from history_model import build_snapshot, detect_month_shift, estimated_month_at_capture, save_snapshot


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

    def test_estimated_month_requires_agreeing_clocks_and_month_boundary_grace(self):
        def observed(local, read_at="2026-11-23T07:00:00+00:00", summer=False):
            return {"meter_local_time": local, "last_successful_read_utc": read_at,
                    "meter_summer_time": summer}
        self.assertEqual(str(estimated_month_at_capture(
            "2026-11-23T07:01:00Z", observed("2026-11-23T08:00"), True, "Europe/Oslo", "2026-11-23T06:59:00Z")),
            "2026-11-01")
        self.assertIsNone(estimated_month_at_capture(
            "2026-11-23T07:01:00Z", observed("2026-11-23T08:00"), False, "Europe/Oslo", "2026-11-23T06:59:00Z"))
        self.assertIsNone(estimated_month_at_capture(
            "2026-11-23T07:01:00Z", observed("2026-11-23T07:55"), True, "Europe/Oslo", "2026-11-23T06:59:00Z"))
        self.assertIsNone(estimated_month_at_capture(
            "2026-11-01T00:10:00+01:00",
            observed("2026-11-01T00:09", "2026-10-31T23:09:00Z"), True, "Europe/Oslo", "2026-10-31T23:08:00Z"))
        self.assertEqual(str(estimated_month_at_capture(
            "2026-11-01T00:16:00+01:00",
            observed("2026-11-01T00:15", "2026-10-31T23:15:00Z"), True, "Europe/Oslo", "2026-10-31T23:15:00Z")),
            "2026-11-01")
        self.assertIsNone(estimated_month_at_capture(
            "2026-11-01T00:16:00+01:00",
            observed("2026-10-31T23:59", "2026-10-31T23:00:00Z"), True, "Europe/Oslo", "2026-10-31T23:00:00Z"))
        self.assertIsNone(estimated_month_at_capture(
            "2026-11-01T00:16:00+01:00",
            observed("2026-11-01T00:15", "2026-10-31T23:15:00Z", summer=True),
            True, "Europe/Oslo", "2026-10-31T23:15:00Z"))

    def test_history_read_before_quarter_hour_cannot_get_new_month_label(self):
        observation = {"meter_local_time": "2026-11-01T00:16",
                       "last_successful_read_utc": "2026-10-31T23:16:00Z",
                       "meter_summer_time": False}
        self.assertIsNone(estimated_month_at_capture(
            "2026-11-01T00:17:00+01:00", observation, True, "Europe/Oslo",
            "2026-10-31T23:14:00Z"))

    def test_meter_clock_behind_at_actual_history_read_blocks_new_label(self):
        observation = {"meter_local_time": "2026-11-01T00:15",
                       "last_successful_read_utc": "2026-10-31T23:16:30Z",
                       "meter_summer_time": False}
        self.assertIsNone(estimated_month_at_capture(
            "2026-11-01T00:17:30+01:00", observation, True, "Europe/Oslo",
            "2026-10-31T23:15:30Z"))
        self.assertEqual(str(estimated_month_at_capture(
            "2026-11-01T00:19:30+01:00",
            {**observation, "meter_local_time": "2026-11-01T00:18",
             "last_successful_read_utc": "2026-10-31T23:19:00Z"},
            True, "Europe/Oslo", "2026-10-31T23:18:00Z")), "2026-11-01")

    def test_shift_evidence_requires_all_23_positions_to_move(self):
        prior = build_snapshot(self.months, "2026-10-23T07:00:00Z")
        # Old position n is the new position n+1.
        shifted = [{"month_back": 1, "value": self.months[0]["value"] + 90, "unit": "kWh"}]
        shifted += [{"month_back": n + 1, "value": self.months[n - 1]["value"], "unit": "kWh"}
                    for n in range(1, 24)]
        current = build_snapshot(shifted, "2026-11-23T07:00:00Z")
        self.assertTrue(detect_month_shift(prior, current))
        self.assertFalse(detect_month_shift(prior, prior))
        current["stands"][10]["cumulative_kwh"] += 1
        self.assertFalse(detect_month_shift(prior, current))

    def test_fallback_dates_are_frozen_and_explicitly_not_meter_dates(self):
        from datetime import date
        result = build_snapshot(self.months, "2026-11-23T07:00:00Z", date(2026, 11, 1))
        self.assertEqual(result["stands"][0]["estimated_date"], "2026-11-01")
        self.assertEqual(result["stands"][9]["estimated_date"], "2026-02-01")
        self.assertEqual(result["stands"][-1]["estimated_date"], "2024-12-01")
        self.assertTrue(all(r["meter_date"] is None and
                            r["date_source"] == "estimated_first_of_month"
                            for r in result["stands"]))
        self.assertEqual(result["bounded_periods"][0]["estimated_start_date"], "2026-10-01")
        self.assertEqual(result["bounded_periods"][0]["estimated_end_date"], "2026-11-01")

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


class ConfiguredDateTests(unittest.TestCase):
    def test_configured_dates(self):
        from history_model import configured_anchor, build_snapshot
        obs = {"monthly_set_day": {"day": 15, "hour": 6, "minute": 30},
               "meter_local_time": "2026-11-25T08:00",
               "meter_summer_time": False,
               "last_successful_read_utc": "2026-11-25T07:00:00+00:00"}
        anchor = configured_anchor(obs, "2026-11-25T06:58:00+00:00", "Europe/Oslo")
        months = [{"month_back": n, "value": 1000-n, "unit": "kWh"} for n in range(1,25)]
        snapshot = build_snapshot(months, "2026-11-25T07:01:00+00:00", configured=anchor)
        self.assertEqual(snapshot["stands"][0]["estimated_date"], "2026-11-15T06:30")
        self.assertEqual(snapshot["stands"][-1]["estimated_date"], "2024-12-15T06:30")
        self.assertIsNone(snapshot["stands"][0]["meter_date"])
        self.assertEqual(snapshot["stands"][0]["date_source"], "derived_monthly_set_day")
        obs["monthly_set_day"]["day"] = 28
        anchor = configured_anchor(obs, "2026-11-25T06:58:00+00:00", "Europe/Oslo")
        self.assertEqual(anchor.isoformat(timespec="minutes"), "2026-10-28T06:30")
