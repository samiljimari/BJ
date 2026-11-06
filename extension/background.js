/* Background script - Firefox event page (background.scripts) / Chrome service worker.
 * - registers hook.js (MAIN world) + relay.js in the origins the user enabled
 * - keeps one WebSocket to the local counter server and relays:
 *     content scripts --(copied frames, counter controls)--> server
 *     server --(state)--> every content script (overlay)
 * ADVICE ONLY: nothing here (or in any content script) ever sends anything to the
 * game, clicks, or places bets. See README "Advice only". */
'use strict';

const api = globalThis.browser ?? globalThis.chrome;
const DEFAULT_SERVER = 'ws://127.0.0.1:8765/ws';
const ports = new Set();
let ws = null;
let wsOpen = false;
let backoff = 1000;
let lastState = null;
let reconnectTimer = null;
const buffer = [];           // frames queued while the server is down
const stats = { forwarded: 0, dropped: 0, buffered: 0 };

// ------------------------------------------------------------ content scripts
const toPattern = (origin) => {
  const u = new URL(origin);
  return `${u.protocol}//${u.hostname}/*`; // match patterns ignore ports
};

async function desiredMatches() {
  const { origins = [] } = await api.storage.local.get('origins');
  const out = [];
  for (const o of origins) {
    const pattern = toPattern(o);
    // Only origins the user actually granted (they can revoke in the add-ons manager).
    if (await api.permissions.contains({ origins: [pattern] })) out.push(pattern);
  }
  return [...new Set(out)].sort();
}

async function syncScripts(force = false) {
  const matches = await desiredMatches();
  const existing = (await api.scripting.getRegisteredContentScripts()).filter((s) => s.id.startsWith('bjc-'));
  const current = [...new Set(existing.flatMap((s) => s.matches || []))].sort();
  if (!force && existing.length === 2 && JSON.stringify(current) === JSON.stringify(matches)) {
    return { ok: true, matches, changed: false };
  }
  if (existing.length) await api.scripting.unregisterContentScripts({ ids: existing.map((s) => s.id) });
  if (!matches.length) return { ok: true, matches, changed: true };
  const scripts = (fallback) => [
    { id: 'bjc-hook', js: ['hook.js'], matches, runAt: 'document_start', allFrames: true, world: 'MAIN',
      persistAcrossSessions: true, ...(fallback ? { matchOriginAsFallback: true } : {}) },
    { id: 'bjc-relay', js: ['panel_render.js', 'relay.js'], matches, runAt: 'document_start', allFrames: true,
      persistAcrossSessions: true, ...(fallback ? { matchOriginAsFallback: true } : {}) },
  ];
  try {
    await api.scripting.registerContentScripts(scripts(true));
  } catch (e) {
    await api.scripting.registerContentScripts(scripts(false)); // matchOriginAsFallback unsupported
  }
  return { ok: true, matches, changed: true };
}

async function addOrigin(origin) {
  const { origins = [], pending = [] } = await api.storage.local.get(['origins', 'pending']);
  await api.storage.local.set({
    origins: [...new Set([...origins, origin])],
    pending: pending.filter((p) => p !== origin),
  });
  return syncScripts();
}

// The popup asks for the permission. In Firefox the permission prompt can close the
// popup before its promise resolves, so the popup also records the origin as
// "pending" and we finish the job here when the permission arrives.
api.permissions.onAdded.addListener(async (perm) => {
  const granted = new Set((perm.origins || []));
  const { pending = [] } = await api.storage.local.get('pending');
  for (const o of pending) {
    if (granted.has(toPattern(o))) await addOrigin(o);
  }
});
api.permissions.onRemoved.addListener(() => { syncScripts().catch(console.error); });
api.runtime.onInstalled.addListener(() => { syncScripts(true).catch(console.error); });
api.runtime.onStartup.addListener(() => { syncScripts().catch(console.error); });

// --------------------------------------------------------------------- server
async function serverUrl() {
  const { serverUrl } = await api.storage.local.get({ serverUrl: DEFAULT_SERVER });
  return serverUrl || DEFAULT_SERVER;
}

