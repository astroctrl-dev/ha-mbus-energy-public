import unittest
from active_diagnostics import active_projection, extension_projection


class ActiveDiagnosticsTests(unittest.TestCase):
    def test_faults_and_flow(self):
        p = active_projection(bytes.fromhex("3f 02 11"), layout_verified=True)
        self.assertTrue(p["active_meter_faults"])
        self.assertEqual(p["fault_messages"], ["F0 - Flow measurement error",
                         "F4 - Battery exhausted", "F9 - Internal communication error"])
        self.assertTrue(p["flow_warning"])
        self.assertTrue(all(p["flow_attributes"].values()))
        self.assertTrue(p["battery_prewarning"])
        self.assertTrue(p["battery_exhausted"])

    def test_clear_and_installation(self):
        p = active_projection(bytes.fromhex("80 00 00"), layout_verified=True)
        self.assertFalse(p["active_meter_faults"])
        self.assertFalse(p["flow_warning"])
        self.assertTrue(p["installation_in_flow"])

    def test_individual_warning_bits(self):
        for bit, key in ((0, "flow_prewarning"), (2, "wrong_sensor_installation"),
                         (3, "wrong_volume_installation"), (4, "negative_temperature_difference"),
                         (5, "negative_flow")):
            p = active_projection(bytes((1 << bit, 0, 0)), layout_verified=True)
            self.assertTrue(p["flow_warning"])
            self.assertTrue(p["flow_attributes"][key])
            self.assertFalse(p["active_meter_faults"])

    def test_gate(self):
        with self.assertRaises(ValueError):
            active_projection(bytes(3))

    def test_observed_extension(self):
        p = extension_projection("0x62")
        self.assertEqual(p["operating_mode"], "Nb")
        self.assertFalse(p["extension_byte_warning"])
        self.assertTrue(p["calibration_seal_bit"])
        self.assertFalse(p["installation_side_bit"])
        self.assertIsNone(p["installation_side"])
        self.assertTrue(p["rolling_frame_oss_bit"])
        self.assertFalse(p["rolling_frame_mss_bit"])

    def test_invalid_and_other_mode(self):
        for raw in (None, "0xGG", "0x123", "zz", "0x-1"):
            self.assertIsNone(extension_projection(raw)["extension_byte_warning"])
        self.assertTrue(extension_projection("0x00")["extension_byte_warning"])

    def test_installation_status(self):
        for raw, expected, side in (("80 00 00", "normal", "flow"),
                                    ("04 00 00", "warning", "return"),
                                    ("02 00 00", "normal", "return")):
            p = active_projection(bytes.fromhex(raw), layout_verified=True)
            self.assertEqual(p["meter_installation_status"], expected)
            self.assertEqual(p["installation_attributes"]["mounting_side"], side)
        for bit in (2, 3, 4, 5):
            p = active_projection(bytes((1 << bit, 0, 0)), layout_verified=True)
            self.assertEqual(p["meter_installation_status"], "warning")
