import unittest
from battery_diagnostics import battery_evidence, battery_state

class BatteryTests(unittest.TestCase):
    def test_independent_bits(self):
        for ab,ef,warning,exhausted in ((0,0,False,False),(2,0,True,False),
                                        (0,16,False,True),(2,16,True,True),
                                        (0xfd,0xef,False,False)):
            result = battery_evidence(bytes((ab,0xff,ef)),
                "2026-11-25T10:00:00Z",layout_verified=True)
            self.assertIs(result["battery_prewarning"],warning)
            self.assertIs(result["battery_exhausted"],exhausted)
            self.assertNotIn("battery_percent",result)
    def test_unverified_or_invalid_rejected(self):
        with self.assertRaises(ValueError):
            battery_evidence(bytes(3),"2026-11-25T10:00:00Z")
        with self.assertRaises(ValueError):
            battery_evidence(bytes(2),"2026-11-25T10:00:00Z",layout_verified=True)
        with self.assertRaises(ValueError):
            battery_evidence(bytes(3),"2026-11-25T10:00:00",layout_verified=True)
    def test_unknown_not_off(self):
        self.assertEqual(battery_state(None,"battery_prewarning"),"None")
        self.assertEqual(battery_state({"battery_prewarning":False},"battery_prewarning"),"OFF")
        self.assertEqual(battery_state({"battery_prewarning":True},"battery_prewarning"),"ON")

    def test_combined_status(self):
        from battery_diagnostics import battery_status
        for warning, exhausted, expected in (
            (False, False, "normal"), (True, False, "pre-warning"),
            (False, True, "exhausted"), (True, True, "exhausted"),
            (None, False, "unknown"), (True, None, "unknown"),
            (None, True, "exhausted"), (0, False, "unknown"),
        ):
            self.assertEqual(battery_status({"battery_prewarning": warning,
                "battery_exhausted": exhausted}), expected)
        self.assertEqual(battery_status(None), "unknown")
        self.assertEqual(battery_status({}), "unknown")
