"""Fresh installation defaults are intentionally opt-in."""
import unittest
from pathlib import Path


class FirstInstallDefaultsTests(unittest.TestCase):
    def test_all_optional_boolean_defaults_off(self):
        text = Path(__file__).with_name("config.yaml").read_text()
        options = text.split("options:\n", 1)[1].split("schema:\n", 1)[0]
        schema = text.split("schema:\n", 1)[1]
        for line in schema.splitlines():
            if line.endswith(": bool"):
                key = line.strip().split(":")[0]
                expected = "true" if key == "use_daylight_saving_time" else "false"
                self.assertIn("  " + key + ": " + expected, options.splitlines())
