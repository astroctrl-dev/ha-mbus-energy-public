import threading
import json
from history_controller import history_file
from history_model import build_snapshot
from datetime import date
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
        self.schedule.observe_clock("12345678", {"clock_out_of_sync": True, "clock_offset_seconds": 150})
        self.schedule.on_valid_round(["12345678"])
        if self.schedule.worker:
            self.schedule.worker.join(2)

    def test_startup_once_and_monthly_clock(self):
        self.round()
        self.round()
        self.assertEqual(len(self.history.calls), 1)
        self.local = self.local.replace(hour=23)
        self.round()
        self.assertEqual(len(self.clock.calls), 1)
        self.local = self.local.replace(month=12, day=15)
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


    def save_archive(self, month=11, day=1):
        path = history_file(self.tmp.name, "12345678")
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = build_snapshot([dict(month_back=i, value=1000-i*10, unit="kWh")
                                   for i in range(1,25)], self.local.isoformat(),
                                  estimated_month=date(2026,month,1))
        snapshot["schema_version"] = 3
        snapshot["monthly_set_day"] = dict(day=day,hour=0,minute=0)
        path.write_text(json.dumps(snapshot))

    def test_restart_complete_archive_skips_history(self):
        self.schedule.config["auto_clock_sync"] = False
        self.save_archive()
        restarted = MaintenanceSchedule(self.schedule.config, self.clock, self.history,
                                        threading.Event(), now=lambda: self.local,
                                        monotonic=lambda: self.mono, root=self.tmp.name)
        self.assertEqual(list(restarted.due("12345678", self.local)), [])
        self.local = self.local.replace(month=12,day=1)
        self.assertFalse(restarted.history_due("12345678", self.local))
        self.assertTrue(restarted.configuration_due("12345678", self.local))
        self.assertEqual(list(restarted.due("12345678", self.local)), [("configuration", "12345678", "2026-12-01")])

    def test_later_storage_day_waits_until_following_day(self):
        self.local = self.local.replace(month=12,day=1)
        self.save_archive(month=11,day=5)
        self.assertFalse(self.schedule.history_due("12345678", self.local))
        self.local = self.local.replace(day=6)
        self.assertTrue(self.schedule.history_due("12345678", self.local))


    def test_in_sync_clock_needs_no_extra_request(self):
        self.schedule.config["auto_monthly_history"] = False
        self.schedule.observe_clock("12345678", {"clock_out_of_sync": False, "clock_offset_seconds": -42})
        self.schedule.on_valid_round(["12345678"])
        self.assertEqual(self.clock.calls, [])
        self.assertTrue(self.schedule._done(("clock", "12345678", "startup")))

    def test_large_offset_needs_no_extra_request(self):
        self.schedule.config["auto_monthly_history"] = False
        self.schedule.observe_clock("12345678", {"clock_out_of_sync": True, "clock_offset_seconds": 301})
        self.schedule.on_valid_round(["12345678"])
        self.assertEqual(self.clock.calls, [])


    def test_transition_at_actual_boundary_and_persistent_failure(self):
        from dst_transition import TransitionStore
        self.schedule.config["auto_monthly_history"] = False
        self.schedule.config["auto_clock_sync"] = False
        self.local = self.local.replace(month=3, day=28, hour=12)
        meter = "12345678"
        self.schedule.observe_clock(meter, {"clock_offset_seconds": 0, "clock_dst_mismatch": False})
        self.schedule.on_valid_round([meter])
        store = TransitionStore(self.tmp.name, meter)
        self.assertIsNone(store.load()["dst_transition_failed"])
        self.local = self.local.replace(day=29, hour=1)
        self.schedule.observe_clock(meter, {"clock_offset_seconds": -3600, "clock_dst_mismatch": True})
        self.schedule.on_valid_round([meter])
        self.assertIsNone(store.load()["dst_transition_failed"])
        self.local = self.local.replace(hour=3)
        self.schedule.observe_clock(meter, {"clock_offset_seconds": -3600, "clock_dst_mismatch": True})
        self.schedule.on_valid_round([meter])
        self.assertTrue(store.load()["dst_transition_failed"])
        self.local = self.local.replace(day=30)
        self.schedule.observe_clock(meter, {"clock_offset_seconds": 0, "clock_dst_mismatch": False})
        self.schedule.on_valid_round([meter])
        self.assertTrue(store.load()["dst_transition_failed"])
        self.assertEqual(self.clock.calls, [])
        self.local = self.local.replace(month=10, day=25)
        self.schedule.observe_clock(meter, {"clock_offset_seconds": 0, "clock_dst_mismatch": False})
        self.schedule.on_valid_round([meter])
        self.assertFalse(store.load()["dst_transition_failed"])
        self.assertFalse(store.load()["dst_clock_override"])


    def test_standard_time_seasonal_check(self):
        from dst_transition import TransitionStore
        self.schedule.config.update(use_daylight_saving_time=False,
                                    auto_monthly_history=False, auto_clock_sync=False)
        meter = "12345678"
        self.local = self.local.replace(month=3, day=28, hour=12)
        self.schedule.on_valid_round([meter])
        self.local = self.local.replace(day=29, hour=3)
        self.schedule.observe_clock(meter, {"clock_offset_seconds": 0, "clock_dst_mismatch": True})
        self.schedule.on_valid_round([meter])
        store = TransitionStore(self.tmp.name, meter)
        self.assertFalse(store.load()["dst_transition_failed"])
        self.assertEqual(self.clock.calls, [])

    def test_catch_up_after_restart_and_intervention_does_not_clear_latch(self):
        from dst_transition import TransitionStore
        meter = "12345678"
        self.schedule.config["auto_monthly_history"] = False
        self.schedule.config["auto_clock_sync"] = False
        self.local = self.local.replace(month=3, day=28, hour=12)
        self.schedule.on_valid_round([meter])
        self.local = self.local.replace(day=30)
        self.schedule = MaintenanceSchedule(self.schedule.config, self.clock, self.history,
            threading.Event(), now=lambda: self.local, root=self.tmp.name)
        self.schedule.observe_clock(meter, {"clock_offset_seconds": -3600, "clock_dst_mismatch": True})
        self.schedule.on_valid_round([meter])
        store = TransitionStore(self.tmp.name, meter)
        self.assertTrue(store.load()["dst_transition_failed"])
        self.local = self.local.replace(month=10, day=25)
        self.clock.last_write_at = lambda _: self.local.replace(hour=9)
        self.schedule.observe_clock(meter, {"clock_offset_seconds": 0, "clock_dst_mismatch": False})
        self.schedule.on_valid_round([meter])
        self.assertTrue(store.load()["dst_transition_failed"])
        self.assertEqual(store.load()["incidents"][-1]["result"], "intervention_unverified")
