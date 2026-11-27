"""Small ingress-only UI for selecting discovered meters. No direct host port."""
import json
from html import escape
from i18n import resolve_language
from ui_translations import TRANSLATIONS, STATUS_TEXT
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from meter_discovery import scan_bus
from operation_admission import OperationAdmission
from analysis_export import load_samples, make_xlsx
from history_controller import HistoryController, load_history, stored_archive_progress
from clock_maintenance import ClockController
from clock_model import configured_local
from dst_transition import TransitionStore
from mqtt_bridge import publish_history, publish_monthly_retry
from monthly_retry import MonthlyRetry
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo


PAGE = r"""<!doctype html><html lang="no"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M-Bus målere</title>
<style>html,body{margin:0;min-height:100%;background:#f7f9fb;color:#17212b;font:16px/1.5 system-ui,-apple-system,sans-serif}main{max-width:720px;margin:0 auto;padding:20px 16px 40px}h1{font-size:1.5rem;line-height:1.2;margin:0 0 8px}h2{font-size:1.15rem;margin:24px 0 8px}p{margin:8px 0}button{min-height:44px;max-width:100%;border:1px solid #8a9aaa;border-radius:8px;background:#e8f1fa;color:#152b3e;padding:8px 14px;font:inherit;margin:4px 4px 4px 0}button:disabled{opacity:.55}button:focus-visible{outline:3px solid #1266ab}.table-wrap{overflow-x:auto;background:#fff;border:1px solid #d0d9e1;border-radius:8px}table{border-collapse:collapse;width:100%;font:inherit}th,td{text-align:left;padding:8px;border-bottom:1px solid #d0d9e1;white-space:nowrap}#status{background:#fff;border:1px solid #d0d9e1;border-radius:8px;padding:12px}.meter{background:#fff;border:1px solid #d0d9e1;border-radius:8px;padding:12px;margin:8px 0;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;overflow-wrap:anywhere}details{margin:12px 0}summary{cursor:pointer;font-weight:600;padding:8px 0}#error{color:#a12020;overflow-wrap:anywhere}.active-diagnostics{width:100%;border-top:1px solid #d0d9e1;padding-top:8px}.battery-line{display:flex;align-items:center;gap:10px}.battery-symbol{width:48px;height:23px;position:relative;border:2px solid currentColor;border-radius:4px;box-sizing:border-box;display:inline-flex;align-items:center;padding:2px}.battery-symbol:after{content:'';position:absolute;right:-6px;top:5px;width:4px;height:9px;background:currentColor;border-radius:1px}.battery-fill{height:100%;border-radius:1px;background:currentColor}.battery-normal{color:#207b43}.battery-normal .battery-fill{width:100%}.battery-pre-warning{color:#946500}.battery-pre-warning .battery-fill{width:30%;background:#d5a000}.battery-exhausted{color:#b22222}.battery-unknown{color:#687582}.battery-exhausted .battery-fill,.battery-unknown .battery-fill{display:none}.battery-mark{font-weight:bold;width:100%;text-align:center;line-height:1}h3{font-size:1rem;margin:16px 0 4px}#address-panel{border-top:1px solid #d0d9e1;padding:8px 0}#address-target{box-sizing:border-box;width:6rem;max-width:100%;min-height:48px;font:600 1.5rem/1.2 system-ui,sans-serif;text-align:center;border:1px solid #8a9aaa;border-radius:8px;padding:6px;color:#17212b;background:white}#address-target:focus-visible{outline:3px solid #1266ab}.address-actions{display:flex;flex-wrap:wrap;align-items:center;gap:4px}.address-note,.export-note{font-size:.875rem;color:#526273}#address-results button{min-width:48px}#address-results button:disabled{opacity:1;cursor:not-allowed}#raw-status{font-size:.875rem}.export-block{border-top:1px solid #d0d9e1;padding:8px 0} .diagnostic-details{margin:8px 0}.diagnostic-details p{margin:4px 0}.diagnostic-warning{color:#92400e;font-weight:600}.meter-actions{width:100%;display:flex;flex-wrap:wrap;gap:4px;align-items:center}.meter-actions-title{width:100%;font-weight:600}.table-wrap th{white-space:normal;line-height:1.2;font-size:.875rem}.table-wrap td{font-variant-numeric:tabular-nums}.table-wrap th,.table-wrap td{padding:7px 6px}.help-details{font-size:.875rem;color:#526273}.diagnostic-stamp{font-size:.875rem;color:#526273}.meter-admin{width:100%;border-top:1px solid #d0d9e1;padding-top:8px}</style><main><h1>M-Bus målere</h1><p>Søk leser primæradressene 0–250. Målere med delt adresse kan ikke alltid skilles.</p>
<p>Initial readings are normally available within about 60 seconds. If the meter is in a confirmed historical telegram mode, automatic restoration of normal telegram mode may take about three minutes in total. Communication errors may extend this time. The minimum interval between commands is 60 seconds.</p><button id="scan">Søk etter målere</button>
<h2>Tilgjengelige målere</h2><div id="available"></div>
<h2>Etablerte målere</h2><div id="selected"></div>
<section id="protocol-diagnostic-panel" hidden><h2>Address protocol diagnostic (test)</h2><p>Isolated single-meter test only. Normal polling pauses for several minutes. No permanent meter parameter writes are authorized.</p><fieldset id="protocol-diagnostic-fields"><legend>Expected instrument identity</legend><p><label>Meter ID <input id="pd-id" inputmode="numeric" maxlength="8" pattern="[0-9]{8}"></label></p><p><label>Manufacturer <input id="pd-manufacturer" maxlength="3" pattern="[A-Z]{3}"></label></p><p><label>Version <input id="pd-version" type="number" min="0" max="254" step="1"></label> <label>Medium <input id="pd-medium" type="number" min="0" max="254" step="1"></label></p><p><label>Fabrication number <input id="pd-number" inputmode="numeric" maxlength="8" pattern="[0-9]{8}"></label></p><p><label>Current primary address <input id="pd-address" type="number" min="0" max="250" step="1"></label></p></fieldset><p><label><input id="pd-single" type="checkbox"> I confirm only one physical meter and one master are connected.</label></p><button id="pd-start" disabled>Run protocol test</button><button id="pd-recover" hidden disabled>Recover diagnostic session</button><p id="pd-status" role="status"></p><p id="pd-pending"></p><p><label>Evidence filename <input id="pd-file" maxlength="42" placeholder="UUID.jsonl"></label><button id="pd-download" disabled>Download private evidence</button></p></section><section id="quarantine-panel" hidden><h2>Address conflict recovery</h2><p>Normal bus operations are blocked until all affected instruments are verified. No response does not prove an address is free.</p><div id="quarantine-list"></div><p id="quarantine-status" role="status"></p></section><section id="address-recovery" hidden><h2>Address recovery</h2><p id="address-recovery-info" role="status"></p><p>Verify the physical address without repeating the address change.</p><button id="address-recover">Verify actual address</button></section><div id="address-panel-parking"><section id="address-panel" hidden><h2>Primary address</h2><button id="address-close">Close</button><p id="address-meter"></p><label for="address-target">New address (0–250)</label><div class="address-actions"><input id="address-target" type="text" inputmode="numeric" maxlength="3" pattern="[0-9]{1,3}" required><button id="address-check">Check address</button></div><h3>Address search</h3><div class="address-actions"><button id="address-search">New search</button><button id="address-resume" disabled>Resume</button><button id="address-stop">Stop</button></div><p id="address-progress" role="status"></p><div id="address-results"></div><p class="address-note">Green: available candidate. Yellow: conflict risk. Red: not selectable. No response does not guarantee availability. Counts refer to registered meters.</p><details class="address-note"><summary>Search timing</summary>Unanswered distinct addresses: minimum 2 seconds. Repeated addresses, responses and uncertain exchanges: 60-second guard.</details><div id="address-write-panel" hidden><label><input type="checkbox" id="address-override" disabled> Accept displayed destination risk</label><p id="address-risk" role="status"></p><button id="address-change">Change address</button><p id="address-change-status" role="status"></p></div><p id="address-write-disabled">Address writing is not enabled in this build.</p></section></div><h2>Klokke</h2><p id="clock-status"></p><details class="help-details"><summary>More information</summary><p>Synkronisering bruker systemtid og valgt tidssone i Configuration. Manuell synkronisering krever bekreftelse; automatisk kontroll starter etter første gyldige måling ved oppstart eller nytt målervalg.</p></details>
<h2>Lagret månedshistorikk</h2><p>Retrieval may pause live readings. Allow about four minutes per missing extended month.</p><details class="help-details"><summary>More information</summary><p>First installation: leave all optional switches off and verify ordinary live measurements before enabling additional functions. Initial retrieval reads frames 2 and 3. Subsequent manual retrieval reads missing extended months (frame 4); allow about four minutes per month. The table shows progress for the current job. Regular polling pauses; live values may be stale or temporarily unavailable. Clock synchronization and scanning also respect the interval. Downloads use saved data and do not query the meter.</p><p>Positions indicate the order in the meter archive. A dash means no retrieval has been started in this session. Saved energy values remain visible while extended data is being read.</p></details><div id="history"></div><section id="data-export"><h2>Data export</h2><div class="export-block"><h3>Measurement data</h3><p class="export-note">Export stored measurements and monthly history. Logging is controlled in Configuration.</p><button id="export">Download Excel (.xlsx)</button></div><div class="export-block"><h3>Raw telegrams</h3><p class="export-note">Enable capture in Configuration and restart. May contain private meter data.</p><p id="raw-status" role="status"></p><button id="raw-download">Download raw text (.txt)</button></div></section><p id="status"></p><p id="error" role="alert"></p>
</main><script>
const root = location.pathname.replace(/\/$/, '');
let refreshing = false;
let lastLists = '';
const diagnosticOpen = new Map();
let lastHistoryCapture = null;
let lastArchiveRevision = -1;
let historySubmitting = false;
let addressMeter = null;
let addressOld = null;
let addressChangeEnabled = false;
let addressChangeBusy = false;
let addressRefreshing = false;
let addressAppliedResult = null;
let quarantineRows = [];
let quarantineView = '';
let quarantineEnabled = false;
let quarantineSubmitting = false;
let quarantineDrafts = new Map();
let quarantineRecoveryPending = false;
function renderQuarantine(rows,enabled) {
  quarantineRows=rows || [];
  quarantineEnabled=enabled===true;
  const blocked=addressChangeBusy||quarantineSubmitting||quarantineRecoveryPending||['running','stopping'].includes(addressJob?.status);
  const panel=document.getElementById('quarantine-panel');
  panel.hidden=!enabled || !quarantineRows.length;
  const key=JSON.stringify([enabled,quarantineRows,blocked]);
  const keys=new Set(quarantineRows.map(r=>r.meter_id+':'+r.address));
  for(const draft of quarantineDrafts.keys()) if(!keys.has(draft)) quarantineDrafts.delete(draft);
  if(key===quarantineView) return;
  quarantineView=key;
  const list=document.getElementById('quarantine-list'); list.replaceChildren();
  if(!enabled) return;
  for(const row of quarantineRows) {
    const line=document.createElement('div');
    line.textContent='ID '+row.meter_id+' — '+addressFormat(row.address)+(row.registered_conflict?' — Registered address conflict':'');
    const input=document.createElement('input'); input.type='number'; input.min='0';input.max='250';input.step='1';input.setAttribute('aria-label','New primary address for '+row.meter_id);
    const draftKey=row.meter_id+':'+row.address;
    input.value=quarantineDrafts.get(draftKey)||'';
    input.oninput=()=>quarantineDrafts.set(draftKey,input.value);
    input.disabled=blocked;
    const action=async(kind)=>{
      if(blocked||quarantineSubmitting||addressChangeBusy||quarantineRecoveryPending) return;
      const target=kind==='relocate'?Number(input.value):null;
      if(kind==='relocate' && (!validAddressInput(input) || target===row.address)) return;
      if(!confirm(kind+' instrument '+row.meter_id+' at '+addressFormat(row.address)+(target===null?'':' to '+addressFormat(target))+'?')) return;
      quarantineSubmitting=true;
      renderQuarantine(quarantineRows,quarantineEnabled);
      try {
        const job=await call('/api/address_quarantine',{meter_id:row.meter_id,address:row.address,action:kind,confirm:true,new_address:target});
        if(job?.status) renderAddressChange({address_change_enabled:addressChangeEnabled,address_change:job,address_search:addressJob});
        await refreshAddressStatus();
      }
      catch(e){document.getElementById('error').textContent=e.message;}
      finally {quarantineSubmitting=false;renderQuarantine(quarantineRows,quarantineEnabled);}
    };
    if(!row.identity_enrolled && !row.registered_conflict) line.append(button('Identify instrument',()=>action('enroll'),blocked));
    if(row.identity_enrolled) {
      line.append(input,button('Resolve address conflict',()=>action('relocate'),blocked));
      if(!row.registered_conflict) line.append(button('Verify and resume',()=>action('verify'),blocked));
    } else if(row.registered_conflict) line.append(document.createTextNode(' — Resolve another identified instrument first; physical isolation may be required.'));
    list.append(line);
  }
}
let displayedRisk = null;
let invalidatedSearch = null;
function syncRisk() {
  const row = recoveryJob?.status==='override_required' ? recoveryJob.destination_evidence : null;
  const target = Number(document.getElementById('address-target').value);
  const next = row && row.meter_id===addressMeter && row.old_address===addressOld && row.new_address===target ? row : null;
  if(JSON.stringify(next)!==JSON.stringify(displayedRisk)) document.getElementById('address-override').checked=false;
  displayedRisk=next;
  document.getElementById('address-override').disabled=!next;
  document.getElementById('address-risk').textContent=next?'Destination '+addressFormat(next.new_address)+' — '+(addressLabels[next.status]||next.status)+'; registered peers: '+next.registered_peers.length:'';
}
function updateAddressHeader() {
  document.getElementById('address-meter').textContent='ID '+addressMeter+' — Current address '+addressFormat(addressOld);
}
let recoveryJob = null;
let addressView = '';
let addressJob = null;
const addressLabels = {current_address:'Current address',current_address_conflict:'Current address – conflict',occupied:'Occupied',occupied_multiple:'Occupied – multiple meters',ambiguous:'Possible address conflict',no_response:'Available (no response)',failed:'Check failed'};
function addressChoice(status) {
  if(status==='no_response') return {selectable:true,bg:'#dcfce7',fg:'#166534'};
  if(['occupied','occupied_multiple','ambiguous'].includes(status)) return {selectable:true,bg:'#fef3c7',fg:'#92400e'};
  if(status==='current_address') return {selectable:false,bg:'#f1f5f9',fg:'#475569'};
  return {selectable:false,bg:'#fee2e2',fg:'#991b1b'};
}
function styleAddressChoice(element,choice) {
  element.style.backgroundColor=choice.bg;
  element.style.color=choice.fg;
}
function groupAddressRows(rows) {
  const groups = [];
  for (const row of [...rows].sort((a,b)=>a.address-b.address)) {
    const last = groups[groups.length-1];
    if (last && row.address === last.end+1 && row.status === last.status && row.known_meter_count === last.count) last.end=row.address;
    else groups.push({start:row.address,end:row.address,status:row.status,count:row.known_meter_count});
  }
  return groups;
}
const addressFormat = n=>String(n).padStart(3,'0');
function renderAddressJob(job) {
  addressJob = job;
  if (!addressMeter) return;
  const matching = job.meter_id === addressMeter;
  const running = ['running','stopping'].includes(job.status);
  document.getElementById('address-check').disabled = running;
  document.getElementById('address-search').disabled = running;
  document.getElementById('address-stop').disabled = !matching || job.status !== 'running';
  document.getElementById('address-close').disabled = running;
  document.getElementById('address-resume').disabled = !matching || job.can_resume !== true || running;
  document.getElementById('address-progress').textContent = matching ? job.status+' – '+job.results.length+'/'+job.total : '';
  const area = document.getElementById('address-results');
  const stale=job.search_id!=null && job.search_id===invalidatedSearch;
  const rows = matching && !stale ? job.results : [];
  if(stale) document.getElementById('address-progress').textContent='Search results invalidated; check destination again.';
  const key = JSON.stringify([addressMeter,rows]);
  if (key === addressView) return;
  addressView = key;
  const opened = new Set(Array.from(area.querySelectorAll('details[open]'),d=>d.dataset.start));
  area.replaceChildren();
  const choose = n => {document.getElementById('address-target').value=String(n); document.getElementById('address-override').checked=false; syncRisk();};
  for (const g of groupAddressRows(rows)) {
    const label = (addressLabels[g.status] || g.status) + (g.count>1 ? ' ('+g.count+')' : '');
    const choice=addressChoice(g.status);
    const candidateButton=(label,n)=>{
      const candidate=button(label,()=>{if(choice.selectable) choose(n);},!choice.selectable);
      styleAddressChoice(candidate,choice);
      return candidate;
    };
    if (g.start === g.end) {
      area.append(candidateButton(addressFormat(g.start)+' — '+label,g.start));
    } else {
      const details=document.createElement('details'); details.dataset.start=String(g.start);
      details.open=opened.has(details.dataset.start);
      const summary=document.createElement('summary');
      summary.textContent=addressFormat(g.start)+'–'+addressFormat(g.end)+' — '+label;
      styleAddressChoice(summary,choice);
      details.append(summary);
      for(let n=g.start;n<=g.end;n++) {
        details.append(candidateButton(addressFormat(n),n));
      }
      area.append(details);
    }
  }
}
function openAddressPanel(item, host) {
  if (addressJob && ['running','stopping'].includes(addressJob.status) && addressJob.meter_id !== item.meter_id) return;
  if (host) host.append(document.getElementById('address-panel'));
  addressMeter=item.meter_id;
  addressOld=item.address;
  document.getElementById('address-override').checked=false;
  document.getElementById('address-panel').hidden=false;
  addressAppliedResult=null;
  updateAddressHeader();
  document.getElementById('address-target').value=String(item.address);
  addressView='';
  if(addressJob) renderAddressJob(addressJob);
  syncRisk();
}
function renderAddressChange(state) {
  addressChangeEnabled=state.address_change_enabled === true;
  const job=state.address_change;
  recoveryJob=job;
  if(job?.meter_id===addressMeter && ['verified_new','verified_old'].includes(job.status)) {
    const key=JSON.stringify([job.operation_id,job.meter_id,job.old_address,job.new_address,job.status]);
    if(addressAppliedResult!==key) {
      addressAppliedResult=key;
      addressOld=job.status==='verified_new'?job.new_address:job.old_address;
      updateAddressHeader();
      document.getElementById('address-target').value=String(addressOld);
      document.getElementById('address-override').checked=false;
      invalidatedSearch=addressJob?.search_id ?? null;
      addressView='';
      document.getElementById('address-results').replaceChildren();
      document.getElementById('address-progress').textContent='Search results invalidated; check destination again.';
    }
  }
  syncRisk();
  const recovery=job?.status==='recovery_required';
  document.getElementById('address-recovery').hidden=!recovery;
  document.getElementById('address-recovery-info').textContent=recovery?(job.recoverable?'ID '+job.meter_id+' — '+addressFormat(job.old_address)+' / '+addressFormat(job.new_address):'Recovery unavailable; inspect persistent transaction state.') : '';
  document.getElementById('address-recover').disabled=!job?.recoverable;
  addressChangeBusy=job?.status === 'running';
  quarantineRecoveryPending=recovery;
  renderQuarantine(quarantineRows,quarantineEnabled);
  if(job?.action) document.getElementById('quarantine-status').textContent=job.meter_id+' — '+job.status;
  document.getElementById('address-write-panel').hidden=!addressChangeEnabled;
  document.getElementById('address-write-disabled').hidden=addressChangeEnabled;
  const searchBusy=['running','stopping'].includes(state.address_search?.status);
  const quarantined=quarantineRows.length>0;
  document.getElementById('address-change').disabled=addressChangeBusy||searchBusy||recovery||quarantined;
  if(addressChangeBusy||recovery||quarantined) {
    document.getElementById('address-check').disabled=true;
    document.getElementById('address-search').disabled=true;
    document.getElementById('address-resume').disabled=true;
  }
  const labels={running:'Changing and verifying address…',verified_new:'New address verified',verified_old:'Old address verified; change not confirmed',unchanged:'Address unchanged',override_required:'Destination risk requires explicit confirmation',identity_blocked:'Instrument identity not verified',recovery_required:'Recovery required; do not retry'};
  document.getElementById('address-change-status').textContent=job?.meter_id===addressMeter?(labels[job.status]||job.status):'';
}
document.getElementById('address-recover').onclick=async()=>{
  const pending=recoveryJob;
  if(!pending?.recoverable || !confirm('Verify the actual address without repeating the address change?')) return;
  document.getElementById('address-recover').disabled=true;
  try {await call('/api/address_recover',{meter_id:pending.meter_id,transaction_id:pending.transaction_id,confirm:true}); await refresh();}
  catch(e){document.getElementById('error').textContent=e.message;}
};
function validAddressInput(input) {return /^[0-9]{1,3}$/.test(input.value) && Number(input.value)<=250 && input.checkValidity();}
document.getElementById('address-target').oninput=()=>{const input=document.getElementById('address-target'); input.value=input.value.replace(/[^0-9]/g,'').slice(0,3); document.getElementById('address-override').checked=false; syncRisk();};
document.getElementById('address-change').onclick=async()=>{
  const input=document.getElementById('address-target');
  if(!addressChangeEnabled||addressChangeBusy||quarantineRows.length||quarantineRecoveryPending||!addressMeter||!validAddressInput(input)) return;
  const target=Number(input.value), override=document.getElementById('address-override').checked;
  if(target===addressOld || (override && !displayedRisk)) return;
  if(!confirm('Change meter '+addressMeter+' from '+addressFormat(addressOld)+' to '+addressFormat(target)+'? The destination will be checked again. '+(override?'You explicitly accept destination conflict or uncertainty.':'Conflicting or uncertain destinations will stop the operation.'))) return;
  document.getElementById('address-change').disabled=true;
  document.getElementById('address-override').checked=false;
  try {await call('/api/address_change',{meter_id:addressMeter,old_address:addressOld,new_address:target,confirm:true,override,accepted_risk:override?displayedRisk:null}); await refresh();}
  catch(e){document.getElementById('error').textContent=e.message;}
};
async function addressAction(route, all=false, resume=false) {
  if(!addressMeter || (route!=='address_stop' && (addressChangeBusy||quarantineRecoveryPending||quarantineRows.length))) return;
  const input=document.getElementById('address-target');
  if(route!=='address_stop' && !all && (!validAddressInput(input))) return;
  if(all && !resume && addressJob?.meter_id===addressMeter && addressJob.can_resume && !confirm('Start a new search and discard previous results?')) return;
  const value=Number(input.value);
  const body=route==='address_stop'?{meter_id:addressMeter}:{meter_id:addressMeter,first:all?0:value,last:all?250:value,...(resume?{resume:true}:{})};
  try { await call('/api/'+route,body); await refresh(); }
  catch(e) { document.getElementById('error').textContent=e.message; }
}
document.getElementById('address-close').onclick=()=>{
  if(addressJob && ['running','stopping'].includes(addressJob.status)) return;
  const panel=document.getElementById('address-panel');
  panel.hidden=true;
  document.getElementById('address-panel-parking').append(panel);
  addressMeter=null;
};
document.getElementById('address-check').onclick=()=>addressAction('address_search');
document.getElementById('address-search').onclick=()=>addressAction('address_search',true);
document.getElementById('address-stop').onclick=()=>addressAction('address_stop');
document.getElementById('address-resume').onclick=()=>addressAction('address_search',true,true);
function displayTimestamp(value) {
  if(typeof value!=='string') return value ?? '—';
  return value.replace(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(:\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/,(_,date,hm,seconds,zone)=>date+' '+hm+(seconds||'')+(zone==='Z'||zone==='+00:00'?' UTC':zone?' '+zone:''));
}
function addCell(row, value, heading=false) {
  const cell = document.createElement(heading ? 'th' : 'td');
  cell.textContent = String(value ?? '');
  row.append(cell);
}
async function refreshHistory() {
  const data = await call('/api/history');
  const area = document.getElementById('history');
  const previousOpen = new Map(Array.from(area.querySelectorAll('details[data-meter]'), d => [d.dataset.meter, d.open]));
  const previousErrors = new Map(Array.from(area.querySelectorAll('details[data-error-meter]'), d => [d.dataset.errorMeter,d.open]));
  area.replaceChildren();
  if (!data.histories.length) { area.textContent = 'Ingen lagret månedshistorikk.'; return; }
  for (const entry of data.histories) {
    const details = document.createElement('details');
    details.dataset.meter = entry.alias;
    details.open = previousOpen.get(entry.alias) ?? (data.histories.length === 1 || data.archive_alias === entry.alias);
    const title = document.createElement('summary'); title.textContent = entry.alias; details.append(title);
    area.append(details);
    const evidence = document.createElement('p');
    evidence.textContent = entry.snapshot.rollover_evidence === 'confirmed_shift'
      ? 'Månedsskifte bekreftet ved forskyvning av alle 24 arkivposisjoner.'
      : 'Månedsskifte ikke bekreftet ved sammenligning med forrige avlesning.';
    details.append(evidence);
    const errors = entry.snapshot.error_history;
    if (errors) {
      const errorDetails=document.createElement("details"); errorDetails.dataset.errorMeter=entry.alias;
      errorDetails.open=previousErrors.get(entry.alias) ?? false;
      const summary=document.createElement("summary"); summary.textContent="Error history"; errorDetails.append(summary);
      const label = document.createElement("p");
      label.textContent = localText("ERROR_HISTORY_TITLE") + ": " + displayTimestamp(errors.read_at_utc);
      errorDetails.append(label);
      const list = document.createElement("p");
      list.textContent = Object.entries({"FT":"Last Negative Temperature Difference (FT)","FF2":"Last Reverse Flow (FF2)","FS":"Last Sensor Error (FS)","FE":"Last Electronic Error (FE)","FF1":"Last Flow Rate Error (FF1)"}).map(([code,label]) => label + ": " + displayTimestamp(errors.last_occurrence_local?.[code])).join("; ");
      errorDetails.append(list);
      const note = document.createElement("p"); note.textContent = localText("ERROR_HISTORY_NOTE"); errorDetails.append(note);
      details.append(errorDetails);
    }
    const wrap = document.createElement('div'); wrap.className = 'table-wrap';
    const table = document.createElement('table'); const head = document.createElement('tr');
    for (const label of ['Pos.', 'Reading (kWh)', 'Usage (kWh)', 'Status']) addCell(head, label, true);
    table.append(head);
    const periods = new Map(entry.snapshot.bounded_periods.map(p => [p.newer_storage, p.period_kwh]));
    const progress = {...entry.stored_progress, ...(data.archive_alias === entry.alias ? data.archive_progress : {})};
    const statusLabels = {waiting:'Waiting',request:'Request',completed:'Completed',stored:'Already stored',failed:'Failed',aborted:'Aborted',retry2:'Retry 2/3',retry3:'Retry 3/3'};
    const statusColors = {waiting:'#777',request:'#a66b00',completed:'#17803d',stored:'#17803d',failed:'#b91c1c',aborted:'#777',retry2:'#a66b00',retry3:'#a66b00'};
    for (const stand of entry.snapshot.stands) {
      const row = document.createElement('tr');
      addCell(row, '−' + String(stand.month_back).padStart(2, '0'));
      addCell(row, stand.cumulative_kwh);
      addCell(row, periods.get(stand.storage) ?? '—');
      const status = progress[String(stand.month_back)];
      const cell = document.createElement('td');
      cell.textContent = statusLabels[status] ? '● ' + statusLabels[status] : '—';
      if (statusColors[status]) { cell.style.color=statusColors[status]; cell.style.fontWeight='600'; }
      row.append(cell);
      table.append(row);
    }
    wrap.append(table); details.append(wrap);
  }
}
async function call(path, body) {
  const response = await fetch(root + path, {method: body ? 'POST' : 'GET',
    headers: body ? {'Content-Type':'application/json'} : {},
    body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(localText(data.error) || 'Forespørselen feilet');
  return data;
}
function button(label, handler, disabled=false) {
  const b = document.createElement('button'); b.textContent = label; b.onclick = handler; b.disabled = disabled; return b;
}
function renderActiveDiagnostics(data, meterId) {
  const section = document.createElement('section');
  section.className = 'active-diagnostics';
  const title = document.createElement('strong');
  title.textContent = 'Active diagnostics';
  section.append(title);
  const states = ['normal', 'pre-warning', 'exhausted', 'unknown'];
  const battery = states.includes(data.battery_status) ? data.battery_status : 'unknown';
  const labels = {'normal':'Normal','pre-warning':'Pre-warning','exhausted':'Exhausted','unknown':'Unknown'};
  const line = document.createElement('p');
  line.className = 'battery-line';
  const icon = document.createElement('span');
  icon.className = 'battery-symbol battery-' + battery;
  icon.setAttribute('aria-hidden','true');
  const fill = document.createElement('span');
  fill.className = 'battery-fill';
  icon.append(fill);
  if (battery === 'exhausted' || battery === 'unknown') {
    const mark = document.createElement('span');
    mark.className = 'battery-mark';
    mark.textContent = battery === 'exhausted' ? '×' : '?';
    icon.append(mark);
  }
  line.append(icon, document.createTextNode('Battery Status: ' + labels[battery]));
  section.append(line);
  const flag = v => v === true ? 'Active' : v === false ? 'Inactive' : 'Unknown';
  const faults = document.createElement('p');
  faults.textContent = 'Active Meter Faults: ' + flag(data.active_meter_faults);
  section.append(faults);
  if (Array.isArray(data.fault_messages) && data.fault_messages.length) {
    const list = document.createElement('ul');
    for (const message of data.fault_messages) {
      const item = document.createElement('li');
      item.textContent = message;
      list.append(item);
    }
    section.append(list);
  }
  const flow = document.createElement('p');
  flow.textContent = 'Flow Warning: ' + flag(data.flow_warning);
  section.append(flow);
  const installation = document.createElement('p');
  installation.textContent = 'Meter Installation Status: ' + ({normal:'Normal', warning:'Warning', unknown:'Unknown'}[data.meter_installation_status] || 'Unknown');
  section.append(installation);
  const ext = data.extension || {};
  const extension = document.createElement('p');
  extension.textContent = 'Extension Byte Warning: ' + flag(ext.extension_byte_warning) +
    ' (' + (ext.extension_byte || 'Unknown') + ')';
  section.append(extension);
  const details=document.createElement('details'); details.className='diagnostic-details';
  details.open=diagnosticOpen.get(meterId)===true;
  details.ontoggle=()=>diagnosticOpen.set(meterId,details.open);
  const summary=document.createElement('summary'); summary.textContent='Diagnostic details'; details.append(summary);
  const attributes=new Map();
  for(const [source,values] of [['Flow',data.flow_attributes||{}],['Installation',data.installation_attributes||{}]]) {
    for(const [key,value] of Object.entries(values)) {
      if(!attributes.has(key)) attributes.set(key,[]);
      attributes.get(key).push({source,value});
    }
  }
  for(const [key,entries] of attributes) {
    const format=value=>typeof value==='string'?value:flag(value);
    const detail=document.createElement('p');
    const consistent=entries.every(e=>e.value===entries[0].value);
    detail.textContent=key.replaceAll('_',' ')+': '+(consistent?format(entries[0].value)+' ('+entries.map(e=>e.source).join(', ')+')':entries.map(e=>e.source+': '+format(e.value)).join('; '));
    if(entries.some(e=>e.value===true)) {
      detail.className='diagnostic-warning';
      const visible=document.createElement('p'); visible.className='diagnostic-warning'; visible.textContent=detail.textContent; section.append(visible);
    }
    details.append(detail);
  }
  section.append(details);
  const stamp = document.createElement('p');
  stamp.className='diagnostic-stamp';
  stamp.textContent = 'Last verified diagnostics: ' + displayTimestamp(data.read_at_utc || 'Unknown');
  section.append(stamp);
  return section;
}
async function refreshAddressStatus() {
  if(addressRefreshing) return;
  addressRefreshing=true;
  try {
    const state=await call('/api/address_status');
    if(state.address_search) renderAddressJob(state.address_search);
    renderAddressChange(state);
  } catch(e) {document.getElementById('error').textContent=e.message;}
  finally {addressRefreshing=false;}
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const state = await call('/api/meters');
    renderQuarantine(state.quarantine,state.address_change_enabled);
    // Address progress is refreshed independently of registry-backed views.
    if (state.raw_log) {
      const r=state.raw_log;
      document.getElementById('raw-status').textContent = 'Capture: '+(r.enabled?'On':'Off')+'; queued: '+r.queued+'; dropped: '+r.dropped+'; rotations: '+r.rotations+(r.storage_error?' · Storage error':'');
    }
    document.getElementById('status').textContent =
      `Søk: ${localText(state.scan_status)}, adresser sjekket: ${state.scan_progress}/251, ` +
      `uavklarte svar: ${state.scan_errors.length}, opprydding venter: ${state.cleanup_pending}. ` +
      `Historikk: ${localText(state.history.status)}` + (state.history.archive_position ? ` — archive ${state.history.archive_position}/24` : '') + (state.history.error ? ` – ${localText(state.history.error)}` : '');
    document.getElementById('clock-status').textContent =
      `Klokke: ${localText(state.clock.status)}. Systemtid nå: ${displayTimestamp(state.clock_target)}. ` +
      (state.clock.result ? `Før: ${displayTimestamp(state.clock.result.before || '—')}, mål: ${displayTimestamp(state.clock.result.target || 'ingen endring')}, etter: ${displayTimestamp(state.clock.result.after || '—')}. ` : '') +
      (state.clock.result && state.clock.result.dst_test ? `DST 1: ${state.clock.result.dst_test_results?.["1"] === true ? "PASS" : state.clock.result.dst_test_results?.["1"] === false ? "FAIL" : "NOT TESTED"}; DST 0: ${state.clock.result.dst_test_results?.["0"] === true ? "PASS" : state.clock.result.dst_test_results?.["0"] === false ? "FAIL" : "NOT TESTED"}; restored: ${state.clock.result.clock_restored ? "PASS" : "FAIL"}. ` : '') + (localText(state.clock.error) || '');
    if (state.history.archive_revision !== lastArchiveRevision ||
        (state.history.captured_at_utc && state.history.captured_at_utc !== lastHistoryCapture)) {
      await refreshHistory();
      lastHistoryCapture = state.history.captured_at_utc;
      lastArchiveRevision = state.history.archive_revision;
    }
    const busy = state.diagnostic_capture_running || historySubmitting || state.history.status === 'running' || state.clock.status === 'running' || state.scan_status === 'running';
    document.getElementById('scan').disabled = busy;
    const lists = JSON.stringify([busy, state.address_search_enabled, state.available, state.selected, state.history_enabled, state.history.status, state.history.manual_meter, state.history.stopping, state.clock_enabled, state.auto_clock_sync, state.clock.status, state.clock_target, state.migrations, state.dst_diagnostics, state.monthly_alarms, state.active_diagnostics]);
    if (lists !== lastLists) {
      lastLists = lists;
      const addressPanel=document.getElementById('address-panel');
      document.getElementById('address-panel-parking').append(addressPanel);
      if(addressMeter && !state.selected.some(item=>item.meter_id===addressMeter)) {
        addressPanel.hidden=true; addressMeter=null;
      }
    for (const name of ['available', 'selected']) {
      const div = document.getElementById(name); div.replaceChildren();
      for (const item of state[name]) {
        const line = document.createElement('div'); line.className = 'meter';
        line.textContent = `ID ${item.meter_id}, adresse ${item.address}` +
          (item.manufacturer ? `, ${item.manufacturer}` : '');
        if (name === 'selected') {
          if (state.address_search_enabled) {
            const addressHost=document.createElement('div'); addressHost.style.cssText='width:100%;min-width:0';
            line.append(button('Primary address',()=>openAddressPanel(item,addressHost)), addressHost);
            if(addressMeter===item.meter_id && !addressPanel.hidden) addressHost.append(addressPanel);
          }
          line.append(renderActiveDiagnostics((state.active_diagnostics || {})[item.meter_id] || {},item.meter_id));
          const flag = value => localText(value === true ? 'DST_ACTIVE' : value === false ? 'DST_INACTIVE' : 'DST_UNKNOWN');
          const alarm = (state.monthly_alarms || {})[item.meter_id] || {};
          const historyAlarm = document.createElement("p");
          historyAlarm.textContent = "Monthly history failed: " + flag(alarm.active);
          line.append(historyAlarm);
          if (alarm.active === true) {
            const ack = button("Acknowledge history failure", () => act("/api/ack_history", item.meter_id));
            line.append(ack);
          }
          const actions=document.createElement('div'); actions.className='meter-actions';
          const actionTitle=document.createElement('div'); actionTitle.className='meter-actions-title'; actionTitle.textContent='Meter operations'; actions.append(actionTitle);
          const remove = button('Fjern', () => act('/api/remove', item.meter_id)); remove.disabled = busy;
          const hist = button('Hent månedshistorikk', async () => {
            if (!confirm('Read monthly archive? Existing energy history is preserved. Missing extended months are read individually; a full archive can require over 90 minutes. Normal polling may pause. Continue?')) return;
            if (historySubmitting || hist.disabled) return;
            historySubmitting = true;
            hist.disabled = true;
            try { await call('/api/history', {meter_id:item.meter_id, confirm:true}); document.getElementById('error').textContent=''; }
            catch (e) { document.getElementById('error').textContent=e.message; }
            finally { historySubmitting=false; lastLists=''; await refresh(); }
          });
          const migration = state.migrations[item.meter_id];
          hist.disabled = busy || !state.history_enabled || state.history.status === 'restore_unverified' || migration === "pending" || migration === "invalid";
          if (migration === "pending") {
            const migrate = button("Migrate historical data", async () => {
              await act("/api/migrate", item.meter_id);
              await refreshHistory();
            });
            migrate.disabled = busy;
            actions.append(migrate);
          }
          actions.append(hist);
          if (state.history.manual_meter === item.meter_id) {
            const stopHistory = button(state.history.stopping ? 'Stopping…' : 'Stop', async () => {
              stopHistory.disabled = true;
              try { await call('/api/stop_history', {meter_id:item.meter_id}); }
              catch (e) { document.getElementById('error').textContent=e.message; }
              finally { lastLists=''; await refresh(); }
            });
            stopHistory.disabled = state.history.stopping;
            actions.append(stopHistory);
          }
          const clock = button('Synkroniser målerklokke', async () => {
            if (!confirm('Sette målerens klokke til systemtid i ' + state.clock_target + '? Dette skriver til måleren. Fortsette?')) return;
            try { await call('/api/clock', {meter_id:item.meter_id, confirm:true}); document.getElementById('error').textContent=''; await refresh(); }
            catch (e) { document.getElementById('error').textContent=e.message; }
          });
          clock.disabled = busy || !state.clock_enabled || state.history.status === 'restore_unverified';
          actions.append(clock); line.append(actions);
          const admin=document.createElement("div"); admin.className="meter-admin";
          const adminTitle=document.createElement("strong"); adminTitle.textContent="Meter administration"; admin.append(adminTitle,document.createElement("br"),remove); line.append(admin);
        }
        else if (item.supported) { const add=button('Legg til', () => act('/api/select', item.meter_id)); add.disabled=busy; line.append(add); }
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
document.getElementById('export').onclick = async () => {
  try {
    const res = await fetch(root + '/api/export.xlsx');
    if (!res.ok) {
      const data = await res.json(); throw new Error(localText(data.error) || 'Ingen data tilgjengelig');
    }
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement('a'); link.href = url;
    link.download = 'mbus-analysis.xlsx'; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    document.getElementById('error').textContent = '';
  } catch (e) { document.getElementById('error').textContent = e.message; }
};
document.getElementById('raw-download').onclick=async()=>{
  if (!confirm('Raw export may contain meter identifiers and consumption. Review before sharing. Continue?')) return;
  try {
    const res=await fetch(root+'/api/raw.jsonl');
    if (!res.ok) throw new Error('Raw export unavailable');
    const url=URL.createObjectURL(await res.blob());
    const link=document.createElement('a'); link.href=url; link.download='mbus-raw.txt';
    document.body.append(link); link.click(); link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  } catch(e) { document.getElementById('error').textContent=e.message; }
};

let pdState={enabled:false};
let pdSubmitting=false;
let pdRefreshing=false;
let pdGeneration=0;
let pdLastFile=null;
const pdEl=id=>document.getElementById(id);
function pdBody(){
  const numeric=id=>pdEl(id).value.trim()===''?NaN:Number(pdEl(id).value);
  return {meter_id:pdEl('pd-id').value,manufacturer:pdEl('pd-manufacturer').value,
    version:numeric('pd-version'),medium:numeric('pd-medium'),number:pdEl('pd-number').value,
    address:numeric('pd-address')};
}
function pdValid(b){
  return /^[0-9]{8}$/.test(b.meter_id)&&/^[A-Z]{3}$/.test(b.manufacturer)&&
    /^[0-9]{8}$/.test(b.number)&&Number.isInteger(b.version)&&b.version>=0&&b.version<=254&&
    Number.isInteger(b.medium)&&b.medium>=0&&b.medium<=254&&Number.isInteger(b.address)&&b.address>=0&&b.address<=250;
}
function renderProtocolDiagnostic(state){
  pdState=state||{enabled:false};
  const enabled=pdState.enabled===true;
  const recovery=pdState.recovery_required===true;
  const busy=pdSubmitting||pdState.status==='running';
  const pending=pdState.pending;
  pdEl('protocol-diagnostic-panel').hidden=!enabled&&!recovery;
  pdEl('protocol-diagnostic-fields').disabled=busy||recovery||!enabled;
  pdEl('pd-single').disabled=busy||!enabled;
  pdEl('pd-start').hidden=recovery;
  pdEl('pd-start').disabled=!enabled||busy||recovery||!pdEl('pd-single').checked||!pdValid(pdBody());
  pdEl('pd-recover').hidden=!recovery;
  pdEl('pd-recover').disabled=!enabled||busy||!pending||!pdEl('pd-single').checked;
  pdEl('pd-status').textContent=(pdState.status||'idle')+(pdState.cleanup_verified===true?' — cleanup verified':'')+
    (pdState.selected_address!=null?' — selected response address '+pdState.selected_address:'');
  pdEl('pd-pending').textContent=recovery?(pending?'Pending recovery: ID '+pending.identity.meter_id+
    ', address '+pending.address+', fabrication number '+pending.number:
    'Diagnostic recovery required; pending record unavailable or diagnostic disabled. Do not remove the guard.'):'';
  if(pdState.evidence_file&&pdState.evidence_file!==pdLastFile){
    pdLastFile=pdState.evidence_file;pdEl('pd-file').value=pdLastFile;
  }
  pdEl('pd-download').disabled=!enabled||busy||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$/.test(pdEl('pd-file').value);
}
async function refreshProtocolDiagnostic(){
  if(pdRefreshing||pdSubmitting)return;
  pdRefreshing=true;const generation=pdGeneration;
  try{const state=await call('/api/address_diagnostic_status');
    if(generation===pdGeneration&&!pdSubmitting)renderProtocolDiagnostic(state);
  }catch(e){pdEl('error').textContent=e.message;}
  finally{pdRefreshing=false;}
}
async function submitProtocolDiagnostic(recovery){
  if(pdSubmitting||pdState.status==='running'||pdState.enabled!==true||
     !pdEl('pd-single').checked||recovery!==(pdState.recovery_required===true))return;
  let body=pdBody();
  if(recovery){
    const p=pdState.pending;if(!p)return;
    body={...p.identity,number:p.number,address:p.address,guard_id:p.id};
  }
  if(!pdValid(body))return;
  if(!confirm((recovery?'Recover diagnostic session':'Run isolated protocol test')+
    ' for ID '+body.meter_id+' at address '+body.address+'? Normal polling may pause.'))return;
  pdSubmitting=true;pdGeneration++;pdEl('pd-single').checked=false;renderProtocolDiagnostic(pdState);
  try{const state=await call(recovery?'/api/diagnostic_recover':'/api/address_diagnostic',
    {...body,confirm:true,single_meter:true,recovery});renderProtocolDiagnostic(state);}
  catch(e){pdEl('error').textContent=e.message;}
  finally{pdSubmitting=false;renderProtocolDiagnostic(pdState);await refreshProtocolDiagnostic();}
}
async function downloadProtocolEvidence(){
  if(pdEl('pd-download').disabled)return;
  if(!confirm('Private diagnostic evidence may contain meter identifiers and measurements. Review before sharing.'))return;
  const name=pdEl('pd-file').value;
  try{
    const response=await fetch(root+'/api/address_diagnostic_evidence/'+encodeURIComponent(name));
    if(!response.ok)throw new Error('Evidence unavailable');
    const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');
    link.href=url;link.download=name;document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  }catch(e){pdEl('error').textContent=e.message;}
}
for(const id of ['pd-id','pd-manufacturer','pd-version','pd-medium','pd-number','pd-address','pd-single','pd-file'])
  pdEl(id).oninput=()=>renderProtocolDiagnostic(pdState);
pdEl('pd-start').onclick=()=>submitProtocolDiagnostic(false);
pdEl('pd-recover').onclick=()=>submitProtocolDiagnostic(true);
pdEl('pd-download').onclick=downloadProtocolEvidence;
setInterval(refreshProtocolDiagnostic,1500);refreshProtocolDiagnostic();

setInterval(refreshAddressStatus, 1500); refreshAddressStatus();
setInterval(refresh, 1500); refreshHistory(); refresh();
</script></html>"""


