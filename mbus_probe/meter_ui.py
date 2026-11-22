"""Small ingress-only UI for selecting discovered meters. No direct host port."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from meter_discovery import scan_bus


PAGE = r"""<!doctype html><html lang="no"><meta charset="utf-8"><title>M-Bus målere</title>
<h1>M-Bus målere</h1><p>Søk leser primæradressene 0–250. Målere med delt adresse kan ikke alltid skilles.</p>
<button id="scan">Søk etter målere</button><button id="stop">Stopp søk</button><button id="auto">Velg eneste ledige automatisk</button>
<p id="status"></p><h2>Tilgjengelige målere</h2><div id="available"></div>
<h2>Etablerte målere</h2><div id="selected"></div><p id="error" role="alert"></p>
<script>
const root = location.pathname.replace(/\/$/, '');
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
      `Søk: ${state.scan_status}, adresser sjekket: ${state.scan_progress}/251, ` +
      `uavklarte svar: ${state.scan_errors.length}, opprydding venter: ${state.cleanup_pending}`;
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
  } catch (e) { document.getElementById('error').textContent = e.message; }
}
async function act(path, meter_id) {
  try { await call(path, {meter_id}); document.getElementById('error').textContent = ''; await refresh(); }
  catch (e) { document.getElementById('error').textContent = e.message; }
}
document.getElementById('scan').onclick = async () => {
  try { await call('/api/scan', {}); await refresh(); }
  catch (e) { document.getElementById('error').textContent = e.message; }
};
document.getElementById('stop').onclick = async () => {
  try { await call('/api/stop', {}); await refresh(); }
  catch (e) { document.getElementById('error').textContent = e.message; }
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
