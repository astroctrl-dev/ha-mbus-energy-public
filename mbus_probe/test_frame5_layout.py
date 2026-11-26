import unittest
from pathlib import Path
from frame5_layout import extract_abcdef, SEPARATORS
from active_diagnostics import active_projection

class Frame5LayoutTests(unittest.TestCase):
    def setUp(self):
        self.frame = bytes.fromhex(Path(__file__).with_name("fixture_t230_frame5_sanitized.hex").read_text())

    def changed(self, index, value):
        frame = bytearray(self.frame)
        frame[index] = value
        frame[-2] = sum(frame[4:-2]) & 255
        return bytes(frame)

    def test_synthetic_layout(self):
        raw = extract_abcdef(self.frame, 0, "00000000")
        self.assertEqual(raw, bytes.fromhex("04 00 00"))
        p = active_projection(raw, layout_verified=True)
        self.assertFalse(p["battery_prewarning"])
        self.assertFalse(p["battery_exhausted"])
        self.assertFalse(p["active_meter_faults"])
        self.assertEqual(p["meter_installation_status"], "warning")
        self.assertTrue(p["installation_attributes"]["wrong_sensor_installation"])

    def test_identity_and_checksum(self):
        for address, identity in ((1, "00000000"), (0, "12345678")):
            with self.assertRaises(ValueError):
                extract_abcdef(self.frame, address, identity)
        bad = bytearray(self.frame)
        bad[74] ^= 1
        with self.assertRaises(ValueError):
            extract_abcdef(bytes(bad), 0, "00000000")

    def test_wrong_layout(self):
        for index in (*SEPARATORS, 13, 19, 167, 168, 169, 171, 172, 173):
            with self.subTest(index=index), self.assertRaises(ValueError):
                extract_abcdef(self.changed(index, self.frame[index] ^ 1), 0, "00000000")
        with self.assertRaises(ValueError):
            extract_abcdef(self.frame[:-1], 0, "00000000")
        normal = bytes.fromhex(Path(__file__).with_name("fixture_t230_sanitized.hex").read_text())
        with self.assertRaises(ValueError):
            extract_abcdef(normal, 0, "00000000")

    def test_variable_flags_and_header_status(self):
        frame = self.changed(74, 0x82)
        self.assertEqual(extract_abcdef(frame, 0, "00000000"), bytes.fromhex("82 00 00"))
        self.assertEqual(extract_abcdef(self.changed(16, 0x10), 0, "00000000"), bytes.fromhex("04 00 00"))

    def test_private_physical_capture_if_available(self):
        path = Path(__file__).resolve().parent.parent / "docs/private-fixtures/t230-frame5-physical-header-redacted.hex"
        if not path.exists():
            self.skipTest("private physical evidence not distributed")
        self.assertEqual(extract_abcdef(bytes.fromhex(path.read_text()), 0, "00000000"), bytes.fromhex("04 00 00"))
