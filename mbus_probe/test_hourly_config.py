import json
import tempfile
import unittest
from pathlib import Path
from mbus_service import load_config


class HourlyConfigTests(unittest.TestCase):
    def load(self, **overrides):
        cfg = {"mqtt_host": "core-mosquitto",
               "serial_port": "/dev/ttyUSB0",
               "address": 0, "interval_seconds": 120}
        cfg.update(overrides)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "options.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            return load_config(path)

    def test_legacy_config_without_hourly_options(self):
        self.assertNotIn("read_before_full_hour", self.load())

    def test_enabled(self):
        self.assertTrue(self.load(read_before_full_hour=True,
                                  seconds_before_full_hour=5)["read_before_full_hour"])

    def test_offset_bounds(self):
        for offset in (0, 5, 300):
            self.assertEqual(self.load(seconds_before_full_hour=offset)
                             ["seconds_before_full_hour"], offset)

    def test_offset_rejects_invalid_values(self):
        for offset in (-1, 301, True, "5", 1.5):
            with self.assertRaisesRegex(ValueError, "seconds_before_full_hour"):
                self.load(seconds_before_full_hour=offset)

    def test_enabled_requires_boolean(self):
        for value in (1, "true", None):
            with self.assertRaisesRegex(ValueError, "read_before_full_hour"):
                self.load(read_before_full_hour=value)

    def test_obsolete_meter_options_cannot_select_instrument(self):
        config = self.load(address=251, meter_id="01234567", use_daylight_saving_time=True)
        for key in ("address", "meter_id", "use_daylight_saving_time"):
            self.assertNotIn(key, config)
