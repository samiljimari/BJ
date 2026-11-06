/* Shared renderer for the counter panel.
 * Used by the in-page overlay (extension content script) and by the local dashboard
 * (served by the Python server at /panel_render.js). No dependencies. */
(function (root) {
  'use strict';

  const CSS = `
  .bjp{--bg:#0f1418;--fg:#e8edf2;--mut:#8b98a5;--line:#26313a;--good:#2fbf71;--bad:#e5484d;--warn:#f5a524;
    --hit:#f5a524;--stand:#3b9eff;--double:#b678ff;--split:#2ccbbf;--surr:#e5484d;
    font:13px/1.35 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--fg);background:var(--bg);
    font-variant-numeric:tabular-nums}
  .bjp *{box-sizing:border-box}
  .bjp .row{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
  .bjp .stat{display:flex;flex-direction:column;min-width:52px}
  .bjp .stat b{font-size:20px;font-weight:650;letter-spacing:-.01em}
  .bjp .stat span{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
  .bjp .tc b{font-size:26px}
  .bjp .pos{color:var(--good)} .bjp .neg{color:var(--bad)}
  .bjp .sec{border-top:1px solid var(--line);margin-top:8px;padding-top:8px}
  .bjp .bet{font-weight:700;font-size:15px;padding:3px 8px;border-radius:6px;display:inline-block}
  .bjp .bet.on{background:color-mix(in srgb,var(--good) 22%,transparent);color:var(--good)}
  .bjp .bet.off{background:#232c33;color:var(--mut)}
  .bjp .act{font-size:30px;font-weight:800;letter-spacing:.02em;line-height:1.1}
  .bjp .act.hit{color:var(--hit)} .bjp .act.stand{color:var(--stand)} .bjp .act.double{color:var(--double)}
  .bjp .act.split{color:var(--split)} .bjp .act.surrender{color:var(--surr)} .bjp .act.other{color:var(--fg)}
  .bjp .mut{color:var(--mut)} .bjp .small{font-size:11.5px}
  .bjp table{border-collapse:collapse;width:100%;margin-top:4px}
  .bjp td{padding:1px 4px 1px 0;font-size:12px}
  .bjp td.v{text-align:right}
  .bjp tr.best td{font-weight:700}
  .bjp .cards{font-weight:600;letter-spacing:.03em}
  .bjp .warn{color:var(--warn);font-size:12px;margin-top:6px}
  .bjp .err{color:var(--bad);font-size:12px;margin-top:6px}
  .bjp .dev{color:var(--warn);font-weight:600}
  `;

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sign = (v, d = 1) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
  const pct = (v, d = 2) => sign(100 * v, d) + '%';
  const UP = { 1: 'A', 10: 'T' };
  const upName = (u) => UP[u] || String(u);
  const ACT_CLASS = { stand: 'stand', hit: 'hit', double: 'double', split: 'split', surrender: 'surrender' };

  function adviceHtml(a, state) {
    const r = state.round;
    if (!a) {
      const ph = r ? r.phase : null;
      const msg = !r ? 'Waiting for a round' : ph === 'dealing' ? 'Dealing…' : ph === 'dealer' ? 'Dealer playing' : ph === 'ended' ? 'Round over' : 'No decision for my hand';
      return `<div class="mut">${esc(msg)}</div>`;
    }
    if (a.pending) return '<div class="act other">…</div><div class="mut small">computing</div>';
    if (a.error) return `<div class="err">Engine error: ${esc(a.error)}</div>`;
    const cls = ACT_CLASS[a.best] || 'other';
    const hand = `${esc((a.cards || []).join(' '))} <span class="mut">(${a.soft ? 'soft ' : ''}${a.total})</span> v ${esc(upName(a.upcard))}`;
    let h = `<div class="row"><div class="act ${cls}">${esc(a.label)}</div>`;
    if (a.ranked && a.ranked.length > 1) h += `<div class="mut small">by ${a.margin.toFixed(3)}</div>`;
    h += `</div><div class="small cards">${hand}${a.hand ? ` <span class="mut">hand ${a.hand + 1}</span>` : ''}</div>`;
    if (a.ranked && a.ranked.length) {
      h += '<table>';
      for (const [k, v] of a.ranked) h += `<tr class="${k === a.best ? 'best' : ''}"><td>${esc(k)}</td><td class="v">${sign(v, 3)}</td></tr>`;
      h += '</table>';
    }
    if (a.basic) {
      h += `<div class="small mut">basic: ${esc(a.basic)}${a.hilo_index_play && a.hilo_index_play !== a.basic ? ` · Hi-Lo index: ${esc(a.hilo_index_play)}` : ''}`;
      if (a.deviation) h += ' · <span class="dev">count deviation</span>';
      h += '</div>';
    }
    if (a.insurance_ev != null) {
      h += `<div class="small">Insurance: <b class="${a.insurance_take ? 'pos' : 'mut'}">${a.insurance_take ? 'TAKE' : 'no'}</b> <span class="mut">(EV ${sign(a.insurance_ev, 3)}, P(ten) ${(100 * a.p_ten).toFixed(1)}%)</span></div>`;
    }
    if (a.note) h += `<div class="small mut">${esc(a.note)}</div>`;
    return h;
  }

  function roundHtml(r) {
    if (!r) return '';
    const seats = Object.entries(r.seats || {});
    let h = `<div class="small"><span class="mut">Dealer</span> <span class="cards">${esc((r.dealer || []).join(' ') || '–')}</span>`;
    for (const [name, s] of seats) {
      if (!s.mine) continue;
      s.hands.forEach((hd, i) => {
        const tag = hd.bust ? ' bust' : hd.surrendered ? ' surr.' : hd.doubled ? ' dbl' : '';
        h += ` · <span class="mut">${seats.length > 1 ? esc(name) + ' ' : ''}${s.hands.length > 1 ? 'H' + (i + 1) : 'Me'}</span> <span class="cards">${esc(hd.cards.join(' ') || '–')}</span>${hd.cards.length ? ` <span class="mut">${hd.total}${tag}</span>` : ''}`;
      });
    }
    return h + '</div>';
  }

  function render(el, state, opts) {
    opts = opts || {};
    if (!state) {
      el.innerHTML = `<div class="bjp"><div class="mut">${esc(opts.waitText || 'Waiting for the counter server…')}</div></div>`;
      return;
    }
    const s = state.shoe, b = state.bet;
    const tcCls = s.true_count >= 1 ? 'pos' : s.true_count <= -1 ? 'neg' : '';
    let h = '<div class="bjp">';
    h += `<div class="row">
      <div class="stat tc"><b class="${tcCls}">${sign(s.true_count, 1)}</b><span>true count</span></div>
      <div class="stat"><b>${sign(s.running_count, 0) || '0'}</b><span>running</span></div>
      <div class="stat"><b>${s.decks_remaining.toFixed(1)}</b><span>decks left</span></div>
      <div class="stat"><b>${Math.round(100 * s.penetration)}%</b><span>dealt</span></div></div>`;
    h += `<div class="row" style="margin-top:6px"><span class="bet ${b.sit_out ? 'off' : 'on'}" title="Suggested bet for the next round - you place it">${esc(b.label)}${b.amount_label ? ' · ' + esc(b.amount_label) : ''}</span>
      <span class="small mut">next round · est. edge ${pct(b.est_edge)}</span></div>`;
    h += `<div class="sec">${adviceHtml(state.advice, state)}</div>`;
    h += `<div class="sec">${roundHtml(state.round)}</div>`;
    if (state.from_shoe_start === false) h += '<div class="warn">Joined mid-shoe: count is incomplete until the next shuffle (or press New shoe at a shuffle).</div>';
    if (!s.integrity_ok) h += '<div class="err">Shoe integrity check failed - see warnings.</div>';
    for (const w of state.warnings || []) h += `<div class="warn">${esc(w)}</div>`;
    if (opts.showSource && state.source) {
      const src = state.source, p = src.parser || {};
      h += `<div class="sec small mut">parser <b>${esc(p.parser)}</b>: ${p.frames_seen || 0} frames → ${p.events_out || 0} events`;
      if (src.recorder && src.recorder.recording) h += ` · <span class="neg">● REC</span> ${esc(src.recorder.file)} (${src.recorder.frames})`;
      if (src.last_frame_age != null) h += ` · last frame ${src.last_frame_age}s ago`;
      h += ` · shoe #${s.shoe_number}, ${s.cards_seen} cards, ${state.rounds_this_shoe} rounds</div>`;
    }
    h += '</div>';
    el.innerHTML = h;
  }

  root.BJPanel = { CSS, render, esc };
})(typeof window !== 'undefined' ? window : globalThis);
