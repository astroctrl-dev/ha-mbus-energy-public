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


    def test_monthly_retry_window_crosses_calendar_month(self):
        self.local = self.local.replace(month=12,day=2)
        self.save_archive(month=10,day=28)
        key, first = self.schedule.history_retry_window("12345678",self.local)
        self.assertTrue(key.endswith(":2026-11"))
        self.assertEqual(first,date(2026,11,29))
        self.assertTrue(self.schedule.history_due("12345678",self.local))
        self.assertTrue(self.schedule.monthly_retry.eligible(key,self.local.date(),first))

    def test_monthly_daily_limit_survives_scheduler_restart(self):
        self.schedule.config["auto_clock_sync"] = False
        self.local = self.local.replace(month=12,day=2)
        self.save_archive(month=11,day=1)
        self.history.status = "failed"
        key, first = self.schedule.history_retry_window("12345678",self.local)
        self.assertTrue(self.schedule.monthly_retry.reserve(key,self.local.date(),first))
        self.schedule = MaintenanceSchedule(self.schedule.config, self.clock, self.history,
            threading.Event(), now=lambda:self.local, monotonic=lambda:self.mono, root=self.tmp.name)
        for _ in range(4):
            self.round()
            self.mono += 600
        self.assertEqual(len(self.history.calls),2)
        self.assertTrue(self.schedule.monthly_retry.alarm(key.rsplit(":",1)[0])["active"])
        self.assertFalse(self.schedule.monthly_retry.eligible(key,self.local.date(),first))

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


    def test_legacy_fixed_time_option_does_not_disable_seasonal_check(self):
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
        self.assertEqual(store.load()["policy"], "Europe/Oslo:True")
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


class DailyDiagnosticsIntegrationTests(unittest.TestCase):
    def test_daily_capture_and_restart_reservation(self):
        from types import SimpleNamespace
        from pathlib import Path
        from diagnostic_runtime import DiagnosticRuntime
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            now = datetime(2026,11,26,3,15,tzinfo=ZoneInfo("Europe/Oslo"))
            meter = "00000000"
            runtime = DiagnosticRuntime(now=lambda: now)
            clock = FakeController("verified")
            history = FakeController("complete")
            history.blocked = threading.Event()
            history.marker = Path(root)/"restore-marker"
            history.registry = SimpleNamespace(snapshot=lambda: {"selected":[{"meter_id":meter}], "scan_status":"completed"})
            raw = Path(__file__).with_name("fixture_t230_frame5_sanitized.hex").read_text()
            def capture(meter_id, *, approved, reserve):
                self.assertTrue(reserve())
                return {"response_hex":raw,"read_at_utc":now.isoformat(),"normal_layout_detected":False}
            history.capture_diagnostic_dev = Mock(side_effect=capture)
            config = {"_diagnostic_runtime":runtime, "_frame5_layout_approved":True}
            for _ in range(2):
                schedule = MaintenanceSchedule(config,clock,history,threading.Event(),now=lambda:now,root=root)
                schedule.on_valid_round([meter])
                if schedule.worker:
                    schedule.worker.join(2)
            self.assertEqual(history.capture_diagnostic_dev.call_count, 1)
            self.assertEqual(runtime.snapshot(meter)["battery_status"],"normal")
            self.assertEqual(runtime.snapshot(meter)["meter_installation_status"],"warning")
