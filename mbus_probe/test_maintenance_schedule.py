import threading
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from maintenance_schedule import MaintenanceSchedule


class FakeController:
    def __init__(self, status):
        self.status = status
        self.calls = []
        self.worker = threading.Thread(target=lambda: None)
        self.worker.start()
    def start(self, meter_id, **kwargs):
        self.calls.append((meter_id, kwargs))
    def snapshot(self):
        return {"status": self.status}


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = datetime(2026, 11, 24, 22, 0, tzinfo=ZoneInfo("Europe/Oslo"))
        self.mono = 1000
        self.clock = FakeController("verified")
        self.history = FakeController("complete")
        self.schedule = MaintenanceSchedule(
            dict(allow_clock_sync=True, auto_clock_sync=True,
                 allow_monthly_history=True, auto_monthly_history=True),
            self.clock, self.history, threading.Event(),
            now=lambda: self.local, monotonic=lambda: self.mono, root=self.tmp.name)

    def round(self):
        self.schedule.on_valid_round(["12345678"])
        if self.schedule.worker:
            self.schedule.worker.join(2)

    def test_startup_once_and_daily_clock(self):
        self.round()
        self.round()
        self.assertEqual(len(self.history.calls), 1)
        self.local = self.local.replace(hour=23)
        self.round()
        self.round()
        self.assertEqual(len(self.clock.calls), 2)
        self.assertEqual(self.clock.calls[0][1], {"auto": True})

    def test_first_and_second_month_day(self):
        self.schedule.config['auto_clock_sync'] = False
        self.local = self.local.replace(day=1, hour=1)
        self.round()
        self.round()
        self.assertEqual(len(self.history.calls), 1)
        self.local = self.local.replace(day=2)
        self.round()
        self.assertEqual(len(self.history.calls), 2)

    def test_retry_is_bounded(self):
        self.schedule.config["auto_clock_sync"] = False
        self.history.status = "failed"
        self.round()
        self.round()
        self.assertEqual(len(self.history.calls), 1)
        self.mono += 600
        self.round()
        self.assertEqual(len(self.history.calls), 2)

    def test_disabled_options_no_jobs(self):
        self.schedule.config["auto_monthly_history"] = False
        self.schedule.config["auto_clock_sync"] = False
        self.local = self.local.replace(hour=23)
        self.round()
        self.assertEqual(self.history.calls + self.clock.calls, [])


    def test_restart_retains_calendar_but_rechecks_startup(self):
        self.schedule.config["auto_clock_sync"] = False
        self.local = self.local.replace(day=1, hour=1)
        self.round()
        restarted = MaintenanceSchedule(self.schedule.config, self.clock, self.history,
                                        threading.Event(), now=lambda: self.local,
                                        monotonic=lambda: self.mono, root=self.tmp.name)
        self.assertEqual(list(restarted.due("12345678", self.local)),
                         [("history", "12345678", "startup")])