def render_page(language):
    """Translate presentation literals only; never rewrite routes or state keys."""
    # Replace in a single pass so translated text is never translated again.
    import re
    language = resolve_language(language)
    page = PAGE.replace('lang="no"', 'lang="' + language + '"', 1)
    html, script = page.split("<script>", 1)
    keys = sorted(TRANSLATIONS, key=len, reverse=True)
    def translate(key):
        return TRANSLATIONS[key].get(language, TRANSLATIONS[key]["en-GB"])
    # Match complete HTML text nodes, not attributes or substrings of CSS.
    html = re.sub(r">([^<>]+)<", lambda m: ">" + escape(translate(m[1])) + "<"
                  if m[1] in TRANSLATIONS else m[0], html)
    # JS strings and template fragments in the trusted static page.
    # Apostrophes/backticks and template interpolation must remain escaped.
    def js_text(key):
        return (translate(key).replace("\\", "\\\\").replace("'", "\\'")
                .replace("`", "\\`").replace("${", "\\${")
                .replace("<", "\\x3c").replace("\n", "\\n").replace("\r", "\\r"))
    # Match complete quoted strings or literal template fragments only.
    # Do not search arbitrary JavaScript identifiers or executable expressions.
    for key in keys:
        quoted = "'" + key + "'"
        if quoted in script:
            script = script.replace(quoted, "'" + js_text(key) + "'")
    fragments = ("Søk: ", ", adresser sjekket: ", "uavklarte svar: ",
                 ", opprydding venter: ", "Historikk: ", "Klokke: ",
                 ". Systemtid nå: ", "Før: ", ", mål: ", ", etter: ", ", adresse ")
    pattern = re.compile("|".join(re.escape(k) for k in fragments))
    script = pattern.sub(lambda m: js_text(m[0]), script)
    display = {key: values.get(language, values["en-GB"]) for key, values in STATUS_TEXT.items()}
    prefix = "const displayText = " + json.dumps(display, ensure_ascii=True).replace("<", "\\u003c") + ";\n"
    prefix += "const localText = value => Object.prototype.hasOwnProperty.call(displayText, value) ? displayText[value] : value;\n"
    return html + "<script>" + prefix + script


