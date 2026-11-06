/* Runs in the page's MAIN world at document_start in enabled frames.
 * Wraps window.WebSocket so every frame the game receives (and sends) is copied to
 * the extension's isolated-world relay via a DOM CustomEvent. It never modifies,
 * delays or blocks the game's traffic. */
(() => {
  'use strict';
  if (window.__bjcHookInstalled) return;
  const Native = window.WebSocket;
  if (typeof Native !== 'function') return;
  window.__bjcHookInstalled = true;

  const EVT = '__bjc_frame';
  const ids = new WeakMap();
  let socketSeq = 0;
  let frameSeq = 0;

  const emit = (o) => {
    try {
      document.dispatchEvent(new CustomEvent(EVT, { detail: JSON.stringify(o) }));
    } catch (e) { /* never break the page */ }
  };

  const b64 = (buf) => {
    const bytes = new Uint8Array(buf);
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(s);
  };

  function capture(ws, dir, data) {
    const base = { kind: 'frame', dir, socket: ids.get(ws), url: ws.url, ts: Date.now(), n: ++frameSeq };
    if (typeof data === 'string') {
      emit({ ...base, binary: false, data });
    } else if (data instanceof ArrayBuffer) {
      emit({ ...base, binary: true, data: b64(data) });
    } else if (ArrayBuffer.isView(data)) {
      emit({ ...base, binary: true, data: b64(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)) });
    } else if (typeof Blob !== 'undefined' && data instanceof Blob) {
      data.arrayBuffer().then((buf) => emit({ ...base, binary: true, data: b64(buf) }), () => {});
    }
  }

  function attach(ws) {
    const id = ++socketSeq;
    ids.set(ws, id);
    emit({ kind: 'ws_open', socket: id, url: ws.url, ts: Date.now() });
    ws.addEventListener('message', (e) => capture(ws, 'in', e.data));
    ws.addEventListener('close', (e) => emit({ kind: 'ws_close', socket: id, url: ws.url, code: e.code, ts: Date.now() }));
  }

  window.WebSocket = new Proxy(Native, {
    construct(target, args, newTarget) {
      const ws = Reflect.construct(target, args, newTarget);
      try { attach(ws); } catch (e) { /* ignore */ }
      return ws;
    },
  });

  const nativeSend = Native.prototype.send;
  Native.prototype.send = function (data) {
    try { if (ids.has(this)) capture(this, 'out', data); } catch (e) { /* ignore */ }
    return nativeSend.apply(this, arguments);
  };
})();
