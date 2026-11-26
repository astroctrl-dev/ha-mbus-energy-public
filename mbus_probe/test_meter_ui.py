import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from meter_registry import MeterRegistry
from meter_ui import serve, render_page
from i18n import LANGUAGES
from ui_translations import TRANSLATIONS, STATUS_TEXT


class IngressBoundaryTests(unittest.TestCase):
    def test_direct_container_request_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = MeterRegistry(Path(directory) / "meters.json")
            server = serve(registry, {"serial_port": "/dev/ttyUSB0"}, None,
                           threading.Lock(), threading.Event(), port=0)
            try:
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(f"http://127.0.0.1:{server.server_port}/api/meters")
                self.assertEqual(ctx.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()

class PresentationTests(unittest.TestCase):
    def test_catalogue_complete_and_routes_preserved(self):
        for translations in TRANSLATIONS.values():
            self.assertEqual(set(translations), set(LANGUAGES))
            self.assertTrue(all(translations.values()))
        for language, title in (("en-GB", "M-Bus energy meters"), ("nb-NO", "M-Bus energimålere"),
                                ("nn-NO", "M-Bus-energimålarar"), ("de-DE", "M-Bus-Energiezähler")):
            page = render_page(language)
            self.assertIn('<html lang="' + language + '">', page)
            self.assertIn("<h1>" + title + "</h1>", page)
            for route in ("/api/meters", "/api/history", "/api/clock", "/api/scan",
                          "/api/select", "/api/remove", "/api/auto", "/api/export.xlsx"):
                self.assertIn("'" + route + "'", page)
            self.assertIn("confirm:true", page)
            self.assertIn("state.history.status === 'running'", page)

    def test_history_controls_and_section_order(self):
        page = render_page("en-GB")
        self.assertIn("'/api/stop_history'", page)
        self.assertIn('"/api/ack_history"', page)
        self.assertIn("state.history.manual_meter === item.meter_id", page)
        self.assertIn("details.dataset.meter = entry.alias", page)
        self.assertLess(page.index('id="available"'), page.index('id="selected"'))
        self.assertLess(page.index('id="selected"'), page.index('id="clock-status"'))
        self.assertLess(page.index('id="clock-status"'), page.index('id="history"'))
        self.assertLess(page.index('id="history"'), page.index('id="raw-status"'))

    def test_dynamic_translation_does_not_change_control_status(self):
        for translations in STATUS_TEXT.values():
            self.assertEqual(set(translations), set(LANGUAGES))
        for language in LANGUAGES:
            page = render_page(language)
            self.assertIn("localText(state.scan_status)", page)
            self.assertIn("localText(state.history.status)", page)
            self.assertIn("localText(state.clock.status)", page)
            self.assertIn("state.scan_status === 'running'", page)
            self.assertIn("state.history.captured_at_utc !== lastHistoryCapture", page)

    def test_configuration_translation_keys_match_schema(self):
        from pathlib import Path
        import re
        root = Path(__file__).parent
        schema = (root / "config.yaml").read_text(encoding="utf-8").split("schema:\n", 1)[1]
        expected = set(re.findall(r"^  ([a-z_]+):", schema, re.M))
        for language in ("en", "nb", "nn", "de"):
            source = (root / "translations" / (language + ".yaml")).read_text(encoding="utf-8")
            self.assertEqual(set(re.findall(r"^  ([a-z_]+):", source, re.M)), expected)
            self.assertEqual(source.count("    name:"), len(expected))
            self.assertEqual(source.count("    description:"), len(expected))

    def test_independent_ingress_and_export_use_english(self):
        import inspect
        source = inspect.getsource(serve)
        self.assertIn('render_page("en-GB")', source)
        self.assertIn('language="en-GB"', source)
        self.assertNotIn("Accept-Language", source)
        self.assertIn('M-Bus energy meters', render_page("en-GB"))

    def test_active_diagnostic_battery_display(self):
        page = render_page("en-GB")
        for state in ("normal", "pre-warning", "exhausted", "unknown"):
            self.assertIn(".battery-" + state, page)
        self.assertIn("Battery Status:", page)
        self.assertIn("renderActiveDiagnostics", page)
        self.assertIn("Last verified diagnostics:", page)
        self.assertIn("item.textContent = message", page)

    def test_capture_controls_are_opt_in(self):
        page = render_page("en-GB")
        self.assertIn("state.diagnostic_capture_enabled", page)
        self.assertIn("Capture frame 5 (test)", page)
        self.assertIn("'/api/diagnostic_capture'", page)
        self.assertIn("Show capture evidence", page)

    def test_capture_status_and_installation_display(self):
        page = render_page("en-GB")
        for text in ("Diagnostic capture:", "Meter Installation Status:",
                     "captureEvidenceVisible", "state.diagnostic_capture_status"):
            self.assertIn(text, page)
        self.assertIn("line.append(capture, status, evidence, output)", page)
