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

class ArchiveControllerTests(unittest.TestCase):
    def setUp(self):
        from history_controller import history_file
        from history_model import build_snapshot, migrate_snapshot, save_snapshot
        from datetime import date
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        registry = MeterRegistry(root / "meters.json")
        registry.set_found([{"meter_id":"00000000","address":0,"supported":True}])
        registry.select("00000000")
        self.controller = HistoryController(registry, {"allow_monthly_history":True,
            "serial_port":"/dev/unused","baud":2400}, threading.Lock(), threading.Event(), root/"analysis")
        self.path = history_file(self.controller.root,"00000000")
        self.saved = migrate_snapshot(build_snapshot(months(),"2026-11-25T10:00:00Z",
            estimated_month=date(2026,11,1)))
        save_snapshot(self.path,self.saved)
        self.original = self.path.read_bytes()

    def test_dev_approval_required(self):
        with patch("history_controller.shared_timing_active",return_value=True):
            with self.assertRaises(ValueError):
                self.controller.collect_archive_dev("00000000",1,reader=lambda *a,**k:self.fail("I/O"))
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_data_rejection_preserves_file_without_blocking(self):
        from archive_acquisition import ArchiveDataError
        def reader(*a,**k):
            self.assertTrue(self.controller.bus_lock.locked())
            self.assertTrue(self.controller.marker.exists())
            raise ArchiveDataError("conflict")
        with patch("history_controller.shared_timing_active",return_value=True):
            with self.assertRaises(ArchiveDataError):
                self.controller.collect_archive_dev("00000000",1,approved=True,reader=reader)
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse(self.controller.blocked.is_set())
        self.assertFalse(self.controller.marker.exists())

    def test_restore_failure_preserves_file_and_guard(self):
        def reader(*a,**k):
            raise RestorationError("uncertain")
        with patch("history_controller.shared_timing_active",return_value=True):
            with self.assertRaises(RestorationError):
                self.controller.collect_archive_dev("00000000",1,approved=True,reader=reader)
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertTrue(self.controller.blocked.is_set())
        self.assertTrue(self.controller.marker.exists())

    def test_extended_archive_requires_confirmation(self):
        with patch("history_controller.shared_timing_active",return_value=True):
            with self.assertRaises(ValueError):
                self.controller.start_extended_archive("00000000")
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_extended_archive_stops_on_first_rejection(self):
        from archive_acquisition import ArchiveDataError
        with patch("history_controller.shared_timing_active",return_value=True), \
             patch.object(self.controller,"collect_archive_dev",side_effect=ArchiveDataError("bad")) as read:
            self.controller.start_extended_archive("00000000",confirmed=True)
            self.controller.worker.join(2)
            read.assert_called_once_with("00000000",1,approved=True,_reserved=True)
        self.assertEqual(self.controller.snapshot()["status"],"failed")
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_extended_archive_manual_reads_all_positions(self):
        with patch("history_controller.shared_timing_active",return_value=True), \
             patch.object(self.controller,"collect_archive_dev",return_value=self.saved) as read:
            self.controller.start_extended_archive("00000000",confirmed=True)
            self.controller.worker.join(2)
            self.assertEqual([c.args[1] for c in read.call_args_list],list(range(1,25)))
        self.assertEqual(self.controller.snapshot()["status"],"complete")

    def test_progress_idle_and_failed(self):
        self.assertEqual(self.controller.snapshot()["archive_progress"],{})
        from archive_acquisition import ArchiveDataError
        def reject(*args,**kwargs):
            state=self.controller.snapshot()
            self.assertEqual(state["archive_progress"]["1"],"request")
            self.assertEqual(state["archive_progress"]["2"],"waiting")
            raise ArchiveDataError("bad")
        with patch("history_controller.shared_timing_active",return_value=True), \
             patch.object(self.controller,"collect_archive_dev",side_effect=reject):
            self.controller.start_extended_archive("00000000",confirmed=True)
            self.controller.worker.join(2)
        self.assertEqual(self.controller.snapshot()["archive_progress"]["1"],"failed")
        self.assertEqual(self.controller.snapshot()["archive_progress"]["2"],"waiting")

    def test_registry_readable_during_transaction(self):
        def reader(*args,**kwargs):
            finished=threading.Event()
            def read_registry():
                self.controller.registry.snapshot()
                finished.set()
            t=threading.Thread(target=read_registry,daemon=True)
            t.start()
            self.assertTrue(finished.wait(1),"GUI blocked by registry lock")
            return self.saved
        with patch("history_controller.shared_timing_active",return_value=True):
            self.controller.collect_archive_dev("00000000",1,approved=True,reader=reader)

    def test_owned_archive_recovery_without_optional_reset(self):
        from ha_measurements import REQUIRED_SENSORS
        from unittest.mock import Mock
        import json
        c=self.controller
        c.root.mkdir(parents=True,exist_ok=True)
        c.marker.write_text(json.dumps({"operation":"archive_frame4","meter_id":"00000000","address":0}))
        c.blocked.set()
        historical={"address":0,"control":8}
        normal={"address":0,"records":[{"kind":k,"current_record":True} for k in REQUIRED_SENSORS]}
        with patch("history_controller.shared_timing_active",return_value=True), \
             patch("history_controller.validate",side_effect=[historical,normal]), \
             patch("history_controller.extract_months",side_effect=ValueError), \
             patch("history_controller.extract_monthly_set_day",side_effect=ValueError), \
             patch("history_controller.select_measurements",side_effect=[ValueError,{k:1 for k in REQUIRED_SENSORS}]), \
             patch.object(c,"_confirmed_archive",return_value=True), \
             patch.object(c,"_restore_interface") as restore:
            self.assertTrue(c.recover_normal(Mock(return_value=(b"tx",b"rx"))))
            restore.assert_called_once_with("/dev/unused",2400,0)
        self.assertFalse(c.marker.exists())
        self.assertFalse(c.blocked.is_set())
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_every_start_selects_normal_even_without_marker(self):
        from ha_measurements import REQUIRED_SENSORS
        from unittest.mock import Mock
        c=self.controller
        self.assertFalse(c.marker.exists())
        c.require_startup_normal()
        self.assertTrue(c.blocked.is_set())
        normal={"address":0,"records":[{"kind":k,"current_record":True} for k in REQUIRED_SENSORS]}
        with patch("history_controller.shared_timing_active",return_value=True), \
             patch("history_controller.validate",return_value=normal), \
             patch("history_controller.select_measurements",return_value={k:1 for k in REQUIRED_SENSORS}), \
             patch.object(c,"_restore_interface") as restore:
            reader=Mock(return_value=(b"tx",b"rx"))
            self.assertTrue(c.recover_normal(reader))
            restore.assert_called_once_with("/dev/unused",2400,0)
            reader.assert_called_once()
        self.assertFalse(c.blocked.is_set())
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_startup_failure_preserves_guard(self):
        c=self.controller
        c.require_startup_normal()
        with patch("history_controller.shared_timing_active",return_value=True), \
             patch.object(c,"_restore_interface",side_effect=ValueError("no ACK")):
            self.assertFalse(c.recover_normal(lambda *a,**k:self.fail("unexpected read")))
        self.assertTrue(c.blocked.is_set())
        self.assertTrue(c.startup_pending)
        self.assertTrue(c.marker.exists())
        self.assertEqual(self.path.read_bytes(),self.original)