async function connectServer() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  clearTimeout(reconnectTimer);
  let sock;
  try {
    sock = new WebSocket(await serverUrl());
  } catch (e) {
    scheduleReconnect();
    return;
  }
  ws = sock;
  sock.onopen = () => {
    wsOpen = true;
    backoff = 1000;
    sock.send(JSON.stringify({ kind: 'hello', role: 'ext' }));
    broadcast({ kind: 'server', connected: true });
    while (buffer.length && wsOpen) sendServer(buffer.shift());
    stats.buffered = 0;
  };
  sock.onmessage = (e) => {
    let m;
    try { m = JSON.parse(e.data); } catch (err) { return; }
    // The server only ever sends display state and keep-alive pings.
    if (m.kind === 'state') {
      lastState = m.state;
      broadcast({ kind: 'state', state: m.state });
    }
  };
  sock.onclose = () => {
    if (ws === sock) { ws = null; wsOpen = false; }
    broadcast({ kind: 'server', connected: false });
    scheduleReconnect();
  };
  sock.onerror = () => { /* onclose follows */ };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connectServer, backoff);
  backoff = Math.min(backoff * 2, 10000);
}

function sendServer(m) {
  if (ws && wsOpen) {
    ws.send(JSON.stringify(m));
    stats.forwarded++;
    return true;
  }
  if (m.kind === 'frame' || m.kind === 'ws_open' || m.kind === 'ws_close') {
    buffer.push(m);
    stats.buffered = buffer.length;
    if (buffer.length > 50000) { buffer.shift(); stats.dropped++; }
  }
  connectServer();
  return false;
}

function broadcast(m) {
  for (const p of ports) {
    try { p.postMessage(m); } catch (e) { ports.delete(p); }
  }
}

// ----------------------------------------------------------- relay connections
const FROM_RELAY = new Set(['frame', 'ws_open', 'ws_close', 'control']);

api.runtime.onConnect.addListener((port) => {
  if (port.name !== 'bjc-relay') return;
  ports.add(port);
  port.postMessage({ kind: 'server', connected: wsOpen });
  if (lastState && wsOpen) port.postMessage({ kind: 'state', state: lastState });
  port.onMessage.addListener((m) => {
    if (!m || m.kind === 'ping') return; // keep-alive for the Firefox event page
    if (!FROM_RELAY.has(m.kind)) return;
    const sender = port.sender || {};
    if (m.kind !== 'control') {
      m.tab = sender.tab ? sender.tab.id : null;
      m.frame_id = sender.frameId;
    }
    sendServer(m);
  });
  port.onDisconnect.addListener(() => ports.delete(port));
  connectServer();
});

// ------------------------------------------------------------- popup / command
api.runtime.onMessage.addListener((m, sender, reply) => {
  (async () => {
    if (m.kind === 'status') {
      reply({ connected: wsOpen, url: await serverUrl(), stats, ports: ports.size, state: lastState });
    } else if (m.kind === 'pending-origin') {
      const { pending = [] } = await api.storage.local.get('pending');
      await api.storage.local.set({ pending: [...new Set([...pending, m.origin])] });
      reply({ ok: true });
    } else if (m.kind === 'add-origin') {
      reply(await addOrigin(m.origin));
    } else if (m.kind === 'remove-origin') {
      const { origins = [] } = await api.storage.local.get('origins');
      await api.storage.local.set({ origins: origins.filter((o) => o !== m.origin) });
      reply(await syncScripts());
    } else if (m.kind === 'sync') {
      reply(await syncScripts(true));
    } else if (m.kind === 'control') {
      reply({ sent: sendServer({ kind: 'control', action: m.action }) });
    } else if (m.kind === 'overlay') {
      broadcast({ kind: 'overlay', toggle: !!m.toggle, settings: m.settings });
      reply({ ok: true });
    } else if (m.kind === 'reconnect') {
      if (ws) try { ws.close(); } catch (e) { /* ignore */ }
      ws = null; wsOpen = false; backoff = 1000;
      await connectServer();
      reply({ ok: true });
    } else {
      reply({ error: 'unknown' });
    }
  })().catch((e) => reply({ error: String(e) }));
  return true; // async reply (Chrome + Firefox)
});

api.commands.onCommand.addListener((cmd) => {
  if (cmd === 'toggle-overlay') broadcast({ kind: 'overlay', toggle: true });
});

syncScripts().catch(console.error);
connectServer();
