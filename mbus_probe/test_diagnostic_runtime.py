import unittest
from datetime import datetime, timezone, timedelta
from diagnostic_runtime import DiagnosticRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
        self.runtime = DiagnosticRuntime(now=lambda: self.now)

    def test_unknown_and_passive(self):
        self.runtime.observe_normal("00000000", "0x62", self.now.isoformat())
        result = self.runtime.snapshot("00000000")
        self.assertEqual(result["battery_status"], "unknown")
        self.assertNotIn("active_meter_faults", result)
        self.assertEqual(result["extension"]["extension_byte"], "0x62")

    def test_verified_and_expiry(self):
        self.runtime.observe_verified("00000000", bytes.fromhex("02 00 00"),
                                     self.now.isoformat(), layout_verified=True)
        self.assertEqual(self.runtime.snapshot("00000000")["battery_status"], "pre-warning")
        self.assertEqual(self.runtime.snapshot("00000001")["battery_status"], "unknown")
        self.now += timedelta(hours=27)
        self.assertEqual(self.runtime.snapshot("00000000")["battery_status"], "unknown")

    def test_unverified_and_invalidation(self):
        with self.assertRaises(ValueError):
            self.runtime.observe_verified("00000000", bytes(3), self.now.isoformat())
        self.runtime.observe_verified("00000000", bytes(3), self.now.isoformat(), layout_verified=True)
        self.runtime.invalidate("00000000")
        self.assertEqual(self.runtime.snapshot("00000000")["battery_status"], "unknown")


    def test_persistent_restart_expiry_and_invalidation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            def restart():
                return DiagnosticRuntime(now=lambda: self.now, root=root)
            first = restart()
            first.observe_verified("00000000", bytes.fromhex("04 00 00"),
                                   self.now.isoformat(), layout_verified=True)
            self.assertEqual(restart().snapshot("00000000")["meter_installation_status"], "warning")
            self.assertEqual(restart().snapshot("00000001")["battery_status"], "unknown")
            self.now += timedelta(hours=27)
            self.assertEqual(restart().snapshot("00000000")["battery_status"], "unknown")
            first = restart()
            first.observe_verified("00000000", bytes(3), self.now.isoformat(), layout_verified=True)
            first.invalidate("00000000")
            self.assertEqual(restart().snapshot("00000000")["battery_status"], "unknown")

    def test_corrupt_persistence_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            first = DiagnosticRuntime(now=lambda: self.now, root=root)
            first.observe_verified("00000000", bytes(3), self.now.isoformat(), layout_verified=True)
            first._path("00000000").write_text("invalid")
            restarted = DiagnosticRuntime(now=lambda: self.now, root=root)
            self.assertEqual(restarted.snapshot("00000000")["battery_status"], "unknown")
