"""Regression: the HAOS image must include all local runtime modules."""
import unittest
from pathlib import Path


class DockerfileTests(unittest.TestCase):
    def test_runtime_modules_are_copied(self):
        folder = Path(__file__).parent
        dockerfile = (folder / "Dockerfile").read_text(encoding="utf-8")
        copy_line = next(line for line in dockerfile.splitlines()
                         if line.startswith("COPY ") and " /opt/" in line)
        copied = set(copy_line.split()[1:-1])
        for name in ("mbus_probe.py", "mbus_records.py", "ha_measurements.py",
                     "mqtt_bridge.py", "mbus_service.py", "poll_schedule.py",
                     "meter_registry.py", "meter_discovery.py", "meter_ui.py",
                     "monthly_diagnostic.py"):
            with self.subTest(module=name):
                self.assertIn(name, copied)
                self.assertTrue((folder / name).is_file())
