import unittest
from pathlib import Path
from mbus_probe import validate
from ha_measurements import select_measurements


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).with_name("fixture_t230_sanitized.hex")
        cls.decoded = validate(bytes.fromhex(path.read_text()))

    def test_only_current_measurements(self):
        values = select_measurements(self.decoded, "00000000")
        self.assertEqual(values, {
            "energy": 12345.0, "volume": 123.45, "power": 1.2,
            "flow": 0.125, "flow_temperature": 45.6,
            "return_temperature": 32.1, "temperature_difference": 13.5,
            "operating_time": 240.0, "flow_time": 120.0,
            "missing_time": 100.0,
        })

    def test_negative_current_power_is_valid_but_counters_stay_nonnegative(self):
        base = self.decoded["records"]
        power = next(r for r in base if r.get("kind") == "power" and r.get("current_record"))
        energy = next(r for r in base if r.get("kind") == "energy" and r.get("current_record"))
        negative_power = [({**r, "value": -0.2} if r is power else r) for r in base]
        values = select_measurements({**self.decoded, "records": negative_power}, "00000000")
        self.assertEqual(values["power"], -0.2)
        self.assertEqual(values["energy"], 12345.0)
        for bad in (-1, float("nan"), float("inf")):
            records = [({**r, "value": bad} if r is energy else r) for r in base]
            with self.subTest(bad=bad):
                selected = select_measurements({**self.decoded, "records": records}, "00000000")
                self.assertNotIn("energy", selected)
                self.assertEqual(selected["power"], 1.2)
        for bad in (float("nan"), float("-inf")):
            records = [({**r, "value": bad} if r is power else r) for r in base]
            with self.subTest(bad=bad):
                selected = select_measurements({**self.decoded, "records": records}, "00000000")
                self.assertNotIn("power", selected)
                self.assertEqual(selected["energy"], 12345)

    def test_checksum_valid_sanitized_frame_with_negative_bcd_power(self):
        path = Path(__file__).with_name("fixture_t230_sanitized.hex")
        frame = bytearray(bytes.fromhex(path.read_text()))
        power = next(r for r in self.decoded["records"]
                     if r.get("kind") == "power" and r.get("current_record"))
        self.assertEqual((power["dif"], power["vif"]), (0x0b, 0x2d))
        start = 19 + power["offset"] + 2  # Long frame header + DIF/VIF.
        frame[start:start + 3] = bytes((0x02, 0x00, 0xf0))  # Signed BCD -2 => -0.2 kW.
        frame[-2] = sum(frame[4:-2]) & 255
        decoded = validate(bytes(frame))
        values = select_measurements(decoded, "00000000")
        self.assertEqual(values["power"], -0.2)
        self.assertEqual(values["energy"], 12345.0)

    def test_temperature_difference_is_signed_and_finite(self):
        for value in (-100.0, -13.5, -0.1, 0.0, 0.1, 13.5, 100.0, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                records = [{**r, "value": value} if r.get("kind") == "temperature_difference"
                           and r.get("current_record") else r for r in self.decoded["records"]]
                selected = select_measurements({**self.decoded, "records": records}, "00000000")
                if abs(value) <= 100:
                    self.assertEqual(selected["temperature_difference"], value)
                else:
                    self.assertNotIn("temperature_difference", selected)
                self.assertEqual(selected["energy"], 12345.0)

    def test_missing_hours_are_error_duration_not_operating_time(self):
        missing = [r for r in self.decoded["records"] if r.get("kind") == "missing_time"]
        self.assertEqual(len(missing), 2)  # Current error duration and last year's value.
        self.assertEqual([r["storage"] for r in missing], [0, 1])
        self.assertEqual(select_measurements(self.decoded, "00000000")["missing_time"], 100)

    def test_identity_and_status_fail_closed(self):
        for change in ({"meter_id": "12345678"}, {"status": 1},
                       {"manufacturer": "ABC"}, {"medium_code": 3}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                select_measurements({**self.decoded, **change}, "00000000")

    def test_rejection_reason_is_specific_and_does_not_leak_meter_id(self):
        cases = (
            ({"type": "short"}, "frame_type"),
            ({"control": 0}, "control"),
            ({"ci": 0}, "ci"),
            ({"manufacturer": "ABC"}, "manufacturer"),
            ({"meter_id": "12345678"}, "meter_id"),
            ({"medium_code": 3}, "medium"),
            ({"status": 1}, "status=0x01"),
            ({"status": None}, "status"),
        )
        for change, reason in cases:
            with self.subTest(change=change), self.assertRaisesRegex(
                    ValueError, "invalid T230 " + reason) as ctx:
                select_measurements({**self.decoded, **change}, "00000000")
            self.assertNotIn("12345678", str(ctx.exception))
            self.assertNotIn("00000000", str(ctx.exception))

    def test_status_transition_zero_to_temporary_error_and_back(self):
        # EN 13757-3: bit 4 signals a temporary meter error, not a toggle.
        valid = {**self.decoded, "status": 0}
        temporary_error = {**self.decoded, "status": 0x10}
        self.assertEqual(len(select_measurements(valid, "00000000")), 10)
        self.assertEqual(len(select_measurements(temporary_error, "00000000")), 10)
        self.assertEqual(len(select_measurements(valid, "00000000")), 10)

    def test_other_status_bits_still_rejected(self):
        for status in (0x01, 0x02, 0x20, 0x11, None):
            with self.subTest(status=status), self.assertRaises(ValueError):
                select_measurements({**self.decoded, "status": status}, "00000000")

    def test_temporary_error_still_requires_valid_identity(self):
        with self.assertRaisesRegex(ValueError, "invalid T230 meter_id"):
            select_measurements({**self.decoded, "status": 0x10,
                                 "meter_id": "12345678"}, "00000000")

    def test_unknown_and_invalid_never_exposed(self):
        decoded = {**self.decoded, "records": self.decoded["records"] + [
            {"kind": "unknown_vif", "current_record": True, "value": 999},
            {"kind": "invalid_bcd", "current_record": True, "value": 999},
        ]}
        self.assertEqual(select_measurements(decoded, "00000000")["energy"], 12345)

    def test_duplicate_current_energy_rejected(self):
        records = self.decoded["records"]
        selected = select_measurements({**self.decoded, "records": records + [records[2]]},
                                       "00000000")
        self.assertNotIn("energy", selected)
        self.assertIn("power", selected)

    def test_missing_current_flow_rejected(self):
        records = [record for record in self.decoded["records"]
                   if record.get("offset") != 23]
        selected = select_measurements({**self.decoded, "records": records}, "00000000")
        self.assertNotIn("flow", selected)
        self.assertIn("energy", selected)

    
class PollIntervalConfigTests(unittest.TestCase):
    def test_allowed_intervals_and_rejection(self):
        import json
        import tempfile
        from mbus_service import load_config
        baseline = {"mqtt_host": "core-mosquitto", "serial_port": "/dev/ttyUSB0"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "options.json"
            for interval in (60, 90, 120, 300, 600):
                path.write_text(json.dumps({**baseline, "interval_seconds": interval}))
                self.assertEqual(load_config(str(path))["interval_seconds"], interval)
            for interval in (0, 5, 10, 20, 30, 59, 61, 301, 601, -1):
                path.write_text(json.dumps({**baseline, "interval_seconds": interval}))
                with self.subTest(interval=interval), self.assertRaises(ValueError):
                    load_config(str(path))
            path.write_text(json.dumps(baseline))
            self.assertEqual(load_config(str(path)).get("interval_seconds", 120), 120)
