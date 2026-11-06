"""A fake live table on its own origin (default http://localhost:8766).

Lets you test the WHOLE pipeline (extension WebSocket hook -> server -> parser ->
overlay) without a casino: enable the extension on http://localhost and open the
demo page. The protocol is made up (see server/parser/demo.py); the dealer plays an
8-deck shoe to the cut card and auto-plays the shared hand with basic strategy.
"""

from __future__ import annotations

import asyncio
import json
import random

from aiohttp import WSMsgType, web

from .engine.strategy import Strategy
from .rules import Rules
from .sim.game import SimShoe, play_round

SUITS = "shdc"

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Demo Table</title>
<style>
 body{font:15px system-ui,sans-serif;background:#0b3d2e;color:#eef;margin:0;padding:24px}
 h1{font-size:18px;margin:0 0 4px} .muted{opacity:.7;font-size:13px}
 .row{margin:18px 0} .lbl{display:inline-block;width:90px;opacity:.8}
 .card{display:inline-block;min-width:34px;padding:6px 4px;margin:2px;border-radius:5px;background:#fff;
   color:#111;text-align:center;font-weight:600}
 .card.r{color:#c00} .card.x{background:#335;color:#335}
 #log{font:12px ui-monospace,monospace;opacity:.75;max-height:240px;overflow:auto;white-space:pre}
</style></head><body>
<h1>Demo live table (fake)</h1>
<div class="muted">Not a casino - a local test table for the counter. Cards stream over a WebSocket on this page.</div>
<div class="row"><span class="lbl">Round</span><span id="round">-</span></div>
<div class="row"><span class="lbl">Dealer</span><span id="dealer"></span></div>
<div class="row"><span class="lbl">Shared hand</span><span id="player"></span></div>
<div class="row"><span class="lbl">Result</span><span id="result">-</span></div>
<div id="log"></div>
<script>
const $ = (id) => document.getElementById(id);
function card(code){ const s=document.createElement('span'); s.className='card'+(code==='XX'?' x':'')+(/[hd]$/.test(code)?' r':'');
  s.textContent = code==='XX' ? '??' : code.slice(0,-1)+({h:'\\u2665',d:'\\u2666',s:'\\u2660',c:'\\u2663'}[code.slice(-1)]||''); return s; }
function connect(){
  const ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    const log = $('log'); log.textContent = (e.data + '\\n' + log.textContent).slice(0, 6000);
    if (m.msg === 'newRound'){ $('round').textContent = m.id; $('dealer').innerHTML=''; $('player').innerHTML=''; $('result').textContent='-'; }
    if (m.msg === 'deal'){
      if (m.to === 'dealer'){ const d=$('dealer'); const x=d.querySelector('.x'); if (x && m.card!=='XX') x.replaceWith(card(m.card)); else d.appendChild(card(m.card)); }
      else if (m.to === 'player'){ $('player').appendChild(card(m.card)); }
    }
    if (m.msg === 'result') $('result').textContent = m.outcome;
    if (m.msg === 'shuffle') $('result').textContent = 'New shoe (shuffle)';
  };
  ws.onclose = () => setTimeout(connect, 1500);
}
connect();
</script></body></html>"""


class DemoTable:
    def __init__(self, rules: Rules, tables: dict, speed: float = 1.0, seed: int | None = None,
                 on_message=None):
        self.rules = rules
        # Optional callback(msg) - "direct" mode feeds the counter without the extension.
        self.on_message = on_message
        self.strategy = Strategy(tables, None, charlie=rules.six_card_charlie)
        self.speed = max(0.05, speed)
        self.rng = random.Random(seed)
        self.clients: set[web.WebSocketResponse] = set()
        self.round_no = 0

    async def send(self, msg: dict) -> None:
        data = json.dumps(msg)
        if self.on_message:
            self.on_message(data)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:
                self.clients.discard(ws)

    async def pause(self, s: float) -> None:
        await asyncio.sleep(s / self.speed)

    async def run(self) -> None:
        sh = SimShoe(self.rules, self.rng)
        fresh = True
        while True:
            if not self.clients and not self.on_message:
                fresh = True  # start a new shoe when someone (re)joins
                await asyncio.sleep(0.5)
                continue
            if fresh or sh.needs_shuffle():
                fresh = False
                sh.shuffle()
                await self.send({"msg": "shuffle"})
                await self.pause(2.0)
            self.round_no += 1
            for msg, pause in round_messages(sh, self.rules, self.strategy, self.rng, self.round_no):
                await self.send(msg)
                await self.pause(pause)

    # ------------------------------------------------------------------ http
    async def page(self, request: web.Request) -> web.Response:
        return web.Response(text=PAGE, content_type="text/html")

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(ws)
        return ws

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.page)
        app.router.add_get("/ws", self.ws)
        return app


def round_messages(sh: SimShoe, rules: Rules, strategy: Strategy, rng: random.Random,
                   round_no: int) -> list[tuple[dict, float]]:
    """Play one round and return the demo-protocol messages with a pause (seconds) after each."""
    rid = f"demo-{round_no}"
    events: list[dict] = []
    result = play_round(sh, rules, strategy, use_devs=False, events=events)
    out: list[tuple[dict, float]] = [({"msg": "newRound", "id": rid}, 1.0)]
    visible = 0
    for ev in events:
        if ev["type"] == "card":
            t = ev["target"]
            code = ev["rank"].replace("T", "10") + rng.choice(SUITS)
            visible += 1
            if visible == 3:  # hole card goes out face down after the initial deal
                out.append(({"msg": "deal", "to": t["kind"], "box": t.get("hand", 0), "card": code, "round": rid}, 0.3))
                out.append(({"msg": "deal", "to": "dealer", "card": "XX", "round": rid}, 3.0))
            else:
                out.append(({"msg": "deal", "to": t["kind"], "box": t.get("hand", 0), "card": code, "round": rid}, 0.7))
        elif ev["type"] == "decision":
            out.append(({"msg": "decision", "box": ev["hand"], "action": ev["action"]},
                        0.3 if ev["action"] == "stand" else 1.5))
    outcome = "win" if result > 0 else ("lose" if result < 0 else "push")
    out.append(({"msg": "result", "id": rid, "outcome": f"{outcome} ({result:+g})"}, 2.5))
    return out
