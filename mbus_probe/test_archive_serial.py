import unittest
from unittest.mock import patch, MagicMock
from archive_serial import read_archive

class ArchiveSerialTests(unittest.TestCase):
    def test_requires_shared_gate(self):
        with patch("archive_serial.shared_timing_active",return_value=False):
            with self.assertRaises(ValueError):
                read_archive({},"unused",2400,1,"00000000",1,approved=True)
    def test_requires_approval(self):
        with patch("archive_serial.shared_timing_active",return_value=True):
            with self.assertRaises(ValueError):
                read_archive({},"unused",2400,1,"00000000",1)
