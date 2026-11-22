import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from meter_discovery import scan_bus
from meter_registry import MeterRegistry
from mbus_probe import validate


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "meters.json"
        self.registry = MeterRegistry(self.path)

    def _scan(self, identities):
        fixture = Path(__file__).with_name("fixture_t230_sanitized.hex")
        template = validate(bytes.fromhex(fixture.read_text()))
        def read(_port, _baud, address, timeout, first_byte_timeout):
            return b"request", b"frame" if address in identities else b""

        def decode(_frame):
            # Associate a distinct frame with its address via read_one mock below.
            return self.current

        def read_with_identity(*args, **kwargs):
            result = read(*args, **kwargs)
            address = args[2]
            if result[1]:
                self.current = {**template, "type": "long", "control": 8, "ci": 0x72,
                                "address": address, "meter_id": identities[address],
                                "manufacturer": "LUG", "medium_code": 4}
            return result

        # The scan is sequential, matching a single physical bus.
        with patch("meter_discovery.read_one", side_effect=read_with_identity), \
             patch("meter_discovery.validate", side_effect=decode):
            scan_bus("/dev/ttyUSB0", 2400, self.registry,
                     threading.Lock(), threading.Event())

    def test_three_meters_are_added_one_at_a_time(self):
        self._scan({0: "12345678", 1: "23456789", 2: "34567890"})
        self.assertEqual(len(self.registry.snapshot()["available"]), 3)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.registry.select_auto()
        self.registry.select("12345678")
        self.assertEqual(len(self.registry.snapshot()["available"]), 2)
        with self.assertRaisesRegex(ValueError, "already selected"):
            self.registry.select("12345678")
        self.registry.select("23456789")
        self.assertEqual(self.registry.select_auto(), "34567890")
        self.assertEqual(len(self.registry.snapshot()["selected"]), 3)
        self.assertEqual(len(self.registry.snapshot()["available"]), 0)
        self.assertEqual(len(MeterRegistry(self.path).snapshot()["selected"]), 3)
        self.registry.remove("23456789")
        self.assertEqual(self.registry.snapshot()["available"], [])
        with self.assertRaisesRegex(ValueError, "cleanup still pending"):
            self.registry.select("23456789")
        self.registry.cleanup_done("23456789")
        self.assertEqual(self.registry.snapshot()["available"][0]["meter_id"], "23456789")
        self.registry.select("23456789")

    def test_no_implicit_auto_on_ambiguous_scan(self):
        self._scan({0: "12345678", 2: "12345678"})
        self.assertEqual(self.registry.snapshot()["scan_status"], "failed")
        self.assertEqual(self.registry.snapshot()["selected"], [])
        with self.assertRaises(ValueError):
            self.registry.select_auto()

    def test_discovery_is_visible_during_scan_and_can_be_stopped(self):
        fixture = Path(__file__).with_name("fixture_t230_sanitized.hex")
        template = validate(bytes.fromhex(fixture.read_text()))
        captured = []

        def read(_port, _baud, address, timeout, first_byte_timeout):
            if address == 7:
                return b"request", b"frame"
            if address == 8:
                captured.append(self.registry.snapshot())
                self.registry.scan_stop.set()
            return b"request", b""

        with patch("meter_discovery.read_one", side_effect=read), \
             patch("meter_discovery.validate", return_value={
                 **template, "type": "long", "control": 8, "address": 7,
                 "meter_id": "12345678", "manufacturer": "LUG", "medium_code": 4}):
            scan_bus("/dev/ttyUSB0", 2400, self.registry,
                     threading.Lock(), threading.Event())
        self.assertEqual(captured[0]["available"][0]["meter_id"], "12345678")
        self.assertEqual(self.registry.snapshot()["scan_status"], "stopped")
        self.registry.select("12345678")
        self.assertEqual(self.registry.snapshot()["selected"][0]["address"], 7)

    def test_only_discovered_and_supported_can_be_selected(self):
        with self.assertRaisesRegex(ValueError, "discovered supported"):
            self.registry.select("12345678")
        self.registry.set_found([{"meter_id": "12345678", "address": 0,
                                  "supported": False}])
        with self.assertRaises(ValueError):
            self.registry.select("12345678")

    def test_scan_never_broadcasts_or_writes(self):
        addresses = []
        def read(_port, _baud, address, **_kwargs):
            addresses.append(address)
            return b"", b""
        with patch("meter_discovery.read_one", side_effect=read):
            scan_bus("/dev/ttyUSB0", 2400, self.registry,
                     threading.Lock(), threading.Event())
        self.assertEqual(addresses, list(range(251)))

    def test_failed_persistence_does_not_change_live_selection(self):
        self.registry.set_found([{"meter_id": "12345678", "address": 0,
                                  "supported": True}])
        with patch.object(self.registry, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.registry.select("12345678")
        self.assertEqual(self.registry.selected, {})
        self.registry.select("12345678")
        with patch.object(self.registry, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.registry.remove("12345678")
        self.assertEqual(self.registry.selected, {"12345678": 0})
        self.assertEqual(self.registry.pending_cleanup, [])
