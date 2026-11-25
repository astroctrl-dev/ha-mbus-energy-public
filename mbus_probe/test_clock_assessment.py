import unittest
from clock_model import assess_clock

class ClockAssessmentTests(unittest.TestCase):
    def test_offset_and_threshold(self):
        r = dict(kind="meter_local_time",storage=0,tariff=0,subunit=0,function=0,
                 timezone="unspecified",summer_time=False,value="2026-11-25T12:00")
        d = {"records":[r]}
        self.assertEqual(assess_clock(d,"2026-11-25T11:00:42Z","Europe/Oslo")["clock_offset_seconds"],-42)
        self.assertFalse(assess_clock(d,"2026-11-25T11:02:00Z","Europe/Oslo")["clock_out_of_sync"])
        self.assertTrue(assess_clock(d,"2026-11-25T11:02:01Z","Europe/Oslo")["clock_out_of_sync"])
        self.assertIsNone(assess_clock({"records":[]},"2026-11-25T11:00:00Z","Europe/Oslo")["clock_out_of_sync"])

    def test_summer_policy(self):
        r = dict(kind="meter_local_time",storage=0,tariff=0,subunit=0,function=0,
                 timezone="unspecified",summer_time=False,value="2026-07-01T12:00")
        self.assertFalse(assess_clock({"records":[r]}, "2026-07-01T11:00:00Z", "Europe/Oslo", False)["clock_out_of_sync"])
        self.assertTrue(assess_clock({"records":[r]}, "2026-07-01T11:00:00Z", "Europe/Oslo", True)["clock_dst_mismatch"])


    def test_seasonal_offset_after_downtime(self):
        from clock_model import seasonal_offset
        from datetime import datetime, timezone
        summer = datetime(2026, 4, 10, 12, tzinfo=timezone.utc)
        winter = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        self.assertTrue(seasonal_offset(summer, "Europe/Oslo", True, False, 3600))
        self.assertTrue(seasonal_offset(winter, "Europe/Oslo", True, True, -3600))
        self.assertFalse(seasonal_offset(summer, "Europe/Oslo", True, False, -3600))
        self.assertFalse(seasonal_offset(summer, "Europe/Oslo", False, False, 3600))
