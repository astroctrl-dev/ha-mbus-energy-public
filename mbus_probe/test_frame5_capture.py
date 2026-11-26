import unittest
from pathlib import Path
from frame5_capture import collect_capture, select_frame5, CaptureError
from monthly_diagnostic import RestorationError, restore_normal_frame
from mbus_probe import request, validate


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.normal = bytes.fromhex(Path(__file__).with_name("fixture_t230_sanitized.hex").read_text())
        self.address = validate(self.normal)["address"]
        self.calls = []

    def exchange(self, responses):
        replies = iter(responses)
        def run(tx):
            self.calls.append(tx)
            return next(replies)
        return run

    def test_capture_never_claims_layout(self):
        a = self.address
        result = collect_capture(a, "00000000",
            self.exchange([b"\xe5", self.normal, b"\xe5", self.normal]), approved=True)
        self.assertFalse(result["layout_verified"])
        self.assertTrue(result["normal_layout_detected"])
        self.assertEqual(self.calls, [select_frame5(a), request(a), restore_normal_frame(a), request(a)])

    def test_failure_restores(self):
        with self.assertRaises(CaptureError):
            collect_capture(self.address, "00000000", self.exchange([b"", b"\xe5", self.normal]), approved=True)
        self.assertEqual(self.calls[-1], request(self.address))

    def test_restore_failure(self):
        with self.assertRaises(RestorationError):
            collect_capture(self.address, "00000000", self.exchange([b"\xe5", self.normal, b"", b"", b""]), approved=True)

    def test_no_approval_no_bus(self):
        with self.assertRaises(ValueError):
            collect_capture(self.address, "00000000", self.exchange([]))
        self.assertEqual(self.calls, [])

    def test_redacted_evidence_checksum(self):
        from frame5_capture import redact_capture
        frame = bytearray(self.normal)
        frame[7:11] = bytes.fromhex("78 56 34 12")
        frame[-2] = sum(frame[4:-2]) & 255
        result = redact_capture({"response_hex":frame.hex(),"read_at_utc":"2026-11-26T00:00:00Z"})
        safe = bytes.fromhex(result["response_hex"])
        self.assertEqual(validate(safe)["meter_id"], "00000000")
        self.assertEqual(safe[19:-2], frame[19:-2])
        self.assertFalse(result["layout_verified"])
