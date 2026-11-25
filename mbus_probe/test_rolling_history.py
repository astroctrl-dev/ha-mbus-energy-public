import unittest
from history_model import build_snapshot
from rolling_history import merge_history

class RollingHistoryTests(unittest.TestCase):
    def snapshot(self, top, month):
        from datetime import date
        return build_snapshot([dict(month_back=i, value=top-i*10, unit="kWh")
                               for i in range(1,25)], "2026-11-25T10:00:00Z",
                              estimated_month=date(2026,month,1))

    def test_rollover_preserves_read_time_and_dates(self):
        old = merge_history(None,self.snapshot(1000,10),"2026-10-02T01:00:00Z")
        new = merge_history(old,self.snapshot(1010,11),"2026-11-02T01:00:00Z")
        self.assertEqual(new["stands"][1]["read_at_utc"],old["stands"][0]["read_at_utc"])
        self.assertEqual(new["stands"][1]["estimated_date"],old["stands"][0]["estimated_date"])
        self.assertEqual(new["stands"][0]["read_at_utc"],"2026-11-02T01:00:00Z")
        self.assertEqual(len(new["stands"]),24)
        self.assertEqual(len(new["bounded_periods"]),23)
        self.assertEqual(new["bounded_periods"][0]["older_read_at_utc"],"2026-10-02T01:00:00Z")

    def test_repeat_preserves_and_explicit_replace_refreshes(self):
        old = merge_history(None,self.snapshot(1000,10),"old")
        new = merge_history(old,self.snapshot(1000,10),"new")
        self.assertEqual(new["stands"][0]["read_at_utc"],"old")
        forced = merge_history(old,self.snapshot(1000,10),"new",replace=True)
        self.assertEqual(forced["stands"][0]["read_at_utc"],"new")

    def test_changed_set_day_preserves_old_dates(self):
        old = merge_history(None,self.snapshot(1000,10),"old")
        incoming = self.snapshot(1010,11)
        for row in incoming["stands"]:
            row["estimated_date"] = row["estimated_date"][:8] + "05T02:00"
        new = merge_history(old,incoming,"new")
        self.assertEqual(new["stands"][0]["estimated_date"],"2026-11-05T02:00")
        self.assertEqual(new["stands"][1]["estimated_date"],"2026-10-01")

    def test_unmatched_history_fails_closed(self):
        old = merge_history(None,self.snapshot(1000,10),"old")
        with self.assertRaises(ValueError):
            merge_history(old,self.snapshot(2000,11),"new")
