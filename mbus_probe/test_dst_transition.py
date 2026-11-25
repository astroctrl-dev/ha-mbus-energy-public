import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from dst_transition import latest_transition, evaluate_transition, TransitionStore


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneInfo("Europe/Oslo")
        self.spring = datetime(2026, 3, 29, 12, tzinfo=self.zone)
        self.autumn = datetime(2026, 10, 25, 12, tzinfo=self.zone)

    def test_transition_and_catch_up(self):
        a = latest_transition(self.spring, self.zone.key)
        self.assertEqual(a["shift_seconds"], 3600)
        self.assertNotEqual(latest_transition(self.spring.replace(hour=1), self.zone.key)["key"], a["key"])
        self.assertEqual(latest_transition(self.spring.replace(day=30), self.zone.key), a)
        self.assertEqual(latest_transition(self.autumn, self.zone.key)["shift_seconds"], -3600)

    def test_exact_utc_boundary_and_autumn_fold(self):
        for instant, shift in ((datetime(2027, 3, 28, 1, tzinfo=timezone.utc), 3600),
                               (datetime(2027, 10, 31, 1, tzinfo=timezone.utc), -3600)):
            transition = latest_transition(instant, self.zone.key)
            self.assertEqual(transition["at_utc"], instant.isoformat())
            self.assertEqual(transition["shift_seconds"], shift)
            self.assertNotEqual(latest_transition(instant - timedelta(seconds=1), self.zone.key)["key"],
                                transition["key"])
            self.assertEqual(latest_transition(instant + timedelta(hours=1), self.zone.key), transition)

    def test_standard_time_projection(self):
        from clock_model import configured_local
        for month, expected in ((1, 13), (7, 14)):
            stamp = datetime(2027, month, 1, 12, tzinfo=timezone.utc)
            self.assertEqual(configured_local(stamp, self.zone.key, True).hour, expected)
            self.assertEqual(configured_local(stamp, self.zone.key, False).hour, 13)

    def test_classification(self):
        for date, offset in ((self.spring, -3600), (self.autumn, 3600)):
            t = latest_transition(date, self.zone.key)
            self.assertEqual(evaluate_transition(t, offset, True), "seasonal_correction_required")
            self.assertEqual(evaluate_transition(t, -offset, True), "failed")
            self.assertEqual(evaluate_transition(t, 0, True), "independent_success")
            self.assertEqual(evaluate_transition(t, 0, False), "independent_success")
            self.assertEqual(evaluate_transition(t, None, False), "unknown")

    def test_persistent_latches(self):
        a = latest_transition(self.spring, self.zone.key)
        b = latest_transition(self.autumn, self.zone.key)
        with tempfile.TemporaryDirectory() as root:
            store = TransitionStore(root, "synthetic-meter")
            self.assertIsNone(store.load()["dst_transition_failed"])
            self.assertTrue(store.observe(a, -3600, True, self.spring)["dst_transition_failed"])
            self.assertIsNone(store.load()["dst_clock_override"])
            with self.assertRaises(ValueError):
                store.verified_override(a, 3600, self.spring)
            store.verified_override(a, 0, self.spring)
            store = TransitionStore(root, "synthetic-meter")
            self.assertTrue(store.observe(a, 0, False, self.spring)["dst_transition_failed"])
            self.assertTrue(store.observe(b, None, False, self.autumn)["dst_clock_override"])
            state = store.observe(b, 0, False, self.autumn)
            self.assertFalse(state["dst_transition_failed"])
            self.assertFalse(state["dst_clock_override"])
            self.assertEqual(len(state["incidents"]), 1)
            self.assertEqual(state["incidents"][0]["after_offset_seconds"], 0)

    def test_bit_only_cannot_be_override(self):
        a = latest_transition(self.spring, self.zone.key)
        with tempfile.TemporaryDirectory() as root:
            store = TransitionStore(root, "synthetic-meter")
            store.observe(a, 0, True, self.spring)
            with self.assertRaises(ValueError):
                store.verified_override(a, 0, self.spring)

    def test_migration_baseline_does_not_claim_success(self):
        a = latest_transition(self.spring, self.zone.key)
        b = latest_transition(self.autumn, self.zone.key)
        with tempfile.TemporaryDirectory() as root:
            store = TransitionStore(root, "synthetic-meter")
            state = store.establish_baseline(a, "Europe/Oslo:True")
            self.assertIsNone(state["dst_transition_failed"])
            self.assertIsNone(store.observe(a, 0, False, self.spring)["dst_transition_failed"])
            store.observe(b, 3600, True, self.autumn)
            state = store.establish_baseline(b, "Europe/Oslo:False")
            self.assertTrue(state["dst_transition_failed"])
            self.assertEqual(len(state["incidents"]), 1)

    def test_corruption_not_success(self):
        with tempfile.TemporaryDirectory() as root:
            store = TransitionStore(root, "synthetic-meter")
            store.path.write_text("{}")
            with self.assertRaises(ValueError):
                store.load()


if __name__ == "__main__":
    unittest.main()
