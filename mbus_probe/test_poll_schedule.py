import unittest
from poll_schedule import next_hour_delay, next_poll_wait


class ScheduleTests(unittest.TestCase):
    def test_disabled(self):
        self.assertEqual(next_poll_wait(120, False, now=3590), 120)

    def test_five_seconds_before_hour(self):
        self.assertEqual(next_hour_delay(3590, 5), 5)
        self.assertEqual(next_poll_wait(120, True, 5, now=3590), 61)

    def test_even_old_short_interval_cannot_bypass_guard(self):
        self.assertEqual(next_poll_wait(10, False), 61)
        self.assertEqual(next_poll_wait(90, True, 5, now=3590), 61)

    def test_after_target_goes_to_next_hour(self):
        self.assertEqual(next_hour_delay(3596, 5), 3599)
        self.assertEqual(next_poll_wait(120, True, 5, now=3596), 120)

    def test_exact_target_not_repeated(self):
        self.assertEqual(next_hour_delay(3595, 5), 3600)

    def test_zero_offset(self):
        self.assertEqual(next_hour_delay(3599, 0), 1)

    def test_invalid_offset(self):
        for value in (-1, 301):
            with self.assertRaises(ValueError):
                next_hour_delay(0, value)

    def test_utc_day_rollover(self):
        self.assertEqual(next_hour_delay(86390, 5), 5)
