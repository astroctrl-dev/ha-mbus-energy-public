import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from diagnostic_schedule import DiagnosticSchedule


class DiagnosticScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = DiagnosticSchedule(self.tmp.name, "Europe/Oslo")
        self.now = datetime(2026, 11, 26, 22, 59, tzinfo=timezone.utc)
        self.flags = dict(enabled=True, layout_verified=True, fresh_normal=True, bus_idle=True)

    def test_all_gates_required(self):
        for key in self.flags:
            self.assertFalse(self.s.reserve("00000000", self.now, **{**self.flags,key:False}))
        self.assertFalse(self.s.path.exists())

    def test_daily_reservation_survives_restart(self):
        self.assertTrue(self.s.reserve("00000000", self.now, **self.flags))
        restart = DiagnosticSchedule(self.tmp.name, "Europe/Oslo")
        self.assertFalse(restart.reserve("00000000", self.now, **self.flags))
        self.assertTrue(restart.reserve("00000000", self.now + timedelta(hours=4, minutes=16), **self.flags))
        self.assertFalse(restart.reserve("00000000", self.now, **self.flags))

    def test_per_meter_and_invalid_time(self):
        self.assertTrue(self.s.reserve("00000000", self.now, **self.flags))
        self.assertTrue(self.s.reserve("00000001", self.now, **self.flags))
        self.assertFalse(self.s.reserve("00000002", self.now.replace(tzinfo=None), **self.flags))
        self.assertFalse(self.s.reserve("invalid", self.now, **self.flags))

    def test_corrupt_state_fails_closed(self):
        self.s.path.write_text("invalid")
        self.assertFalse(self.s.reserve("00000000", self.now, **self.flags))
        self.assertEqual(self.s.path.read_text(), "invalid")

    def test_local_time_boundary_and_busy_deferral(self):
        before = datetime(2026, 11, 26, 2, 14, 59, tzinfo=timezone.utc)
        due = before + timedelta(seconds=1)
        self.assertFalse(self.s.reserve("00000000", before, **self.flags))
        self.assertFalse(self.s.reserve("00000000", due, **{**self.flags, "bus_idle": False}))
        self.assertTrue(self.s.reserve("00000000", due + timedelta(minutes=10), **self.flags))
        self.assertFalse(self.s.reserve("00000000", due + timedelta(hours=5), **self.flags))

    def test_dst_days(self):
        for instant in (datetime(2026, 3, 29, 1, 15, tzinfo=timezone.utc),
                        datetime(2026, 10, 25, 2, 15, tzinfo=timezone.utc)):
            self.assertFalse(self.s.reserve("00000001", instant - timedelta(seconds=1), **self.flags))
            self.assertTrue(self.s.reserve("00000001", instant, **self.flags))
