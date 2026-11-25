import unittest
from datetime import date
from copy import deepcopy
from history_model import build_snapshot, migrate_snapshot

class HistoryMigrationTests(unittest.TestCase):
    def original(self):
        s = build_snapshot([dict(month_back=i,value=1000-i*10,unit="kWh") for i in range(1,25)],
                           "2026-11-25T03:55:00Z",date(2026,11,1))
        s["date_provenance"] = {"history_read_at_utc":"2026-11-25T03:51:00Z"}
        return s

    def test_all_47_and_one_shot(self):
        old = self.original()
        copy = deepcopy(old)
        new = migrate_snapshot(old)
        self.assertEqual(old,copy)
        self.assertEqual(new["schema_version"],3)
        for row in new["stands"]+new["bounded_periods"]:
            self.assertEqual(row["read_at_utc"],"2026-11-25T03:51:00Z")
        for i,p in enumerate(new["bounded_periods"]):
            self.assertEqual(p["estimated_date"],new["stands"][i]["estimated_date"])
            self.assertEqual(p["period_kwh"],old["bounded_periods"][i]["period_kwh"])
        self.assertIs(migrate_snapshot(new),new)

    def test_invalid_difference_refused_without_mutation(self):
        old=self.original()
        old["bounded_periods"][0]["period_kwh"]=99
        copy=deepcopy(old)
        with self.assertRaises(ValueError):
            migrate_snapshot(old)
        self.assertEqual(old,copy)


    def test_explicit_job_only_and_persistent_completion(self):
        import tempfile, threading, json
        from pathlib import Path
        from history_controller import HistoryController, history_file, load_history
        from history_model import save_snapshot
        from meter_registry import MeterRegistry
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = MeterRegistry(root / "meters.json")
            registry.set_found([{"meter_id":"00000000","address":0,"supported":True}])
            registry.select("00000000")
            path = history_file(root,"00000000")
            save_snapshot(path,self.original())
            controller = HistoryController(registry,{"allow_monthly_history":True},threading.Lock(),threading.Event(),root,reader=lambda *_: self.fail("bus read"))
            self.assertEqual(load_history(root,registry.snapshot()["selected"])[0][1]["schema_version"],2)
            self.assertEqual(controller.migration_status("00000000"),"pending")
            with self.assertRaises(ValueError):
                controller.start("00000000")
            controller.migrate("00000000")
            self.assertEqual(controller.migration_status("00000000"),"complete")
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                controller.migrate("00000000")
            self.assertEqual(path.read_bytes(),original)
