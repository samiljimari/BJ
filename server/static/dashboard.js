'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const style = document.createElement('style');
  style.textContent = window.BJPanel.CSS;
  document.head.appendChild(style);

  let ws = null;
  let state = null;
  let target = 'auto';
  let oneShot = null;

  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => {
      ws.send(JSON.stringify({ kind: 'hello', role: 'ui' }));
      $('dot').classList.add('up');
      $('conn').textContent = 'connected';
    };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.kind === 'state') { state = m.state; render(); }
    };
    ws.onclose = () => {
      $('dot').classList.remove('up');
      $('conn').textContent = 'server offline - retrying';
      setTimeout(connect, 1500);
    };
  }
  const send = (m) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(m)); };

  // ------------------------------------------------------------- input
  const CARDS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', 'T'];
  for (const c of CARDS) {
    const b = document.createElement('button');
    b.textContent = c === 'T' ? '10' : c;
    b.addEventListener('click', () => card(c));
    $('keys').appendChild(b);
  }
  function card(rank) {
    const t = oneShot || target;
    oneShot = null;
    markTargets();
    send({ kind: 'manual', rank, target: t });
  }
  function markTargets() {
    for (const b of $('targets').querySelectorAll('button')) {
      b.classList.toggle('on', b.dataset.t === (oneShot || target));
    }
  }
  $('targets').addEventListener('click', (e) => {
    const t = e.target.dataset && e.target.dataset.t;
    if (t) { target = t; oneShot = null; markTargets(); }
  });
  document.querySelectorAll('[data-d]').forEach((b) =>
    b.addEventListener('click', () => send({ kind: 'manual_decision', action: b.dataset.d })));
  $('newround').addEventListener('click', () => send({ kind: 'control', action: 'new_round' }));
  $('undo').addEventListener('click', () => send({ kind: 'control', action: 'undo' }));
  $('newshoe').addEventListener('click', newShoe);
  function newShoe() { if (confirm('Start a new shoe? (count resets to 0)')) send({ kind: 'control', action: 'reset_shoe' }); }

  const KEYMAP = { a: 'A', 1: 'A', t: 'T', 0: 'T', j: 'T', q: 'T', k: 'T' };
  for (let i = 2; i <= 9; i++) KEYMAP[i] = String(i);
  const DECISIONS = { s: 'stand', d: 'double', p: 'split', r: 'surrender', i: 'insurance' };
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.tagName === 'INPUT') return;
    const k = e.key.toLowerCase();
    if (e.shiftKey && k === 'n') { newShoe(); e.preventDefault(); return; }
    if (KEYMAP[k]) { card(KEYMAP[k]); e.preventDefault(); return; }
    if (DECISIONS[k]) { send({ kind: 'manual_decision', action: DECISIONS[k] }); e.preventDefault(); return; }
    if (k === 'n') { send({ kind: 'control', action: 'new_round' }); e.preventDefault(); return; }
    if (k === 'backspace' || k === 'u') { send({ kind: 'control', action: 'undo' }); e.preventDefault(); return; }
    if (k === 'z') { oneShot = 'dealer'; markTargets(); }
    if (k === 'x') { oneShot = 'other'; markTargets(); }
  });

  // ------------------------------------------------------------ render
  function render() {
    window.BJPanel.render($('panel'), state, { showSource: true });
    if (!state) return;
    $('rules').textContent = `rules: ${state.rules} · house edge ${(100 * state.house_edge).toFixed(2)}% (full shoe)`;
    const rem = state.shoe.remaining;
    const total = Object.values(rem).reduce((a, b) => a + b, 0) || 1;
    const comp = $('comp');
    const lbl = $('complbl');
    comp.textContent = '';
    lbl.textContent = '';
    for (const c of CARDS) {
      const share = rem[c] / total;
      const base = c === 'T' ? 16 / 52 : 4 / 52;
      const rel = share / base; // 1.0 = same as a fresh shoe
      const bar = document.createElement('div');
      bar.className = 'bar' + (rel > 1.05 ? ' rich' : rel < 0.95 ? ' poor' : '');
      bar.style.height = Math.max(4, Math.min(100, rel * 50)) + '%';
      bar.title = `${c}: ${rem[c]} left (${(100 * share).toFixed(1)}%, ${(rel * 100).toFixed(0)}% of normal)`;
      comp.appendChild(bar);
      const l = document.createElement('div');
      l.textContent = `${c} ${rem[c]}`;
      lbl.appendChild(l);
    }
    const socks = (state.source && state.source.sockets) || [];
    $('sockets').textContent = socks.length
      ? socks.map((s) => `${s.open ? '●' : '○'} ${s.url}  (frame ${s.frame})`).join('\n')
      : 'none - enable the game frame in the extension popup';
    $('sockets').style.whiteSpace = 'pre-wrap';
  }

  render();
  connect();
})();
