/* Browser-free smoke test of the extension scripts, Firefox flavour (`browser.*` API).
 *
 *   python -m server.main --demo --no-log        (terminal 1)
 *   node tests/ext_node_smoke.js                 (terminal 2)
 *
 * Loads the REAL hook.js, panel_render.js, relay.js and background.js into one Node
 * process with a mocked `browser` API (storage, permissions, scripting, runtime ports),
 * opens a "game" WebSocket to the demo table, and checks that the frames reach the
 * counter server through hook -> relay -> background -> server, and that state comes
 * back to the relay. Needs Node 22+ (global WebSocket). Not a replacement for a test in
 * a real Firefox - it exercises the logic, not the browser integration. */
'use strict';

const assert = require('assert');
const path = require('path');
const EXT = path.join(__dirname, '..', 'extension');
const SERVER = 'http://127.0.0.1:8765';
const GAME_WS = 'ws://127.0.0.1:8766/ws';

// ------------------------------------------------------------------ mock browser
const store = { overlayMode: 'off', origins: [] };
let registered = [];
const onConnect = [];
const onMessage = [];
const toRelay = []; // messages delivered to the relay side (for assertions)

function storageGet(keys) {
  if (keys == null) return { ...store };
  if (typeof keys === 'string') return keys in store ? { [keys]: store[keys] } : {};
  if (Array.isArray(keys)) return Object.fromEntries(keys.filter((k) => k in store).map((k) => [k, store[k]]));
  return Object.fromEntries(Object.entries(keys).map(([k, d]) => [k, k in store ? store[k] : d]));
}

function event() {
  const ls = [];
  return { addListener: (f) => ls.push(f), fire: (...a) => ls.forEach((f) => f(...a)) };
}

function portPair(name) {
  const a = { name, onMessage: event(), onDisconnect: event() };
  const b = { name, onMessage: event(), onDisconnect: event(), sender: { tab: { id: 1 }, frameId: 0 } };
  const clone = (m) => JSON.parse(JSON.stringify(m));
  a.postMessage = (m) => queueMicrotask(() => b.onMessage.fire(clone(m)));
  b.postMessage = (m) => queueMicrotask(() => { toRelay.push(m); a.onMessage.fire(clone(m)); });
  return [a, b];
}

globalThis.browser = {
  storage: { local: { get: async (k) => storageGet(k), set: async (o) => { Object.assign(store, o); } } },
  permissions: {
    contains: async () => true, request: async () => true, remove: async () => true,
    onAdded: event(), onRemoved: event(),
  },
  scripting: {
    getRegisteredContentScripts: async () => registered,
    unregisterContentScripts: async ({ ids }) => { registered = registered.filter((s) => !ids.includes(s.id)); },
    registerContentScripts: async (s) => {
      if (s.some((x) => x.matchOriginAsFallback)) throw new Error('simulate unsupported key'); // exercise fallback
      registered = registered.concat(s);
    },
  },
  runtime: {
    onInstalled: event(), onStartup: event(),
    onConnect: { addListener: (f) => onConnect.push(f) },
    onMessage: { addListener: (f) => onMessage.push(f) },
    connect: ({ name }) => {
      const [relaySide, bgSide] = portPair(name);
      queueMicrotask(() => onConnect.forEach((f) => f(bgSide)));
      return relaySide;
    },
  },
  commands: { onCommand: event() },
};
const sendToBackground = (m) => new Promise((res) => onMessage[0](m, {}, res));

// ------------------------------------------------------------- minimal page globals
globalThis.window = globalThis;
window.top = window;
globalThis.document = new EventTarget();
globalThis.location = { href: 'http://127.0.0.1:8766/' };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const getState = async () => (await fetch(`${SERVER}/api/state`)).json();

(async () => {
  require(path.join(EXT, 'background.js'));

  // 1) enabling an origin registers both scripts (MAIN-world hook + relay)
  const r = await sendToBackground({ kind: 'add-origin', origin: 'http://127.0.0.1' });
  assert.ok(r.ok, 'add-origin failed');
  const hook = registered.find((s) => s.id === 'bjc-hook');
  const relay = registered.find((s) => s.id === 'bjc-relay');
  assert.ok(hook && relay, 'content scripts not registered');
  assert.strictEqual(hook.world, 'MAIN');
  assert.strictEqual(hook.runAt, 'document_start');
  assert.deepStrictEqual(hook.matches, ['http://127.0.0.1/*']);
  assert.deepStrictEqual(relay.js, ['panel_render.js', 'relay.js']);
  console.log('ok  scripts registered (fallback without matchOriginAsFallback exercised)');

  // 2) pending origin is completed by permissions.onAdded (Firefox popup-closes case)
  await sendToBackground({ kind: 'pending-origin', origin: 'https://example.org' });
  browser.permissions.onAdded.fire({ origins: ['https://example.org/*'] });
  await sleep(100);
  assert.ok(store.origins.includes('https://example.org'), 'pending origin not completed');
  assert.ok(!store.pending.includes('https://example.org'));
  console.log('ok  pending origin completed via permissions.onAdded');

  // 3) inject the page scripts, then let the "game" open its socket
  require(path.join(EXT, 'hook.js'));
  require(path.join(EXT, 'panel_render.js'));
  require(path.join(EXT, 'relay.js'));
  const before = await getState();
  const game = new WebSocket(GAME_WS);
  let gameMsgs = 0;
  game.addEventListener('message', () => { gameMsgs++; });
  await sleep(9000);

  const after = await getState();
  const framesIn = after.source.parser.frames_seen - before.source.parser.frames_seen;
  console.log(`    game frames received by page: ${gameMsgs}, frames parsed by server: ${framesIn}, cards counted: ${after.shoe.cards_seen}`);
  assert.ok(gameMsgs > 0, 'demo table sent nothing - is the server running with --demo?');
  assert.strictEqual(framesIn, gameMsgs, 'every game frame must reach the parser exactly once');
  assert.ok(after.shoe.cards_seen > 0, 'no cards counted');
  assert.ok(after.source.sockets.some((s) => s.url === GAME_WS), 'game socket not reported');
  assert.ok(!after.source.sockets.some((s) => (s.url || '').includes(':8765')), 'own server socket leaked');
  console.log('ok  hook -> relay -> background -> server -> parser');

  const states = toRelay.filter((m) => m.kind === 'state');
  assert.ok(states.length > 0, 'relay received no state');
  assert.strictEqual(states[states.length - 1].state.mode, 'advisory');
  const kinds = new Set(toRelay.map((m) => m.kind));
  assert.ok([...kinds].every((k) => ['server', 'state', 'overlay'].includes(k)), `unexpected kinds ${[...kinds]}`);
  console.log(`ok  relay got ${states.length} state updates (mode=advisory), only display messages`);

  game.close();
  console.log('\nALL OK');
  process.exit(0);
})().catch((e) => { console.error('FAIL', e.message); process.exit(1); });
