import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch
from meter_discovery import scan_bus


class ScanRestoreGuardTests(unittest.TestCase):
    def test_scan_does_not_transmit_with_unverified_normal_frame(self):
        registry = SimpleNamespace(lock=threading.Lock(), scan_status="running")
        blocked = threading.Event()
        blocked.set()
        with patch("meter_discovery.read_one") as read:
            scan_bus("fake", 2400, registry, threading.Lock(), threading.Event(), blocked)
            read.assert_not_called()
        self.assertEqual(registry.scan_status, "failed")
