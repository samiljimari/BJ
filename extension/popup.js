'use strict';

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);
const send = (m) => api.runtime.sendMessage(m);
const originOf = (url) => { try { const u = new URL(url); return /^https?:$/.test(u.protocol) ? u.origin : null; } catch (e) { return null; } };
const patternOf = (origin) => { const u = new URL(origin); return `${u.protocol}//${u.hostname}/*`; };
const hostKey = (origin) => { const u = new URL(origin); return `${u.protocol}//${u.hostname}`; };

let tabId = null;

async function enabledOrigins() {
  const { origins = [] } = await api.storage.local.get('origins');
  return origins;
}

function enable(origin) {
  // Runs synchronously inside the click handler: the permission request must be
  // made while the click is still being handled.
  const key = hostKey(origin);
  // Firefox may close this popup when its permission prompt opens, so the background
  // records the origin as pending and completes the registration on permissions.onAdded.
  send({ kind: 'pending-origin', origin: key });
  api.permissions.request({ origins: [patternOf(origin)] }).then(async (granted) => {
    if (granted) await send({ kind: 'add-origin', origin: key });
    refresh();
  }, () => refresh());
}

async function disable(origin) {
  await send({ kind: 'remove-origin', origin });
  try { await api.permissions.remove({ origins: [patternOf(origin)] }); } catch (e) { /* localhost is required */ }
  refresh();
}

function item(label, btnText, onClick, cls) {
  const d = document.createElement('div');
  d.className = 'item';
  const c = document.createElement('code');
  c.textContent = label;
  c.title = label;
  const b = document.createElement('button');
  b.textContent = btnText;
  if (cls) b.className = cls;
  b.addEventListener('click', onClick);
  d.append(c, b);
  return d;
}

async function refresh() {
  const enabled = await enabledOrigins();

  // frames of the active tab
  const fr = $('frames');
  fr.textContent = '';
  if (tabId != null) {
    let frames = [];
    try { frames = (await api.webNavigation.getAllFrames({ tabId })) || []; } catch (e) { /* no access */ }
    const origins = [...new Set(frames.map((f) => originOf(f.url)).filter(Boolean))];
    if (!origins.length) fr.textContent = 'No http(s) frames.';
    for (const o of origins) {
      const on = enabled.includes(hostKey(o));
      fr.appendChild(item(o, on ? 'enabled' : 'Enable', on ? () => disable(hostKey(o)) : () => enable(o), on ? 'on' : ''));
    }
  }

  const og = $('origins');
  og.textContent = enabled.length ? '' : 'none';
  for (const o of enabled) og.appendChild(item(o, 'Remove', () => disable(o)));

  let st = null;
  try { st = await send({ kind: 'status' }); } catch (e) { /* background starting */ }
  $('dot').classList.toggle('up', !!(st && st.connected));
  $('srv').textContent = st && st.connected ? 'server: connected' : 'server: offline';
  if (document.activeElement !== $('url')) $('url').value = st ? st.url : '';
  const s = st && st.state;
  const status = $('status');
  status.textContent = '';
  if (s) {
    const src = s.source || {};
    const rec = src.recorder || {};
    const p = src.parser || {};
    const lines = [
      `TC ${s.shoe.true_count.toFixed(1)} · RC ${s.shoe.running_count} · ${s.shoe.cards_seen} cards · shoe #${s.shoe.shoe_number}`,
      `${s.bet.label}${s.bet.amount_label ? ' = ' + s.bet.amount_label : ''}`,
      `parser ${p.parser}: ${p.frames_seen} frames → ${p.events_out} events`,
      `forwarded ${st.stats.forwarded}, buffered ${st.stats.buffered}, dropped ${st.stats.dropped}`,
    ];
    for (const l of lines) { const d = document.createElement('div'); d.textContent = l; status.appendChild(d); }
    if (rec.recording) {
      const d = document.createElement('div');
      d.className = 'rec';
      d.textContent = `● recording ${rec.file} (${rec.frames} frames)`;
      status.appendChild(d);
    }
    $('rec').textContent = rec.recording ? 'Stop recording' : 'Record frames';
    $('rec').dataset.on = rec.recording ? '1' : '';
  } else {
    status.textContent = st && st.connected ? 'Connected, no state yet.' : 'Start the server: python -m server.main';
  }

  const { overlayMode = 'game' } = await api.storage.local.get('overlayMode');
  $('mode').value = overlayMode;
}

$('reload').addEventListener('click', () => { if (tabId != null) api.tabs.reload(tabId); window.close(); });
$('rec').addEventListener('click', async () => {
  await send({ kind: 'control', action: $('rec').dataset.on ? 'record_stop' : 'record_start' });
  setTimeout(refresh, 300);
});
$('reset').addEventListener('click', async () => {
  if (confirm('Start a new shoe? (count resets to 0)')) await send({ kind: 'control', action: 'reset_shoe' });
  setTimeout(refresh, 300);
});
$('undo').addEventListener('click', async () => { await send({ kind: 'control', action: 'undo' }); setTimeout(refresh, 300); });
$('mode').addEventListener('change', async () => {
  const overlayMode = $('mode').value;
  await api.storage.local.set({ overlayMode });
  await send({ kind: 'overlay', settings: { overlayMode } });
});
$('toggle').addEventListener('click', () => send({ kind: 'overlay', toggle: true }));
$('save').addEventListener('click', async () => {
  await api.storage.local.set({ serverUrl: $('url').value.trim() });
  await send({ kind: 'reconnect' });
  setTimeout(refresh, 500);
});

api.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
  tabId = tab ? tab.id : null;
  refresh();
  setInterval(refresh, 1500);
});
