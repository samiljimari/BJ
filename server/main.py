"""Local server: browser extension + dashboard <-> parser -> table -> advisor.

    python -m server.main                       # parser 'none' (recon), dashboard at http://localhost:8765
    python -m server.main --demo                # + fake table at http://localhost:8766 (parser 'demo')
    python -m server.main --parser evolution_infinite --record
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

from .advisor import Advisor
from .betting import BetRamp
from .engine.strategy import Strategy, format_chart, load_deviations, load_or_build
from .logger import Recorder, SessionLog
from .parser import PARSERS, get_parser
from .rules import Rules
from .table import Table

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
EXTENSION = ROOT / "extension"
log = logging.getLogger("bj")


class CounterServer:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.rules = Rules.load(args.rules)
        log.info("rules: %s (%s)", self.rules.name, self.rules.fingerprint())
        t = time.perf_counter()
        self.strategy_data = load_or_build(self.rules)
        log.info("basic strategy ready in %.1fs, house edge %.3f%%",
                 time.perf_counter() - t, -100 * self.strategy_data["round_ev"])
        self.strategy = Strategy(self.strategy_data["tables"], load_deviations(args.deviations),
                                 charlie=self.rules.six_card_charlie)
        ramp = BetRamp.load(args.ramp) if args.ramp else BetRamp()
        ramp.base_edge = self.strategy_data["round_ev"] if not args.ramp else ramp.base_edge
        if args.unit is not None:
            ramp.unit = args.unit
        if args.currency is not None:
            ramp.currency = args.currency
        self.advisor = Advisor(self.rules, self.strategy, ramp, house_edge=-self.strategy_data["round_ev"])
        self.table = Table(self.rules, tuple(args.seats.split(",")))
        self.parser = get_parser(args.parser)
        self.session = SessionLog(enabled=not args.no_log)
        self.recorder = Recorder()
        if args.record:
            p = self.recorder.start()
            log.info("recording raw frames to %s", p)
        self.clients: dict[web.WebSocketResponse, str] = {}
        self.sockets: dict[str, dict] = {}  # game sockets seen by the extension
        self.ext_frames = 0
        self.last_frame_ts: float | None = None
        self.advice: dict | None = None
        self._advice_key = None
        self._broadcast_pending = False
        self.own_hosts = {f"{h}:{args.port}" for h in ("localhost", "127.0.0.1", args.host)}

    # ----------------------------------------------------------------- state
    def state(self) -> dict:
        s = self.advisor.snapshot(self.table)
        s["advice"] = self.advice
        s["source"] = {
            "parser": self.parser.status(),
            "ext_clients": sum(1 for r in self.clients.values() if r == "ext"),
            "ui_clients": sum(1 for r in self.clients.values() if r == "ui"),
            "ext_frames": self.ext_frames,
            "last_frame_age": None if self.last_frame_ts is None else round(time.time() - self.last_frame_ts, 1),
            "sockets": list(self.sockets.values())[-6:],
            "recorder": self.recorder.status(),
            "log_dir": str(self.session.dir.relative_to(ROOT)) if self.session.enabled else None,
        }
        return s

    def changed(self) -> None:
        """Call after any table change: recompute advice (async) + broadcast."""
        inputs = self.advisor.advice_inputs(self.table)
        if inputs is None:
            self._advice_key = None
            self.advice = None
        elif inputs != self._advice_key:
            self._advice_key = inputs
            self.advice = {"pending": True}
            asyncio.get_running_loop().create_task(self._compute_advice(inputs))
        self.schedule_broadcast()

    async def _compute_advice(self, inputs) -> None:
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self.advisor.compute_advice, inputs)
        except Exception as e:  # never kill the server over one bad hand
            log.exception("advice failed")
            result = {"error": str(e)}
        if inputs == self._advice_key:
            self.advice = result
            self.session.advice_given(result, self.table.shoe.snapshot())
            self.schedule_broadcast()

    def schedule_broadcast(self) -> None:
        if not self._broadcast_pending:
            self._broadcast_pending = True
            asyncio.get_running_loop().call_later(0.03, lambda: asyncio.ensure_future(self._broadcast()))

    async def _broadcast(self) -> None:
        self._broadcast_pending = False
        data = json.dumps({"kind": "state", "state": self.state()})
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:
                self.clients.pop(ws, None)

    # -------------------------------------------------------------- handlers
    def apply_event(self, ev: dict, source: str) -> None:
        self.session.event(ev, source)
        self.table.apply(ev)

    def on_frame(self, f: dict) -> None:
        url = f.get("url") or ""
        try:
            netloc = urlparse(url).netloc
        except ValueError:
            netloc = ""
        if netloc in self.own_hosts:
            return  # our own dashboard socket hooked by the extension - ignore
        self.ext_frames += 1
        self.last_frame_ts = time.time()
        f.setdefault("ts_server", time.time())
        self.session.frame(f)
        self.recorder.write(f)
        for ev in self.parser.feed(f):
            self.apply_event(ev, self.parser.name)

    def on_manual_card(self, msg: dict) -> None:
        """Dashboard keypad: {"kind":"manual","rank":"T","target":"auto|player|dealer|other"}"""
        want = msg.get("target", "auto")
        auto = self.table.auto_target()
        if want == "auto":
            target = auto
        elif want == "player":
            idx = self.table.current_hand_index()
            target = {"kind": "player", "seat": self.table.my_seat(), "hand": idx or 0,
                      "new_round": auto.get("new_round", False)}
        else:
            target = {"kind": want}
        if target.pop("new_round", False):
            self.apply_event({"type": "round_start"}, "manual")
        self.apply_event({"type": "card", "rank": msg["rank"], "target": target}, "manual")

    def on_manual_decision(self, msg: dict) -> None:
        idx = self.table.current_hand_index()
        if idx is None:
            return
        self.apply_event({"type": "decision", "seat": self.table.my_seat(), "hand": idx,
                          "action": msg["action"]}, "manual")

    def on_control(self, msg: dict) -> None:
        action = msg.get("action")
        if action == "reset_shoe":
            self.apply_event({"type": "shoe_change", "manual": True}, "control")
        elif action == "undo":
            last = self.table.undo()
            self.session.event({"type": "undo", "removed": last}, "control")
        elif action == "new_round":
            self.apply_event({"type": "round_start", "round_id": msg.get("round_id")}, "control")
        elif action == "record_start":
            p = self.recorder.start()
            log.info("recording raw frames to %s", p)
        elif action == "record_stop":
            self.recorder.stop()
        else:
            log.warning("unknown control %r", action)

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        self.clients[ws] = "ui"
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                kind = m.get("kind")
                if kind == "hello":
                    self.clients[ws] = m.get("role", "ui")
                    await ws.send_str(json.dumps({"kind": "state", "state": self.state()}))
                    continue
                if kind == "frame":
                    self.on_frame(m)
                elif kind == "frames":
                    for f in m.get("frames", []):
                        self.on_frame(f)
                elif kind in ("ws_open", "ws_close"):
                    key = f"{m.get('frame_url', '')}#{m.get('socket')}"
                    self.sockets[key] = {"url": m.get("url"), "frame": m.get("frame_url"),
                                         "open": kind == "ws_open", "ts": time.time()}
                elif kind == "event":
                    self.apply_event(m["event"], self.clients[ws])
                elif kind == "events":
                    for e in m.get("events", []):
                        self.apply_event(e, self.clients[ws])
                elif kind == "manual":
                    self.on_manual_card(m)
                elif kind == "manual_decision":
                    self.on_manual_decision(m)
                elif kind == "control":
                    self.on_control(m)
                elif kind == "ping":
                    continue
                self.changed()
        finally:
            self.clients.pop(ws, None)
            self.schedule_broadcast()
        return ws

    async def heartbeat(self) -> None:
        # Regular traffic keeps the extension's MV3 service worker alive.
        while True:
            await asyncio.sleep(15)
            for ws, role in list(self.clients.items()):
                if role == "ext":
                    try:
                        await ws.send_str('{"kind":"ping"}')
                    except Exception:
                        self.clients.pop(ws, None)

    # ------------------------------------------------------------------ http
    async def index(self, request):
        return web.FileResponse(STATIC / "index.html")

    async def panel_js(self, request):
        return web.FileResponse(EXTENSION / "panel_render.js",
                                headers={"Content-Type": "application/javascript"})

    async def api_state(self, request):
        return web.json_response(self.state())

    async def api_strategy(self, request):
        return web.Response(text=f"{self.rules.name}  house edge {-100 * self.strategy_data['round_ev']:.3f}%\n\n"
                                 + format_chart(self.strategy_data["tables"]))

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/panel_render.js", self.panel_js)
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_get("/api/state", self.api_state)
        app.router.add_get("/api/strategy", self.api_strategy)
        app.router.add_static("/static/", STATIC)

        async def on_start(app):
            app["hb"] = asyncio.get_running_loop().create_task(self.heartbeat())

        async def on_stop(app):
            app["hb"].cancel()
            self.recorder.stop()
            self.session.close()

        app.on_startup.append(on_start)
        app.on_cleanup.append(on_stop)
        return app


async def serve(args: argparse.Namespace) -> None:
    srv = CounterServer(args)
    runner = web.AppRunner(srv.app())
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    log.info("dashboard: http://localhost:%d   (parser: %s)", args.port, args.parser)
    if args.demo:
        from .demo import DemoTable
        on_message = None
        if args.demo_direct:
            def on_message(data: str) -> None:  # bypass the extension: frames go straight to the parser
                srv.on_frame({"kind": "frame", "dir": "in", "socket": 0, "binary": False, "data": data,
                              "url": f"ws://demo-direct:{args.demo_port}/ws", "ts": int(time.time() * 1000)})
                srv.changed()
        demo = DemoTable(srv.rules, srv.strategy_data["tables"], speed=args.demo_speed, on_message=on_message)
        drunner = web.AppRunner(demo.app())
        await drunner.setup()
        await web.TCPSite(drunner, args.host, args.demo_port).start()
        asyncio.get_running_loop().create_task(demo.run())
        log.info("demo table: http://localhost:%d  (enable the extension on http://localhost)", args.demo_port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--rules", default="infinite_blackjack")
    ap.add_argument("--parser", choices=sorted(PARSERS), help="default: 'demo' with --demo, else 'none'")
    ap.add_argument("--seats", default="shared", help="comma-separated seats that are mine")
    ap.add_argument("--ramp", help="bet ramp JSON (default: notes section 8 ramp)")
    ap.add_argument("--unit", type=float, help="money per betting unit, e.g. 0.5 -> 'BET 2u = \u20ac1.00'")
    ap.add_argument("--currency", help="currency symbol for the bet amount (default \u20ac)")
    ap.add_argument("--deviations", default=str(ROOT / "rules" / "deviations_i18.json"),
                    help="Hi-Lo index table used for the cross-check line")
    ap.add_argument("--record", action="store_true", help="record raw frames to fixtures/shoe_NNN.jsonl")
    ap.add_argument("--no-log", action="store_true", help="do not write logs/session-*")
    ap.add_argument("--demo", action="store_true", help="also run the fake demo table")
    ap.add_argument("--demo-port", type=int, default=8766)
    ap.add_argument("--demo-speed", type=float, default=1.0)
    ap.add_argument("--demo-direct", action="store_true",
                    help="feed the demo table straight into the counter (no extension needed)")
    args = ap.parse_args(argv)
    if args.demo_direct:
        args.demo = True
    if args.parser is None:
        args.parser = "demo" if args.demo else "none"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
