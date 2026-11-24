import unittest
from datetime import datetime, timezone
from threading import Event
from history_controller import HistorySchedule


class Controller:
    def __init__(self):
        self.config = {"allow_monthly_history": True, "clock_timezone": "Europe/Oslo"}
        self.stop, self.blocked = Event(), Event()
        self.calls = []

    def start(self, meter_id, completion=None):
        self.calls.append(meter_id)
        self.finish = completion


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.c = Controller()
        self.now = datetime(2026, 11, 30, 22, tzinfo=timezone.utc)
        self.tick = 0
        self.s = HistorySchedule(self.c, lambda: self.now, lambda: self.tick)

    def test_startup_and_monthly_slots(self):
        self.s.on_valid_round(["a"])
        self.s.on_valid_round(["a"])
        self.assertEqual(self.c.calls, ["a"])
        self.c.finish(True)
        self.s.on_valid_round(["a"])
        self.now = datetime(2026, 12, 1, 0, tzinfo=timezone.utc)
        self.s.on_valid_round(["a"])
        self.c.finish(True)
        self.s.on_valid_round(["a"])
        self.now = datetime(2026, 12, 2, 0, tzinfo=timezone.utc)
        self.s.on_valid_round(["a"])
        self.assertEqual(self.c.calls, ["a", "a", "a"])

    def test_retry_and_block(self):
        self.s.on_valid_round(["a", "b"])
        self.c.finish(False)
        self.s.on_valid_round(["a", "b"])
        self.assertEqual(self.c.calls, ["a", "b"])
        self.c.finish(True)
        self.tick = 900
        self.c.blocked.set()
        self.s.on_valid_round(["a"])
        self.assertEqual(len(self.c.calls), 2)
        self.c.blocked.clear()
        self.s.on_valid_round(["a"])
        self.assertEqual(self.c.calls[-1], "a")

    def test_disabled(self):
        self.c.config["allow_monthly_history"] = False
        self.s.on_valid_round(["a"])
        self.assertEqual(self.c.calls, [])

    def test_failed_monthly_slot_retries_after_window(self):
        self.s.on_valid_round(["a"])
        self.c.finish(True)
        self.now = datetime(2026, 12, 2, 22, tzinfo=timezone.utc)
        self.s.on_valid_round(["a"])
        self.c.finish(False)
        self.now = datetime(2026, 12, 3, 1, tzinfo=timezone.utc)
        self.tick = 900
        self.s.on_valid_round(["a"])
        self.assertEqual(self.c.calls, ["a", "a", "a"])
        self.c.finish(True)
        self.s.on_valid_round(["a"])
        self.assertEqual(len(self.c.calls), 3)
