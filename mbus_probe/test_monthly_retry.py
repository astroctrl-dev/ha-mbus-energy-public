import tempfile
import unittest
from datetime import date, timedelta
from monthly_retry import MonthlyRetry

class MonthlyRetryTests(unittest.TestCase):
    def test_daily_limit_restart_and_latch(self):
        with tempfile.TemporaryDirectory() as root:
            day = date(2026,12,2)
            key = "history:meter:2026-12"
            for i in range(3):
                ledger = MonthlyRetry(root)
                self.assertTrue(ledger.reserve(key,day,day))
                ledger.finish(key,day,False,"timeout")
                self.assertEqual(ledger.alarm("history:meter")["active"],i==2)
            self.assertFalse(ledger.reserve(key,day,day))
            tomorrow = day + timedelta(days=1)
            self.assertTrue(ledger.reserve(key,tomorrow,day))
            ledger.finish(key,tomorrow,True)
            self.assertTrue(ledger.alarm("history:meter")["active"])
            self.assertFalse(ledger.eligible(key,tomorrow,day))
            ledger.acknowledge("history:meter")
            self.assertFalse(MonthlyRetry(root).alarm("history:meter")["active"])

    def test_ten_day_window(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = MonthlyRetry(root)
            day = date(2026,12,2)
            key = "history:meter:2026-12"
            self.assertFalse(ledger.eligible(key,day-timedelta(days=1),day))
            self.assertTrue(ledger.eligible(key,day+timedelta(days=9),day))
            self.assertFalse(ledger.eligible(key,day+timedelta(days=10),day))

    def test_interrupted_reservations_reconciled_once(self):
        with tempfile.TemporaryDirectory() as root:
            day = date(2026,12,2)
            key = "history:meter:2026-12"
            for i in range(3):
                ledger = MonthlyRetry(root)
                ledger.reconcile_interrupted()
                self.assertTrue(ledger.reserve(key,day,day))
            ledger = MonthlyRetry(root)
            ledger.reconcile_interrupted()
            self.assertFalse(ledger.eligible(key,day,day))
            self.assertEqual(ledger.alarm("history:meter")["reason"],"interrupted_unverified")
            ledger.acknowledge("history:meter")
            ledger.reconcile_interrupted()
            self.assertFalse(ledger.alarm("history:meter")["active"])
            self.assertEqual(ledger.load()[key]["failures"][day.isoformat()],3)

    def test_malformed_nested_counts_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = MonthlyRetry(root)
            ledger.save({"history:meter:2026-12":{"complete":False,"days":{"2026-12-02":"3"}}})
            with self.assertRaises(ValueError):
                ledger.reconcile_interrupted()

    def test_duplicate_finish_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = MonthlyRetry(root)
            day = date(2026,12,2)
            key = "history:meter:2026-12"
            ledger.reserve(key,day,day)
            ledger.finish(key,day,False)
            with self.assertRaises(ValueError):
                ledger.finish(key,day,False)
