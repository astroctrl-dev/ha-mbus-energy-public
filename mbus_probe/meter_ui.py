"""Small ingress-only UI for selecting discovered meters. No direct host port."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from meter_discovery import scan_bus
from analysis_export import load_samples, make_xlsx
from history_controller import HistoryController, load_history


PAGE = r"""<!doctype html><html lang="no"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M-Bus målere</title>
<style>html,body{margin:0;min-height:100%;background:#f7f9fb;color:#17212b;font:16px/1.5 system-ui,-apple-system,sans-serif}main{max-width:720px;margin:0 auto;padding:20px 16px 40px}h1{font-size:1.5rem;line-height:1.2;margin:0 0 8px}h2{font-size:1.15rem;margin:24px 0 8px}p{margin:8px 0}button{min-height:44px;max-width:100%;border:1px solid #8a9aaa;border-radius:8px;background:#e8f1fa;color:#152b3e;padding:8px 14px;font:inherit;margin:4px 4px 4px 0}button:disabled{opacity:.55}button:focus-visible{outline:3px solid #1266ab}.table-wrap{overflow-x:auto;background:#fff;border:1px solid #d0d9e1;border-radius:8px}table{border-collapse:collapse;width:100%;font:inherit}th,td{text-align:left;padding:8px;border-bottom:1px solid #d0d9e1;white-space:nowrap}#status{background:#fff;border:1px solid #d0d9e1;border-radius:8px;padding:12px}.meter{background:#fff;border:1px solid #d0d9e1;border-radius:8px;padding:12px;margin:8px 0;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;overflow-wrap:anywhere}#error{color:#a12020;overflow-wrap:anywhere}</style><main><h1>M-Bus målere</h1><p>Søk leser primæradressene 0–250. Målere med delt adresse kan ikke alltid skilles.</p>
<button id="scan">Søk etter målere</button><button id="auto">Velg eneste ledige automatisk</button>
<h2>Analyse</h2><p>Last ned validerte normalavlesninger og lagret månedshistorikk som Excel-fil. Nedlasting leser lagrede data og sender ingen kommando til måleren. Historikk hentes separat med knappen ved den valgte måleren.</p><button id="export">Last ned analyse (.xlsx)</button>
<p id="status"></p><h2>Lagret månedshistorikk</h2><p>Posisjonene angir rekkefølge i målerens historikk. Avregningsdato vises bare når den er verifisert.</p><div id="history"></div><h2>Tilgjengelige målere</h2><div id="available"></div>
<h2>Etablerte målere</h2><div id="selected"></div><p id="error" role="alert"></p>
</main><script>
const root = location.pathname.replace(/\/$/, '');
let refreshing = false;
let lastLists = '';
let lastHistoryCapture = null;
function addCell(row, value, heading=false) {
  const cell = document.createElement(heading ? 'th' : 'td');
  cell.textContent = String(value ?? '');
  row.append(cell);
}
async function refreshHistory() {
  const data = await call('/api/history');
  const area = document.getElementById('history');
  area.replaceChildren();
  if (!data.histories.length) { area.textContent = 'Ingen lagret månedshistorikk.'; return; }
  for (const entry of data.histories) {
    const title = document.createElement('h3'); title.textContent = entry.alias; area.append(title);
    const wrap = document.createElement('div'); wrap.className = 'table-wrap';
    const table = document.createElement('table'); const head = document.createElement('tr');
    for (const label of ['Posisjon', 'Målerstand (kWh)', 'Forbruk siden neste eldre stand (kWh)', 'Avregningsdato']) addCell(head, label, true);
    table.append(head);
    const periods = new Map(entry.snapshot.bounded_periods.map(p => [p.newer_storage, p.period_kwh]));
    for (const stand of entry.snapshot.stands) {
      const row = document.createElement('tr');
      addCell(row, '−' + stand.month_back);
      addCell(row, stand.cumulative_kwh);
      addCell(row, periods.get(stand.storage) ?? '—');
      addCell(row, stand.meter_date ?? 'Ikke tilgjengelig');
      table.append(row);
    }
    wrap.append(table); area.append(wrap);
  }
}
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
  if (refreshing) return;
  refreshing = true;
  try {
    const state = await call('/api/meters');
    document.getElementById('status').textContent =
      `Søk: ${state.scan_status}, adresser sjekket: ${state.scan_progress}/251, ` +
      `uavklarte svar: ${state.scan_errors.length}, opprydding venter: ${state.cleanup_pending}. ` +
      `Historikk: ${state.history.status}` + (state.history.error ? ` – ${state.history.error}` : '');
    if (state.history.status === 'complete' && state.history.captured_at_utc !== lastHistoryCapture) {
      lastHistoryCapture = state.history.captured_at_utc;
      await refreshHistory();
    }
    document.getElementById('scan').disabled = state.scan_status === 'running';
    document.getElementById('auto').disabled = state.scan_status !== 'completed' || state.scan_errors.length > 0 || state.available.filter(m => m.supported).length !== 1;
    const lists = JSON.stringify([state.available, state.selected, state.history_enabled, state.history.status]);
    if (lists !== lastLists) {
      lastLists = lists;
    for (const name of ['available', 'selected']) {
      const div = document.getElementById(name); div.replaceChildren();
      for (const item of state[name]) {
        const line = document.createElement('div'); line.className = 'meter';
        line.textContent = `ID ${item.meter_id}, adresse ${item.address}` +
          (item.manufacturer ? `, ${item.manufacturer}` : '');
        if (name === 'selected') {
          line.append(button('Fjern', () => act('/api/remove', item.meter_id)));
          const hist = button('Hent månedshistorikk', async () => {
            if (!confirm('Dette bytter midlertidig M-Bus-ramme (CI=50h/03h), leser historikk og gjenoppretter normalrammen. Avlesningen tar noen minutter. Fortsette?')) return;
            await act('/api/history', item.meter_id);
          });
          hist.disabled = !state.history_enabled || state.history.status === 'running';
          line.append(hist);
        }
        else if (item.supported) line.append(button('Legg til', () => act('/api/select', item.meter_id)));
        else line.append(' (ikke støttet)');
        div.append(line);
      }
    }
    }
  } catch (e) { document.getElementById('error').textContent = e.message; }
  finally { refreshing = false; }
}
async function act(path, meter_id) {
  try { await call(path, {meter_id}); document.getElementById('error').textContent = ''; await refresh(); }
  catch (e) { document.getElementById('error').textContent = e.message; }
}
document.getElementById('scan').onclick = async () => {
  try { await call('/api/scan', {}); document.getElementById('error').textContent = ''; await refresh(); }
  catch (e) { document.getElementById('error').textContent = e.message; }
};
document.getElementById('auto').onclick = () => act('/api/auto', '');
document.getElementById('export').onclick = async () => {
  try {
    const res = await fetch(root + '/api/export.xlsx');
    if (!res.ok) {
      const data = await res.json(); throw new Error(data.error || 'Ingen data tilgjengelig');
    }
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement('a'); link.href = url;
    link.download = 'mbus-analysis.xlsx'; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    document.getElementById('error').textContent = '';
  } catch (e) { document.getElementById('error').textContent = e.message; }
};
setInterval(refresh, 1500); refreshHistory(); refresh();
</script></html>"""


def serve(registry, config, client, bus_lock, stop, port=8099, history_controller=None):
    history_controller = history_controller or HistoryController(registry, config, bus_lock, stop)
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
                self._send(200, {**registry.snapshot(), "history": history_controller.snapshot(),
                                 "history_enabled": config.get("allow_monthly_history", False)})
            elif self.path.rstrip("/").endswith("/api/history"):
                try:
                    entries = [{"alias": alias, "snapshot": snapshot} for alias, snapshot in
                               load_history("/data/analysis", registry.snapshot()["selected"])]
                except (OSError, ValueError, KeyError):
                    self._send(409, {"error": "Lagret historikk kunne ikke leses"})
                    return
                self._send(200, {"histories": entries})
            elif self.path.endswith("/api/export.xlsx"):
                try:
                    payload = make_xlsx(load_samples("/data/analysis/normal.jsonl"),
                                        load_history("/data/analysis", registry.snapshot()["selected"]))
                except (OSError, ValueError, KeyError):
                    self._send(409, {"error": "Ingen validerte analysedata tilgjengelig"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", 'attachment; filename="mbus-analysis.xlsx"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/" or self.path.endswith("/"):
                self._send(200, PAGE, "text/html")
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.client_address[0] != "172.30.32.2":
                self._send(403, {"error": "ingress required"})
                return
            route = self.path.rsplit("/", 2)[-1]
            if route not in ("scan", "select", "auto", "remove", "history"):
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
                    threading.Thread(target=scan_bus, args=(config["serial_port"],
                                     int(config.get("baud", 2400)), registry, bus_lock, stop),
                                     daemon=True).start()
                elif route == "history":
                    history_controller.start(meter_id)
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
    server.history_controller = history_controller
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