def serve(registry, config, client, bus_lock, stop, port=8099, history_controller=None, clock_controller=None, raw_log=None, address_search_job=None, address_change_job=None, address_safety_blocked=None, address_diagnostic_factory=None):
    history_controller = history_controller or HistoryController(
        registry, config, bus_lock, stop,
        on_complete=lambda meter_id, snapshot: publish_history(client, meter_id, snapshot))
    clock_controller = clock_controller or ClockController(registry, config, bus_lock, stop,
                                                           history_blocked=history_controller.blocked)
    capture_lock = threading.Lock()
    capture_state = {"status": "not_started"}

    def diagnostic_capture(meter_id):
        try:
            from frame5_capture import redact_capture
            result = history_controller.capture_diagnostic_dev(meter_id, approved=True)
            safe = redact_capture(result)
            status = "normal_layout_detected" if safe.get("normal_layout_detected") else "complete"
            if status == "complete" and config.get("_frame5_layout_approved") is True:
                from frame5_layout import extract_abcdef
                frame = bytes.fromhex(result["response_hex"])
                raw = extract_abcdef(frame, frame[5], meter_id)
                config["_diagnostic_runtime"].observe_verified(
                    meter_id, raw, result["read_at_utc"], layout_verified=True)
                safe["layout_verified"] = True
                status = "verified"
            with capture_lock:
                capture_state.update(status=status, evidence=safe)
        except (ValueError, OSError, RuntimeError):
            with capture_lock:
                capture_state.update(status="failed", evidence=None)

    def capture_status():
        with capture_lock:
            return capture_state['status']

    def capture_running():
        with capture_lock:
            return capture_state["status"] == "running"

    admission = OperationAdmission()
    address_diagnostic_job = address_diagnostic_factory(admission,history_controller.blocked.is_set) if address_diagnostic_factory else None
    admission.register("address_diagnostic", lambda: address_diagnostic_job is not None and address_diagnostic_job.busy())
    admission.register("history", lambda: history_controller.snapshot()["status"] == "running")
    admission.register("clock", lambda: clock_controller.snapshot()["status"] == "running")
    admission.register("diagnostic_capture", capture_running)
    admission.register("address_search", lambda: address_search_job is not None and
                       address_search_job.snapshot()["status"] in ("running", "stopping"))
    admission.register("address_change", lambda: address_change_job is not None and
                       address_change_job.snapshot()["status"] == "running")
    admission.register("scan", lambda: registry.snapshot()["scan_status"] == "running")
    admission.register("address_safety", lambda: bool(address_safety_blocked and address_safety_blocked()))

    def guard_start(obj, method, name):
        original = getattr(obj, method)
        def guarded(*args, **kwargs):
            with admission.start(name):
                return original(*args, **kwargs)
        setattr(obj, method, guarded)

    # The maintenance scheduler uses these same controller instances.
    guard_start(history_controller, "start", "history")
    guard_start(history_controller, "start_extended_archive", "history")
    guard_start(history_controller, "capture_diagnostic_dev", "diagnostic_capture")
    guard_start(clock_controller, "start", "clock")
    if address_search_job:
        guard_start(address_search_job, "start", "address_search")
    if address_change_job:
        guard_start(address_change_job, "start", "address_change")
        guard_start(address_change_job, "recover", "address_recover")
        guard_start(address_change_job, "quarantine_action", "address_quarantine")

    def dst_diagnostics():
        result = {}
        for row in registry.snapshot()["selected"]:
            meter_id = row["meter_id"]
            try:
                state = TransitionStore("/data/analysis", meter_id).load()
                result[meter_id] = {k: state.get(k) for k in
                                    ("dst_transition_failed", "dst_clock_override", "last_transition")}
            except (OSError, ValueError, TypeError):
                result[meter_id] = {"dst_transition_failed": None, "dst_clock_override": None}
        return result

    def monthly_alarm(meter_id):
        key = "history:" + hashlib.sha256(meter_id.encode()).hexdigest()
        try:
            return MonthlyRetry("/data/analysis").alarm(key)
        except (OSError, ValueError):
            return {"active": None}

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
            if self.path.rstrip("/").endswith("/api/address_diagnostic_status"):
                self._send(200,address_diagnostic_job.snapshot() if address_diagnostic_job else {"enabled":False})
                return
            if "/api/address_diagnostic_evidence/" in self.path:
                try:
                    if address_diagnostic_job is None:
                        raise ValueError("diagnostic unavailable")
                    name=self.path.rsplit("/",1)[-1]
                    payload=address_diagnostic_job.export(name)
                except (OSError,ValueError):
                    self._send(404,{"error":"evidence unavailable"})
                    return
                self.send_response(200)
                self.send_header("Content-Type","application/x-ndjson")
                self.send_header("Content-Disposition",'attachment; filename="'+name+'"')
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length",str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path.rstrip("/").endswith("/api/address_status"):
                self._send(200, {
                    "address_search_enabled": address_search_job is not None,
                    "address_change_enabled": address_change_job is not None,
                    "address_search": address_search_job.snapshot() if address_search_job else None,
                    "address_change": address_change_job.snapshot() if address_change_job else None})
                return
            if self.path.rstrip("/").endswith("/api/meters"):
                self._send(200, {**registry.snapshot(), "address_search_enabled": address_search_job is not None,
                                 "address_change_enabled": address_change_job is not None,
                                 "address_change": address_change_job.snapshot() if address_change_job else None,
                                 "address_search": address_search_job.snapshot() if address_search_job else None,
                                 "history": history_controller.snapshot(),
                                 "migrations": {r["meter_id"]: history_controller.migration_status(r["meter_id"]) for r in registry.snapshot()["selected"]},
                                 "raw_log": raw_log.status() if raw_log else None,
                                 "dst_diagnostics": dst_diagnostics(),
                                 "diagnostic_capture_enabled": config.get("allow_diagnostic_capture") is True,
                                 "diagnostic_capture_running": capture_running(),
                                 "diagnostic_capture_status": capture_status(),
                                 "active_diagnostics": {r["meter_id"]: config["_diagnostic_runtime"].snapshot(r["meter_id"])
                                                        if config.get("_diagnostic_runtime") else {"battery_status":"unknown"}
                                                        for r in registry.snapshot()["selected"]},
                                 "monthly_alarms": {r["meter_id"]: monthly_alarm(r["meter_id"]) for r in registry.snapshot()["selected"]},
                                 "history_enabled": config.get("allow_monthly_history", False),
                                 "clock": clock_controller.snapshot(),
                                 "clock_enabled": config.get("allow_clock_sync", False),
                                 "auto_clock_sync": config.get("auto_clock_sync", False),
                                 "clock_target": configured_local(datetime.now(ZoneInfo("UTC")), config.get("clock_timezone", "Europe/Oslo")).isoformat(timespec="minutes")})
            elif self.path.rstrip("/").endswith("/api/diagnostic_capture"):
                with capture_lock:
                    self._send(200, dict(capture_state))
            elif self.path.rstrip("/").endswith("/api/history"):
                try:
                    entries = [{"alias": alias, "snapshot": snapshot,
                                "stored_progress": stored_archive_progress(snapshot)} for alias, snapshot in
                               load_history("/data/analysis", registry.snapshot()["selected"])]
                except (OSError, ValueError, KeyError):
                    self._send(409, {"error": "Lagret historikk kunne ikke leses"})
                    return
                from history_controller import history_file
                job = history_controller.snapshot()
                meter = job.get("archive_meter")
                alias = history_file(history_controller.root,meter).stem if meter else None
                self._send(200, {"histories": entries, "archive_alias":alias,
                                 "archive_progress":job.get("archive_progress",{})})
            elif self.path.endswith("/api/raw.jsonl"):
                try:
                    if raw_log is None:
                        raise OSError("raw log unavailable")
                    payload = raw_log.snapshot()
                except OSError:
                    self._send(409, {"error": "Raw export unavailable"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="mbus-raw.txt"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path.endswith("/api/export.xlsx"):
                try:
                    payload = make_xlsx(load_samples("/data/analysis/normal.jsonl"),
                                        load_history("/data/analysis", registry.snapshot()["selected"]),
                                        language="en-GB",
                                        temperature_unit=None)
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
                self._send(200, render_page("en-GB"), "text/html")
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.client_address[0] != "172.30.32.2":
                self._send(403, {"error": "ingress required"})
                return
            route = self.path.rsplit("/", 2)[-1]
            if route not in ("scan", "select", "auto", "remove", "history", "clock", "migrate", "ack_history", "stop_history", "diagnostic_capture", "address_search", "address_stop", "address_change", "address_recover", "address_quarantine", "address_diagnostic", "diagnostic_recover"):
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 4096:
                    raise ValueError("invalid request length")
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("request must be a JSON object")
                meter_id = data.get("meter_id")
                if meter_id is not None and not isinstance(meter_id, str):
                    raise ValueError("meter_id must be text")
                if route in ("stop_history", "address_stop", "ack_history"):
                    self._dispatch(route, meter_id, data)
                else:
                    with admission.start(route):
                        self._dispatch(route, meter_id, data)
            except (ValueError, KeyError, ConnectionError, OSError) as exc:
                self._send(400, {"error": str(exc)})

        def _dispatch(self, route, meter_id, data):
            if route in ("address_diagnostic","diagnostic_recover"):
                if address_diagnostic_job is None or not address_diagnostic_job.enabled:
                    raise ValueError("diagnostic not enabled")
                if data.get("recovery",False) is not (route=="diagnostic_recover"):
                    raise ValueError("diagnostic route mismatch")
                address_diagnostic_job.start(data)
                self._send(202,address_diagnostic_job.snapshot())
                return
            if route == "address_quarantine":
                if address_change_job is None or history_controller.blocked.is_set():
                    raise ValueError("quarantine action unavailable")
                address_change_job.quarantine_action(meter_id, data.get("address"),
                    action=data.get("action"), confirmed=data.get("confirm"),
                    new_address=data.get("new_address"))
                self._send(202, address_change_job.snapshot())
                return
            if route == "address_recover":
                if address_change_job is None or history_controller.blocked.is_set():
                    raise ValueError("address recovery unavailable")
                address_change_job.recover(meter_id, data.get("transaction_id"), confirmed=data.get("confirm"))
                self._send(202, address_change_job.snapshot())
                return
            if route == "address_change":
                if address_change_job is None:
                    raise ValueError("address change not enabled")
                if (history_controller.blocked.is_set() or history_controller.snapshot()["status"] == "running"
                        or clock_controller.snapshot()["status"] == "running" or capture_running()
                        or (address_search_job and address_search_job.snapshot()["status"] in ("running", "stopping"))):
                    raise ValueError("bus unavailable")
                address_change_job.start(meter_id, data.get("old_address"), data.get("new_address"),
                                         confirmed=data.get("confirm"), override=data.get("override", False),
                                         accepted_risk=data.get("accepted_risk"))
                self._send(202, address_change_job.snapshot())
                return
            if route in ("address_search", "address_stop"):
                if address_change_job and address_change_job.snapshot()["status"] == "running":
                    raise ValueError("address change running")
                if address_search_job is None:
                    raise ValueError("address search not enabled")
                if route == "address_stop":
                    address_search_job.request_stop(meter_id)
                else:
                    if history_controller.blocked.is_set() or history_controller.snapshot()["status"] == "running" or clock_controller.snapshot()["status"] == "running" or capture_running():
                        raise ValueError("bus unavailable")
                    if "resume" in data:
                        address_search_job.start(meter_id, data.get("first"), data.get("last"), resume=data["resume"])
                    else:
                        address_search_job.start(meter_id, data.get("first"), data.get("last"))
                self._send(202, address_search_job.snapshot())
                return
            if route == "stop_history":
                history_controller.request_stop(meter_id)
                self._send(200, registry.snapshot())
                return
            if route == "ack_history":
                with registry.lock:
                    if meter_id not in registry.selected:
                        raise ValueError("meter not selected")
                key = "history:" + hashlib.sha256(meter_id.encode()).hexdigest()
                ledger = MonthlyRetry("/data/analysis")
                ledger.acknowledge(key)
                publish_monthly_retry(client, meter_id, ledger.alarm(key))
                self._send(200, registry.snapshot())
                return
            if history_controller.blocked.is_set():
                raise ValueError("Normal telegram not yet verified")
            if history_controller.snapshot()["status"] == "running":
                raise ValueError("History retrieval already running")
            with capture_lock:
                if capture_state["status"] == "running":
                    raise ValueError("diagnostic capture already running")
            if route == "diagnostic_capture":
                if config.get("allow_diagnostic_capture") is not True or data.get("confirm") is not True:
                    raise ValueError("diagnostic capture requires explicit permission and confirmation")
                if stop.is_set() or clock_controller.snapshot().get("status") == "running":
                    raise ValueError("bus unavailable")
                with registry.lock:
                    if len(registry.selected) != 1 or meter_id not in registry.selected or registry.scan_status == "running":
                        raise ValueError("one selected meter and idle scanner required")
                with capture_lock:
                    if capture_state["status"] == "running":
                        raise ValueError("diagnostic capture already running")
                    capture_state.update(status="running", evidence=None)
                threading.Thread(target=diagnostic_capture, args=(meter_id,), daemon=True).start()
                self._send(202, {"status": "running"})
                return
            if route == "scan":
                with registry.lock:
                    if registry.scan_status == "running":
                        raise ValueError("scan already running")
                    registry.scan_status = "running"
                    registry.scan_progress = 0
                    registry.scan_errors = []
                    registry.found = {}
                threading.Thread(target=scan_bus, args=(config["serial_port"],
                                 int(config.get("baud", 2400)), registry, bus_lock, stop, history_controller.blocked),
                                 daemon=True).start()
            elif route == "migrate":
                history_controller.migrate(meter_id)
            elif route == "history":
                if history_controller.migration_status(meter_id) == "complete":
                    history_controller.start_extended_archive(meter_id,confirmed=data.get("confirm"))
                else:
                    history_controller.start(meter_id, manual=True)
            elif route == "clock":
                if history_controller.migration_status(meter_id) in ("pending", "invalid"):
                    raise ValueError("migrate saved history before clock synchronization")
                if data.get("confirm") is not True:
                    raise ValueError("clock write requires explicit confirmation")
                if data.get("test_dst") is True:
                    raise ValueError("Experimental DST writes are retired")
                clock_controller.start(meter_id)
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

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.history_controller = history_controller
    server.clock_controller = clock_controller
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
