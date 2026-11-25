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
