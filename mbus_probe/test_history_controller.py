import threading
from unittest.mock import patch
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from analysis_export import make_xlsx
from history_controller import HistoryController, load_history
from meter_registry import MeterRegistry
from monthly_diagnostic import RestorationError


def months():
    return [{"month_back": n, "value": 1000 - n * 10, "unit": "kWh"}
            for n in range(1, 25)]


class HistoryControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry = MeterRegistry(self.root / "meters.json")
        self.registry.set_found([{"meter_id": "00000000", "address": 0, "supported": True}])
        self.registry.select("00000000")
        self.bus_lock = threading.Lock()
        self.stop = threading.Event()
        self.config = {"allow_monthly_history": True,
                       "serial_port": "/dev/ttyUSB0", "baud": 2400}

    def controller(self, reader):
        return HistoryController(self.registry, self.config, self.bus_lock, self.stop,
                                 self.root / "analysis", reader=reader, pause=lambda _s: None)

    def test_gated_operation_and_excel_export_from_persisted_snapshot(self):
        calls = []
        def reader(port, baud, address, meter_id):
            self.assertTrue(self.bus_lock.locked())
            calls.append((port, baud, address, meter_id))
            return months()
        controller = self.controller(reader)
        controller.start("00000000")
        controller.worker.join(3)
        self.assertEqual(controller.snapshot()["status"], "complete")
        self.assertEqual(len(calls), 1)
        histories = load_history(self.root / "analysis", self.registry.snapshot()["selected"])
        self.assertEqual(len(histories), 1)
        self.assertEqual(len(histories[0][1]["stands"]), 24)
        self.assertEqual(len(histories[0][1]["bounded_periods"]), 23)
        self.assertNotIn("00000000", str(histories))
        wb = load_workbook(BytesIO(make_xlsx([], histories)), read_only=True, data_only=True)
        self.assertEqual(wb.sheetnames, ["Info", "Normal records",
                                         "Månedshistorikk", "Månedsforbruk"])
        self.assertEqual(len(list(wb["Månedshistorikk"].values)), 25)
        self.assertEqual(len(list(wb["Månedsforbruk"].values)), 24)
        self.assertIsNone(list(wb["Månedshistorikk"].values)[1][4])
        self.assertEqual(list(wb["Månedsforbruk"].values)[1][3], 10)

    def test_restore_failure_sets_guard_before_bus_unlock(self):
        controller = self.controller(lambda *_: (_ for _ in ()).throw(
            RestorationError("uncertain normal frame")))
        real_lock = self.bus_lock
        observed = []
        class ObservedLock:
            def __enter__(self):
                real_lock.acquire()
            def __exit__(self, *_):
                observed.append(controller.blocked.is_set())
                real_lock.release()
        controller.bus_lock = ObservedLock()
        controller.start("00000000")
        controller.worker.join(3)
        self.assertEqual(observed, [True])
        self.assertEqual(controller.snapshot()["status"], "restore_unverified")

    def test_disabled_cannot_read_or_overwrite(self):
        self.config["allow_monthly_history"] = False
        controller = self.controller(lambda *_: self.fail("physical reader called"))
        with self.assertRaisesRegex(ValueError, "Aktiver månedshistorikk"):
            controller.start("00000000")
        self.assertEqual(load_history(self.root / "analysis", self.registry.snapshot()["selected"]), [])

    def test_bad_collection_preserves_last_valid_snapshot(self):
        good = self.controller(lambda *_: months())
        good.start("00000000")
        good.worker.join(3)
        original = load_history(self.root / "analysis", self.registry.snapshot()["selected"])
        bad = self.controller(lambda *_: months()[:-1])
        bad.start("00000000")
        bad.worker.join(3)
        self.assertEqual(bad.snapshot()["status"], "failed")
        self.assertFalse(self.stop.is_set())
        self.assertEqual(load_history(self.root / "analysis", self.registry.snapshot()["selected"]), original)

    def test_recovery_requires_verified_normal_frame(self):
        controller = self.controller(lambda *_: self.fail("history reader called"))
        controller.root.mkdir(parents=True)
        controller.marker.touch()
        controller.blocked.set()
        self.config["allow_monthly_history"] = False
        with patch.object(self.stop, "wait", return_value=False), \
                patch("history_controller.validate", return_value={"address": 0}), \
                patch("history_controller.select_measurements", return_value={"energy": 1}):
            self.assertFalse(controller.recover_normal(lambda *a, **k: (b"", b"")))
        self.assertTrue(controller.marker.exists())
        self.assertTrue(controller.blocked.is_set())
        from ha_measurements import REQUIRED_SENSORS
        with patch.object(self.stop, "wait", return_value=False), \
                patch("history_controller.validate", return_value={"address": 0, "records": [
                    {"kind": k, "current_record": True} for k in REQUIRED_SENSORS]}), \
                patch("history_controller.select_measurements",
                      return_value={k: 1 for k in REQUIRED_SENSORS if k != "temperature_difference"}):
            self.assertTrue(controller.recover_normal(lambda *a, **k: (b"", b"")))
        self.assertFalse(controller.marker.exists())
        self.assertFalse(controller.blocked.is_set())
        self.assertEqual(controller.snapshot()["status"], "recovered")

    def test_confirmed_history_requires_explicit_restore_permission(self):
        controller = self.controller(lambda *_: self.fail("history reader called"))
        controller.root.mkdir(parents=True)
        controller.marker.touch()
        controller.blocked.set()
        from ha_measurements import REQUIRED_SENSORS
        from unittest.mock import Mock
        historical = {"address": 0, "control": 8}
        reader = Mock(return_value=(b"tx", b"rx"))
        with patch.object(self.stop, "wait", return_value=False), \
                patch("history_controller.validate", return_value=historical), \
                patch("history_controller.extract_months", return_value=months()), \
                patch("history_controller.select_measurements", side_effect=ValueError("not normal")), \
                patch.object(controller, "_restore_interface") as restore:
            self.assertFalse(controller.recover_normal(reader))
            restore.assert_not_called()
            self.assertTrue(controller.marker.exists())
        self.config["allow_recovery_interface_reset"] = True
        with patch.object(self.stop, "wait", return_value=False), \
                patch("history_controller.validate", side_effect=[historical, {"address": 0, "records": [
                    {"kind": k, "current_record": True} for k in REQUIRED_SENSORS]}]), \
                patch("history_controller.extract_months", return_value=months()), \
                patch("history_controller.select_measurements",
                      side_effect=[ValueError("not normal"), {k: 1 for k in REQUIRED_SENSORS}]), \
                patch.object(controller, "_restore_interface") as restore:
            self.assertTrue(controller.recover_normal(reader))
            restore.assert_called_once_with("/dev/ttyUSB0", 2400, 0)
        self.assertFalse(controller.marker.exists())

    def test_uncertain_restore_stops_normal_polling(self):
        def uncertain(*_):
            raise RestorationError("normal frame not verified")
        controller = self.controller(uncertain)
        controller.start("00000000")
        controller.worker.join(3)
        self.assertEqual(controller.snapshot()["status"], "restore_unverified")
        self.assertTrue(controller.blocked.is_set())
        self.assertFalse(self.stop.is_set())
        restarted = self.controller(lambda *_: self.fail("reader called after restart"))
        self.assertTrue(restarted.blocked.is_set())
        self.assertEqual(restarted.snapshot()["status"], "restore_unverified")
        self.assertEqual(load_history(self.root / "analysis", self.registry.snapshot()["selected"]), [])


if __name__ == "__main__":
    unittest.main()
