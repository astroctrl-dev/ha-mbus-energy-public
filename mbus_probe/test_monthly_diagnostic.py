import unittest
from pathlib import Path
from unittest.mock import patch
from monthly_diagnostic import select_frame_three, restore_normal_frame, extract_months, verify_normal_frame


class MonthlyDiagnosticTests(unittest.TestCase):
    def test_documented_selection_and_restore_frames(self):
        self.assertEqual(select_frame_three(0), bytes.fromhex("68 04 04 68 53 00 50 03 a6 16"))
        self.assertEqual(restore_normal_frame(0), bytes.fromhex("68 03 03 68 53 00 50 a3 16"))

    def test_requires_all_24_unique_monthly_energy_records(self):
        sample = {
            "type": "long", "ci": 0x72, "meter_id": "12345678",
            "manufacturer": "LUG", "medium_code": 4, "status": 0,
            "records": [
                {"kind": "energy", "storage": n, "tariff": 0, "function": 0,
                 "unit": "kWh", "value": 1000.0 + n}
                for n in range(2, 26)
            ],
        }
        with patch("monthly_diagnostic.validate", return_value=sample):
            result = extract_months(b"synthetic", "12345678")
            self.assertEqual(len(result), 24)
            self.assertEqual(result[0]["month_back"], 1)
            sample["records"].pop()
            with self.assertRaisesRegex(ValueError, "exactly 24"):
                extract_months(b"synthetic", "12345678")

    def test_known_status_10_keeps_months_available(self):
        sample = {"type": "long", "ci": 0x72, "meter_id": "12345678",
                  "manufacturer": "LUG", "medium_code": 4, "status": 0x10,
                  "records": [{"kind": "energy", "storage": n, "tariff": 0,
                               "function": 0, "unit": "kWh", "value": float(n)}
                              for n in range(2, 26)]}
        with patch("monthly_diagnostic.validate", return_value=sample):
            self.assertEqual(len(extract_months(b"synthetic", "12345678")), 24)
            sample["status"] = 1
            with self.assertRaisesRegex(ValueError, "status"):
                extract_months(b"synthetic", "12345678")

    def test_restore_requires_valid_normal_read(self):
        fixture = Path(__file__).with_name("fixture_t230_sanitized.hex")
        normal = bytes.fromhex(fixture.read_text())
        values = verify_normal_frame(normal, 0, "00000000")
        self.assertEqual(len(values), 7)
        with self.assertRaises(ValueError):
            verify_normal_frame(normal, 1, "00000000")
        with self.assertRaises(ValueError):
            verify_normal_frame(normal, 0, "12345678")
        with self.assertRaises(ValueError):
            verify_normal_frame(normal[:-2] + bytes([normal[-2] ^ 1, normal[-1]]), 0, "00000000")

    def test_secondary_subunit_cannot_replace_monthly_stand(self):
        sample = {"type": "long", "ci": 0x72, "meter_id": "12345678",
                  "manufacturer": "LUG", "medium_code": 4, "status": 0,
                  "records": [{"kind": "energy", "storage": n, "tariff": 0,
                               "subunit": 0, "function": 0, "unit": "kWh",
                               "value": float(n)} for n in range(2, 26)]}
        with patch("monthly_diagnostic.validate", return_value=sample):
            self.assertEqual(len(extract_months(b"synthetic", "12345678")), 24)
            sample["records"][0]["subunit"] = 1
            with self.assertRaisesRegex(ValueError, "exactly 24"):
                extract_months(b"synthetic", "12345678")

    def test_rejects_wrong_meter_and_tariff(self):
        sample = {
            "type": "long", "ci": 0x72, "meter_id": "12345678",
            "manufacturer": "LUG", "medium_code": 4, "status": 0,
            "records": [{"kind": "energy", "storage": n, "tariff": 0,
                         "function": 0, "unit": "kWh", "value": float(n)}
                        for n in range(2, 26)],
        }
        with patch("monthly_diagnostic.validate", return_value=sample):
            with self.assertRaisesRegex(ValueError, "identity"):
                extract_months(b"synthetic", "87654321")
            sample["records"][0]["tariff"] = 5
            with self.assertRaisesRegex(ValueError, "exactly 24"):
                extract_months(b"synthetic", "12345678")


if __name__ == "__main__":
    unittest.main()
