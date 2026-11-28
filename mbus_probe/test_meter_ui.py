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
                          "/api/select", "/api/remove", "/api/export.xlsx"):
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

    def test_removed_controls_absent_from_rendered_page(self):
        import inspect
        for language in LANGUAGES:
            page = render_page(language)
            for marker in ('id="auto"', "getElementById('auto')",
                           "Select meter automatically", "Capture frame 5 (test)",
                           "Show capture evidence", "Diagnostic capture:",
                           "Migration completed (24/24 + 23/23)", "captureEvidenceVisible",
                           'id="diagnostic-evidence"'):
                self.assertNotIn(marker, page)
            self.assertIn('id="scan"', page)
            self.assertIn("'/api/select'", page)
            self.assertIn('if (migration === "pending")', page)
            self.assertIn("Meter Installation Status:", page)
            self.assertIn("'/api/migrate'", page.replace('"/api/migrate"', "'/api/migrate'"))
        # UI removal must not remove the existing guarded backend operations.
        source=inspect.getsource(serve)
        self.assertIn('route == "auto"', source)
        self.assertIn('route == "diagnostic_capture"', source)

    def test_compact_diagnostics_and_history_js(self):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("Node required")
        page=render_page("en-GB")
        js=page[page.index("function displayTimestamp"):page.index("function addCell")]
        js+=page[page.index("function renderActiveDiagnostics"):page.index("async function refreshAddressStatus")]
        prelude=r"""
const assert=require('node:assert/strict');
class Element {
  constructor(){this.children=[];this.textContent='';}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(){}
}
const document={createElement:()=>new Element(),createTextNode:s=>s};
const diagnosticOpen=new Map();
"""
        checks=r"""
assert.equal(displayTimestamp('2026-11-27T02:17:30.918239+00:00'),'2026-11-27 02:17:30 UTC');
assert.equal(displayTimestamp('2026-11-27T23:50+01:00'),'2026-11-27 23:50 +01:00');
assert.equal(displayTimestamp('2026-11-22T19:03'),'2026-11-22 19:03');
assert.equal(displayTimestamp(null),'—');
const data={flow_attributes:{wrong_sensor_installation:true,negative_flow:false},installation_attributes:{wrong_sensor_installation:true,negative_flow:null,mounting_side:'return'},read_at_utc:'2026-11-27T02:17:30.918239+00:00'};
const section=renderActiveDiagnostics(data,'meter-a');
const details=section.children.find(x=>x.className==='diagnostic-details');
assert.equal(details.open,false);
assert.equal(details.children.filter(x=>x.textContent.startsWith('wrong sensor installation:')).length,1);
assert.match(details.children.find(x=>x.textContent.startsWith('negative flow:')).textContent,/Flow: Inactive; Installation: Unknown/);
assert.ok(section.children.some(x=>x.className==='diagnostic-warning'&&x.textContent.includes('wrong sensor installation')));
details.open=true;details.ontoggle();
assert.equal(renderActiveDiagnostics(data,'meter-a').children.find(x=>x.className==='diagnostic-details').open,true);
assert.equal(renderActiveDiagnostics(data,'meter-b').children.find(x=>x.className==='diagnostic-details').open,false);
"""
        result=subprocess.run(["node","-"],input=prelude+js+checks,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("Usage (kWh)",page)
        self.assertIn("Reading (kWh)",page)
        self.assertIn('class="help-details"',page)
        self.assertIn('errorDetails.dataset.errorMeter=entry.alias',page)
        self.assertNotIn('migrated.className="migration-status"',page)
        self.assertIn('admin.className="meter-admin"',page)


    def test_experimental_green_accept_and_yellow_block(self):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("Node required")
        page=render_page("en-GB")
        js=page[page.index("const addressFormat ="):page.index("function renderAddressJob")]
        js+=page[page.index("function validAddressInput"):page.index("function updateFastWarning")]
        js+=page[page.index("document.getElementById('address-check').onclick="):page.index("document.getElementById('address-search').onclick=")]
        prelude=r"""
const assert=require('node:assert/strict');
const elements=new Map();
const document={getElementById(id){if(!elements.has(id)) elements.set(id,{value:'2',style:{},checkValidity:()=>true});return elements.get(id);}};
let addressMeter='01234567',addressOld=1,addressChangeEnabled=true,addressChangeBusy=false;
let quarantineRows=[],quarantineRecoveryPending=false,testRequestPending=false;
let addressJob={meter_id:addressMeter,search_id:'test',total:1,status:'completed',results:[{address:2,status:'no_response',observations:['no_response','no_response']}]};
const testPhase=()=> 'off';
const confirm=()=>true;
const calls=[];
const call=async(route,body)=>{calls.push({route,body});return {status:'running'};};
const refresh=async()=>{};
const renderAddressChange=()=>{};
const syncRisk=()=>{};
const addressAction=()=>{throw Error('unexpected search');};
"""
        checks=r"""
(async()=>{
requestEvidenceId='test';requestTarget=2;
syncAddressRequest();
const action=document.getElementById('address-check');
assert.equal(action.textContent,'Accept new address');
assert.equal(action.disabled,false);
addressJob.results[0]={address:2,status:'occupied',observations:['occupied']};
syncAddressRequest();
assert.equal(action.disabled,true);
await action.onclick();
assert.equal(calls.length,0);
addressJob.results[0]={address:2,status:'no_response',observations:['no_response','no_response']};
syncAddressRequest();
await action.onclick();
assert.equal(calls.length,1);
assert.equal(calls[0].route,'/api/address_change');
assert.deepEqual(calls[0].body,{meter_id:'01234567',old_address:1,new_address:2,confirm:true,override:false,accepted_risk:null});
await action.onclick();
assert.equal(calls.length,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result=subprocess.run(["node","-"],input=prelude+js+checks,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


    def test_address_recovery_precedes_startup_verification_only(self):
        from types import SimpleNamespace
        from meter_ui import address_recovery_history_blocked
        with tempfile.TemporaryDirectory() as root:
            marker=Path(root)/"restore.json"
            history=SimpleNamespace(marker=marker,blocked=threading.Event(),startup_pending=True)
            history.blocked.set()
            self.assertFalse(address_recovery_history_blocked(history))
            marker.touch()
            self.assertTrue(address_recovery_history_blocked(history))
            marker.unlink()
            history.startup_pending=False
            self.assertTrue(address_recovery_history_blocked(history))
            history.blocked.clear()
            self.assertFalse(address_recovery_history_blocked(history))
