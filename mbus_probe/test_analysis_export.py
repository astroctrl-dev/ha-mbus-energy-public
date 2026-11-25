import tempfile
import unittest
from pathlib import Path
from io import BytesIO
from openpyxl import load_workbook

from mbus_probe import validate
from ha_measurements import select_measurements
from analysis_export import append_sample, load_samples, make_sample, make_xlsx


class AnalysisExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).with_name("fixture_t230_sanitized.hex")
        cls.decoded = validate(bytes.fromhex(fixture.read_text()))

    def test_sanitized_normal_records_and_bounded_persistence(self):
        select_measurements(self.decoded, "00000000")
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "alias.key"
            path = Path(tmp) / "samples.jsonl"
            sample = make_sample(self.decoded, "00000000", "2026-11-23T02:00:00Z", key)
            self.assertTrue(sample["alias"].startswith("Meter-"))
            self.assertEqual(sample["meter_local_time"], "2024-01-01T12:00")
            self.assertTrue(any(r["kind"] == "energy" for r in sample["records"]))
            append_sample(path, sample, limit=2)
            append_sample(path, sample, limit=2)
            append_sample(path, sample, limit=2)
            self.assertEqual(len(load_samples(path)), 2)
            self.assertNotIn("00000000", path.read_text())
            self.assertNotIn("raw_hex", path.read_text())
            self.assertNotIn("meter_id", path.read_text())
            self.assertEqual(sample["alias"],
                             make_sample(self.decoded, "00000000", "2026-11-23T02:00:00Z", key)["alias"])

    def test_partial_archive_excludes_invalid_current_record(self):
        records = [{**r, "value": -1} if r.get("kind") == "energy" and r.get("current_record")
                   else r for r in self.decoded["records"]]
        decoded = {**self.decoded, "records": records}
        selected = select_measurements(decoded, "00000000")
        with tempfile.TemporaryDirectory() as tmp:
            sample = make_sample(decoded, "00000000", "2026-11-23T02:00:00Z",
                                 Path(tmp) / "alias.key", validated=selected)
        current_energy = [r for r in sample["records"] if r["kind"] == "energy"
                          and r["storage"] == 0 and r["tariff"] == 0 and r["function"] == 0]
        self.assertEqual(current_energy, [])
        self.assertTrue(any(r["kind"] == "power" for r in sample["records"]))

    def test_workbook_contains_values_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = make_sample(self.decoded, "00000000", "2026-11-23T02:00:00Z",
                                 Path(tmp) / "alias.key")
            payload = make_xlsx([sample])
        wb = load_workbook(BytesIO(payload), read_only=True, data_only=True)
        self.assertEqual(wb.sheetnames, ["Info", "Normal records", "Diagnostics"])
        rows = list(wb["Normal records"].values)
        self.assertEqual(rows[0][0:3], ("alias", "read_at_utc", "meter_local_time"))
        energy = [r for r in rows[1:] if r[5] == "energy" and r[6] == 0 and r[7] == 0]
        self.assertEqual(energy[0][10:12], (12345, "kWh"))
        self.assertNotIn("00000000", str(rows))
        self.assertEqual(list(wb["Info"].values)[3][1],
                         "Unspecified; local meter time is not UTC")

    def test_history_has_24_stands_and_23_differences(self):
        from history_model import build_snapshot
        months = [{"month_back": n, "value": 1000 - 10*n, "unit": "kWh"}
                  for n in range(1, 25)]
        history = build_snapshot(months, "2026-11-23T02:00:00Z")
        wb = load_workbook(BytesIO(make_xlsx([], history)), read_only=True, data_only=True)
        self.assertEqual(len(list(wb["Månedshistorikk"].values)), 25)
        self.assertEqual(len(list(wb["Månedsforbruk"].values)), 24)
        self.assertEqual(list(wb["Månedsforbruk"].values)[1][3], 10)
        self.assertIsNone(list(wb["Månedshistorikk"].values)[1][4])

    def test_localized_temperature_export_preserves_numeric_values_and_source(self):
        from copy import deepcopy
        from history_model import build_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            sample = make_sample(self.decoded, "00000000", "2026-11-23T02:00:00Z",
                                 Path(tmp) / "alias.key")
            sample["records"] = [
                dict(kind=kind, storage=0, tariff=0, subunit=0, function=0, value=value, unit=unit)
                for kind, value, unit in (("flow_temperature", 37.5, "C"),
                                           ("return_temperature", 36.4, "C"),
                                           ("temperature_difference", 1.1, "K"),
                                           ("energy", 12345, "kWh"))
            ]
            history = build_snapshot([{"month_back": n, "value": 1000 - 10*n, "unit": "kWh"}
                                      for n in range(1, 25)], "2026-11-23T02:00:00Z")
            original = deepcopy((sample, history))
            for language, label in (("en-GB", "Field"), ("nb-NO", "Felt"),
                                    ("nn-NO", "Felt"), ("de-DE", "Feld")):
                for target, expected, symbol in (("C", (37.5,36.4,1.1), "°C"),
                                                  ("K", (310.65,309.55,1.1), "K"),
                                                  ("F", (99.5,97.52,1.98), "°F")):
                    with self.subTest(language=language, target=target):
                        wb = load_workbook(BytesIO(make_xlsx([sample], history, language, target)),
                                           read_only=True, data_only=True)
                        self.assertEqual(wb["Info"]["A1"].value, label)
                        rows = list(wb["Normal records"].values)[1:]
                        for row, number in zip(rows, expected):
                            self.assertIsInstance(row[10], (float, int))
                            self.assertAlmostEqual(row[10], number)
                            self.assertEqual(row[11], symbol)
                        self.assertEqual(rows[3][10:12], (12345, "kWh"))
                        self.assertEqual(len(list(wb["Månedshistorikk"].values)), 25)
                        self.assertEqual(len(list(wb["Månedsforbruk"].values)), 24)
                        wb.close()
            self.assertEqual((sample, history), original)

    def test_no_unvalidated_or_incomplete_export(self):
        with self.assertRaises(ValueError):
            make_xlsx([])
        with self.assertRaises(ValueError):
            make_xlsx([], {"stands": [], "bounded_periods": []})


if __name__ == "__main__":
    unittest.main()

class DiagnosticExportTests(unittest.TestCase):
    def test_history_export_preserves_unknown_and_local_time(self):
        from history_model import build_snapshot
        snap = build_snapshot([{"month_back":n,"value":1000-10*n,"unit":"kWh"}
                               for n in range(1,25)], "2026-11-23T03:00:00Z")
        snap["error_history"] = {"read_at_utc":"2026-11-25T10:00:00+00:00",
                                 "last_occurrence_local":{"FT":"2026-11-22T19:03"}}
        wb = load_workbook(BytesIO(make_xlsx([], snap)), read_only=True, data_only=True)
        rows = list(wb["Error history"].values)
        self.assertEqual(rows[1][2:], ("FT", "2026-11-22T19:03", "not_inferred", "Last Negative Temperature Difference (FT)"))
        self.assertIsNone(rows[2][3])
        wb.close()
