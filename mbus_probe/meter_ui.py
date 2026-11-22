"""Small ingress-only UI for selecting discovered meters. No direct host port."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from meter_discovery import scan_bus


PAGE = r"""<!doctype html><html lang="no"><meta charset="utf-8"><title>M-Bus T230 – målere</title>
<h1>M-Bus T230 – målere</h1><p>Søk på M-Bus-adressene 0–250. Funn vises med ID og adresse etter hvert. Du kan stoppe når du har funnet måleren du trenger. Målere med samme adresse kan gi tvetydige svar.</p>
<button id="scan">Søk etter målere</button><button id="stop">Stopp søk</button><button id="auto">Velg eneste ledige automatisk</button>
<p id="status"></p><h2>Tilgjengelige målere</h2><div id="available"></div>
<h2>Etablerte målere</h2><div id="selected"></div><p id="error" role="alert"></p>
<script>
const root = location.pathname.replace(/\/$/, '');
const statusLabels = {not_started:'Ikke startet', running:'Søker', completed:'Fullført', stopped:'Stoppet', failed:'Feilet'};
const errorLabels = {'scan already running':'Et søk pågår allerede.', 'no scan is running':'Ingen søk pågår.', 'meter is not a discovered supported device':'Måleren må finnes i søket og være støttet.', 'automatic selection requires exactly one unassigned meter and a clean scan':'Automatisk valg krever nøyaktig én ledig måler og et fullført søk uten feil.', 'MQTT unavailable; cannot remove meter':'MQTT er utilgjengelig. Måleren kan ikke fjernes nå.'};
function friendly(error) { return errorLabels[error.message] || error.message; }
async function call(path, body) {
  const response = await fetch(root + path, {method: body ? 'POST' : 'GET',
    headers: body ? {'Content-Type':'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Forespørselen feilet');
  return data;
}
function button(label, handler) {
  const b = document.createElement('button'); b.textContent = label; b.onclick = handler; return b;
}
async function refresh() {
  try {
    const state = await call('/api/meters');
    document.getElementById('status').textContent =
      `Søk: ${statusLabels[state.scan_status] || state.scan_status}. Framdrift: ${state.scan_progress}/251 adresser. ` +
      `Funnet: ${state.available.length + state.selected.length} målere.` +
      (state.scan_errors.length ? ` Uavklarte svar: ${state.scan_errors.length}.` : '') +
      (state.cleanup_pending ? ` MQTT-opprydding venter: ${state.cleanup_pending}.` : '');
    for (const name of ['available', 'selected']) {
      const div = document.getElementById(name); div.replaceChildren();
      for (const item of state[name]) {
        const line = document.createElement('p');
        line.textContent = `ID ${item.meter_id}, adresse ${item.address}` +
          (item.manufacturer ? `, ${item.manufacturer}` : '');
        if (name === 'selected') line.append(button('Fjern', () => act('/api/remove', item.meter_id)));
        else if (item.supported) line.append(button('Legg til', () => act('/api/select', item.meter_id)));
        else line.append(' (ikke støttet)');
        div.append(line);
      }
    }
  } catch (e) { document.getElementById('error').textContent = friendly(e); }
}
async function act(path, meter_id) {
  try { await call(path, {meter_id}); document.getElementById('error').textContent = ''; await refresh(); }
  catch (e) { document.getElementById('error').textContent = friendly(e); }
}
document.getElementById('scan').onclick = async () => {
  try { await call('/api/scan', {}); await refresh(); }
  catch (e) { document.getElementById('error').textContent = friendly(e); }
};
document.getElementById('stop').onclick = async () => {
  try { await call('/api/stop', {}); await refresh(); }
  catch (e) { document.getElementById('error').textContent = friendly(e); }
};
document.getElementById('auto').onclick = () => act('/api/auto', '');
setInterval(refresh, 1500); refresh();
</script></html>"""


def serve(registry, config, client, bus_lock, stop, port=8099):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, payload, content_type="application/json"):
            body = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.client_address[0] != "172.30.32.2":
                self._send(403, {"error": "ingress required"})
                return
            if self.path.rstrip("/").endswith("/api/meters"):
                self._send(200, registry.snapshot())
            elif self.path == "/" or self.path.endswith("/"):
                self._send(200, PAGE, "text/html")
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.client_address[0] != "172.30.32.2":
                self._send(403, {"error": "ingress required"})
                return
            route = self.path.rsplit("/", 2)[-1]
            if route not in ("scan", "stop", "select", "auto", "remove"):
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 256:
                    raise ValueError("invalid request length")
                data = json.loads(self.rfile.read(length) or b"{}")
                meter_id = data.get("meter_id")
                if route == "scan":
                    with registry.lock:
                        if registry.scan_status == "running":
                            raise ValueError("scan already running")
                        registry.scan_status = "running"
                        registry.scan_progress = 0
                        registry.scan_errors = []
                        registry.found = {}
                        registry.scan_stop.clear()
                    threading.Thread(target=scan_bus, args=(config["serial_port"],
                                     int(config.get("baud", 2400)), registry, bus_lock, stop),
                                     daemon=True).start()
                elif route == "stop":
                    with registry.lock:
                        if registry.scan_status != "running":
                            raise ValueError("no scan is running")
                        registry.scan_stop.set()
                elif route == "select":
                    registry.select(meter_id)
                elif route == "auto":
                    registry.select_auto()
                else:
                    from mqtt_bridge import cleanup_discovery
                    with bus_lock, registry.lock:
                        if meter_id not in registry.selected:
                            raise ValueError("meter not selected")
                        from mqtt_bridge import mark_unavailable
                        result = mark_unavailable(client, meter_id)
                        if result.rc:
                            raise ConnectionError("MQTT unavailable; cannot remove meter")
                        result.wait_for_publish(timeout=5)
                        registry.remove(meter_id)
                        cleanup_discovery(client, meter_id)
                        registry.cleanup_done(meter_id)
                self._send(200, registry.snapshot())
            except (ValueError, KeyError, ConnectionError, OSError) as exc:
                self._send(400, {"error": str(exc)})

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
