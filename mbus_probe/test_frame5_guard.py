import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from history_controller import HistoryController
from frame5_capture import CaptureError
from monthly_diagnostic import RestorationError


class Frame5GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = SimpleNamespace(selected={"00000000": 1}, lock=threading.Lock())
        self.controller = HistoryController(self.registry, {"serial_port":"fake"},
            threading.Lock(), threading.Event(), root=self.tmp.name)
        p = patch("history_controller.shared_timing_active", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_success(self):
        def reader(*args, **kwargs):
            self.assertTrue(self.controller.marker.exists())
            self.assertTrue(self.controller.bus_lock.locked())
            return {"read_at_utc":"2026-11-26T00:00:00Z","layout_verified":False}
        result = self.controller.capture_diagnostic_dev("00000000", approved=True, reader=reader)
        self.assertFalse(result["layout_verified"])
        self.assertFalse(self.controller.marker.exists())

    def test_failure_keeps_guard(self):
        def reader(*args, **kwargs):
            raise RestorationError("not restored")
        with self.assertRaises(RestorationError):
            self.controller.capture_diagnostic_dev("00000000", approved=True, reader=reader)
        self.assertTrue(self.controller.marker.exists())
        self.assertTrue(self.controller.blocked.is_set())

    def test_safe_failure_clears_guard(self):
        def reader(*args, **kwargs):
            raise CaptureError("invalid capture")
        with self.assertRaises(CaptureError):
            self.controller.capture_diagnostic_dev("00000000", approved=True, reader=reader)
        self.assertFalse(self.controller.marker.exists())
        self.assertFalse(self.controller.blocked.is_set())

    def test_approval_required(self):
        with self.assertRaises(ValueError):
            self.controller.capture_diagnostic_dev("00000000")
        self.assertFalse(self.controller.marker.exists())

    def test_owned_recovery_identity(self):
        marker = {"operation":"diagnostic_frame5","meter_id":"00000000","address":1}
        decoded = dict(type="long",ci=0x72,control=8,address=1,meter_id="00000000",
                       manufacturer="LUG",medium_code=4,status=0xff)
        check = self.controller._owned_diagnostic
        self.assertTrue(check(decoded,1,"00000000",marker))
        self.assertFalse(check(decoded,1,"00000000",None))
        self.assertFalse(check(decoded,1,"00000000",{**marker,"address":2}))
        for field, value in (("meter_id","00000001"),("medium_code",7),
                             ("manufacturer","ABC"),("address",2),("ci",0x70)):
            self.assertFalse(check({**decoded,field:value},1,"00000000",marker))

    def test_capture_preserves_history_status(self):
        previous = {"status":"complete","error":None,"captured_at_utc":"old-history"}
        self.controller.state = dict(previous)
        self.controller.capture_diagnostic_dev("00000000", approved=True,
            reader=lambda *a, **k: {"read_at_utc":"new-diagnostic","layout_verified":False})
        self.assertEqual(self.controller.state, previous)

    def test_running_scan_rejects_capture(self):
        self.registry.scan_status = "running"
        with self.assertRaises(ValueError):
            self.controller.capture_diagnostic_dev("00000000", approved=True,
                reader=lambda *a, **k: self.fail("unexpected bus access"))
        self.assertFalse(self.controller.marker.exists())

    def recovery_fixture(self, startup=False):
        import json
        from mbus_probe import validate
        normal = bytes.fromhex(Path(__file__).with_name("fixture_t230_sanitized.hex").read_text())
        address = validate(normal)["address"]
        self.registry.selected = {"00000000":address}
        # Synthetic non-normal telegram: identity is real fixture data, payload
        # deliberately not a frame-5 layout claim.
        payload = normal[4:19] + bytes.fromhex("0f 12 07 00 62 05")
        other = bytes((0x68,len(payload),len(payload),0x68)) + payload + bytes((sum(payload)&255,0x16))
        marker = {"operation":"diagnostic_frame5","meter_id":"00000000","address":address}
        self.controller.marker.write_text(json.dumps(marker))
        self.controller.blocked.set()
        self.controller.startup_pending = startup
        return address, normal, other

    def test_recovery_end_to_end(self):
        for startup in (False, True):
            with self.subTest(startup=startup):
                address, normal, other = self.recovery_fixture(startup)
                with patch.object(self.controller, "_restore_interface") as restore:
                    from unittest.mock import Mock
                    reader = Mock(side_effect=[(b"req",other),(b"req",normal)])
                    self.assertTrue(self.controller.recover_normal(reader=reader))
                    restore.assert_called_once_with("fake",2400,address)
                    self.assertEqual(reader.call_count,2)
                self.assertFalse(self.controller.blocked.is_set())
                self.assertFalse(self.controller.marker.exists())
                self.assertFalse(self.controller.startup_pending)

    def test_recovery_wrong_identity_keeps_guard(self):
        address, normal, other = self.recovery_fixture(True)
        wrong = bytearray(other)
        wrong[7:11] = bytes.fromhex("01 00 00 00")
        wrong[-2] = sum(wrong[4:-2]) & 255
        with patch.object(self.controller, "_restore_interface") as restore:
            self.assertFalse(self.controller.recover_normal(reader=lambda *a, **k:(b"req",bytes(wrong))))
            restore.assert_not_called()
        self.assertTrue(self.controller.blocked.is_set())
        self.assertTrue(self.controller.marker.exists())

    def test_recovery_requires_normal_after_reset(self):
        address, normal, other = self.recovery_fixture(True)
        with patch.object(self.controller, "_restore_interface") as restore:
            self.assertFalse(self.controller.recover_normal(reader=lambda *a, **k:(b"req",other)))
            restore.assert_called_once()
        self.assertTrue(self.controller.blocked.is_set())
        self.assertTrue(self.controller.marker.exists())
