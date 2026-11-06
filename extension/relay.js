/* Isolated-world content script (enabled frames only).
 * - receives copied frames from hook.js (DOM CustomEvent) and forwards them to the
 *   background script
 * - renders the counter overlay (Shadow DOM) in the frame that carries the game's
 *   WebSocket traffic (or in the top page, depending on the popup setting).
 * ADVICE ONLY: this script only reads. It never clicks, types, submits or sends
 * anything to the game - the only DOM it creates is its own overlay. */
(() => {
  'use strict';
  if (window.__bjcRelay) return;
  window.__bjcRelay = true;

  const api = globalThis.browser ?? globalThis.chrome;
  const EVT = '__bjc_frame';
  const isTop = window === window.top;
  let port = null;
  let queue = [];
  let lastState = null;
  let serverUp = false;
  let sawGameTraffic = false;
  let settings = { overlayMode: 'game', serverUrl: 'ws://127.0.0.1:8765/ws', overlayPos: null, overlayMin: false };
  let ownHost = '127.0.0.1:8765';
  let host = null;   // overlay host element
  let body = null;
  let hidden = false;

  api.storage.local.get(settings).then((s) => {
    settings = { ...settings, ...s };
    try { ownHost = new URL(settings.serverUrl).host; } catch (e) { /* keep default */ }
    maybeShow();
  }, () => {});

  // --------------------------------------------------------------- transport
  function connect() {
    try {
      port = api.runtime.connect({ name: 'bjc-relay' });
    } catch (e) {
      port = null; // extension reloaded: this content script is orphaned
      return;
    }
    port.onMessage.addListener(onMessage);
    port.onDisconnect.addListener(() => { port = null; setTimeout(connect, 1000); });
    const q = queue;
    queue = [];
    q.forEach(post);
  }

  // Firefox unloads idle background event pages; regular port traffic keeps it (and
  // its connection to the counter server) alive while a game frame is open.
  setInterval(() => { if (port) { try { port.postMessage({ kind: 'ping' }); } catch (e) { port = null; } } }, 20000);

  function post(m) {
    if (port) {
      try { port.postMessage(m); return; } catch (e) { port = null; }
    }
    queue.push(m);
    if (queue.length > 20000) queue.shift();
  }

  const isOwnSocket = (url) => {
    try {
      const h = new URL(url).host;
      return h === ownHost || h === ownHost.replace('127.0.0.1', 'localhost') || h === ownHost.replace('localhost', '127.0.0.1');
    } catch (e) { return false; }
  };

  document.addEventListener(EVT, (e) => {
    let m;
    try { m = JSON.parse(e.detail); } catch (err) { return; }
    if (!m || isOwnSocket(m.url)) return;
    m.frame_url = location.href;
    post(m);
    if (m.kind === 'frame' && !sawGameTraffic) {
      sawGameTraffic = true;
      maybeShow();
    }
  });

  function onMessage(m) {
    if (m.kind === 'state') {
      lastState = m.state;
      serverUp = true;
      render();
    } else if (m.kind === 'server') {
      serverUp = !!m.connected;
      render();
    } else if (m.kind === 'overlay') {
      if (m.toggle) hidden = !hidden;
      if (m.settings) { settings = { ...settings, ...m.settings }; }
      maybeShow();
    }
  }

  // ----------------------------------------------------------------- overlay
  function wanted() {
    if (hidden || settings.overlayMode === 'off') return false;
    if (settings.overlayMode === 'top') return isTop;
    return sawGameTraffic; // 'game': the frame that owns the game's socket
  }

  function maybeShow() {
    if (wanted()) {
      if (!host) create();
      host.style.display = '';
      render();
    } else if (host) {
      host.style.display = 'none';
    }
  }

  const OVERLAY_CSS = `
    .shell{width:300px;border-radius:10px;overflow:hidden;box-shadow:0 8px 28px rgba(0,0,0,.45);
      border:1px solid #26313a;background:#0f1418;opacity:.96}
    .bar{display:flex;align-items:center;gap:6px;padding:5px 8px;background:#161d23;cursor:move;user-select:none;
      font:600 12px system-ui,sans-serif;color:#8b98a5}
    .bar .t{flex:1}
    .dot{width:8px;height:8px;border-radius:50%;background:#e5484d}
    .dot.up{background:#2fbf71}
    button{font:12px system-ui,sans-serif;background:#232c33;color:#e8edf2;border:1px solid #33414c;border-radius:5px;
      padding:2px 8px;cursor:pointer}
    button:hover{background:#2c3740}
    .body{padding:8px 10px}
    .acts{display:flex;gap:6px;padding:0 10px 8px}
    .min .body,.min .acts{display:none}
  `;

  function create() {
    host = document.createElement('div');
    host.setAttribute('data-bjc', 'overlay');
    const pos = settings.overlayPos || { top: 12, right: 12 };
    host.style.cssText = `position:fixed;z-index:2147483647;${pos.left != null ? `left:${pos.left}px` : `right:${pos.right}px`};top:${pos.top}px;`;
    const shadow = host.attachShadow({ mode: 'open' });
    shadow.innerHTML = `<style>${window.BJPanel.CSS}${OVERLAY_CSS}</style>
      <div class="shell${settings.overlayMin ? ' min' : ''}">
        <div class="bar"><span class="dot"></span><span class="t">BJ counter · advice only</span>
          <button data-a="min" title="Minimize">–</button><button data-a="hide" title="Hide (Alt+Shift+B)">×</button></div>
        <div class="body"></div>
        <div class="acts"><button data-a="reset" title="Shuffle seen: start a new shoe">New shoe</button>
          <button data-a="undo" title="Undo last event">Undo</button></div>
      </div>`;
    body = shadow.querySelector('.body');
    const shell = shadow.querySelector('.shell');
    shadow.addEventListener('click', (e) => {
      const a = e.target && e.target.getAttribute && e.target.getAttribute('data-a');
      if (a === 'min') {
        shell.classList.toggle('min');
        api.storage.local.set({ overlayMin: shell.classList.contains('min') });
      } else if (a === 'hide') {
        hidden = true; maybeShow();
      } else if (a === 'reset') {
        if (confirm('Start a new shoe? (count resets to 0)')) post({ kind: 'control', action: 'reset_shoe' });
      } else if (a === 'undo') {
        post({ kind: 'control', action: 'undo' });
      }
    });
    dragify(shadow.querySelector('.bar'));
    mount();
    document.addEventListener('fullscreenchange', mount);
  }

  function mount() {
    // Keep the overlay visible when the game puts an element into fullscreen.
    const target = document.fullscreenElement || document.documentElement;
    if (host && target && host.parentNode !== target && !(target instanceof HTMLVideoElement)) target.appendChild(host);
  }

  function dragify(bar) {
    let sx, sy, ox, oy, dragging = false;
    bar.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'BUTTON') return;
      dragging = true;
      const r = host.getBoundingClientRect();
      sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top;
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      host.style.left = Math.max(0, ox + e.clientX - sx) + 'px';
      host.style.top = Math.max(0, oy + e.clientY - sy) + 'px';
      host.style.right = 'auto';
    });
    window.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      const r = host.getBoundingClientRect();
      api.storage.local.set({ overlayPos: { left: Math.round(r.left), top: Math.round(r.top) } });
    });
  }

  function render() {
    if (!host || !body) return;
    const dot = host.shadowRoot.querySelector('.dot');
    dot.classList.toggle('up', serverUp);
    dot.title = serverUp ? 'Connected to local server' : 'Local server not reachable';
    window.BJPanel.render(body, serverUp ? lastState : null, {
      waitText: 'Local server not reachable - start it with: python -m server.main',
    });
  }

  connect();
})();
