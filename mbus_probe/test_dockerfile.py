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
        # Frame-5 battery acquisition is deliberately not part of the runtime.
        # Keep this explicit exclusion until the feature is separately approved.
        excluded = {"battery_diagnostics.py"}
        self.assertTrue(excluded.isdisjoint(copied))
        for name in sorted(p.name for p in folder.glob("*.py")
                           if not p.name.startswith("test_") and p.name not in excluded):
            with self.subTest(module=name):
                self.assertIn(name, copied)
                self.assertTrue((folder / name).is_file())
