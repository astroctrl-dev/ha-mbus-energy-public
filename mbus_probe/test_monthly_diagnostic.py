import unittest
from pathlib import Path
from unittest.mock import patch
from monthly_diagnostic import select_frame_three, restore_normal_frame, extract_months, verify_normal_frame


class MonthlyDiagnosticTests(unittest.TestCase):
    def test_physical_frame_two_layout_sanitized(self):
        from monthly_diagnostic import extract_monthly_set_day
        from mbus_probe import validate
        # Preserve physical record layout, replace meter ID and unrelated values.
        records = bytes.fromhex(
            "d4 10 ad 6f 00 00 00 00 d4 10 bb 6f 00 00 00 00 "
            "d4 10 da 6f 00 00 00 00 d4 10 de 6f 00 00 00 00 "
            "44 6d 00 00 41 31 c4 8f 0f 6d 00 00 e1 ff "
            "c4 8f 4f 6d 00 00 ef ff 34 6d 00 00 41 31 "
            "34 fc 6e 02 54 46 00 00 00 00 34 fc 6e 02 53 46 00 00 00 00 "
            "34 fc 6e 02 45 46 00 00 00 00 34 fc 6e 03 31 46 46 00 00 00 00 "
            "34 fc 6e 03 32 46 46 00 00 00 00 0f 00 00 00 00 00")
        body = bytes.fromhex("08 00 72 00 00 00 00 a7 32 07 04 40 00 00 00") + records
        frame = bytes((0x68, len(body), len(body), 0x68)) + body + bytes((sum(body)&255, 0x16))
        self.assertEqual(extract_monthly_set_day(frame, 0, "00000000"),
                         {"day": 1, "hour": 0, "minute": 0})
        self.assertEqual(sum(r["kind"] == "vendor_diagnostic_opaque"
                             for r in validate(frame)["records"]), 5)
        with self.assertRaises(ValueError):
            extract_monthly_set_day(frame, 0, "12345678")
        with self.assertRaises(ValueError):
            extract_monthly_set_day(frame[:-2] + bytes((frame[-2]^1, 0x16)), 0, "00000000")
        from history_model import configured_anchor, configured_timestamp
        observation = {"monthly_set_day": extract_monthly_set_day(frame, 0, "00000000"),
                       "meter_local_time": "2026-11-25T03:51",
                       "last_successful_read_utc": "2026-11-25T02:51:21+00:00",
                       "meter_summer_time": False}
        anchor = configured_anchor(observation, "2026-11-25T02:49:19+00:00", "Europe/Oslo")
        self.assertEqual(configured_timestamp(anchor, 1), "2026-11-01T00:00")
        self.assertEqual(configured_timestamp(anchor, 24), "2024-12-01T00:00")

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
        self.assertEqual(len(values), 10)
        with self.assertRaises(ValueError):
            verify_normal_frame(normal, 1, "00000000")
        with self.assertRaises(ValueError):
            verify_normal_frame(normal, 0, "12345678")
        with self.assertRaises(ValueError):
            verify_normal_frame(normal[:-2] + bytes([normal[-2] ^ 1, normal[-1]]), 0, "00000000")

    def test_restore_rejects_partial_history_but_accepts_invalid_individual_value(self):
        from ha_measurements import REQUIRED_SENSORS, SENSORS
        sample = {"type": "long", "control": 8, "address": 0, "ci": 0x72,
                  "meter_id": "00000000", "manufacturer": "LUG", "medium_code": 4,
                  "status": 0, "records": [
                      {"kind": k, "current_record": True, "unit": SENSORS[k][0],
                       "value": None if k == "power" else 1}
                      for k in REQUIRED_SENSORS]}
        with patch("monthly_diagnostic.validate", return_value=sample):
            values = verify_normal_frame(b"synthetic", 0, "00000000")
            self.assertNotIn("power", values)
            sample["records"] = [r for r in sample["records"] if r["kind"] != "flow"]
            with self.assertRaisesRegex(ValueError, "missing required"):
                verify_normal_frame(b"synthetic", 0, "00000000")

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
