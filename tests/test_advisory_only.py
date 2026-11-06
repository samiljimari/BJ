"""Tripwire for the "advice only" guarantee.

The tool must never place bets or make decisions: nothing that runs inside the game
page may click, type, submit or send messages to the game, and the server only ever
pushes display state. If one of these tests fails, someone added automation - that
must be a deliberate, reviewed decision, not an accident.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
IN_PAGE = ["hook.js", "relay.js", "panel_render.js"]  # scripts injected into the game's frames

AUTOMATION = [
    r"\.click\s*\(",
    r"new\s+(Mouse|Pointer|Keyboard|Input|Touch|Wheel|Drag|Focus)Event\b",
    r"\.submit\s*\(",
    r"requestSubmit",
    r"execCommand",
    r"\.focus\s*\(",
    r"\bnew\s+WebSocket\s*\(",
    r"\.send\s*\(",
    r"\bfetch\s*\(",
    r"XMLHttpRequest",
    r"sendBeacon",
]


def _src(name: str) -> str:
    text = (EXT / name).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)        # strip block comments
    return re.sub(r"(?m)^\s*//.*$|(?<=[;{}])\s*//.*$", "", text)  # and line comments


def test_in_page_scripts_have_no_automation_primitives():
    for name in IN_PAGE:
        src = _src(name)
        for pat in AUTOMATION:
            assert not re.search(pat, src), f"{name}: forbidden pattern {pat!r} (advice-only guarantee)"


def test_hook_only_observes_the_game_socket():
    src = _src("hook.js")
    # The constructor wrapper creates exactly the socket the game asked for...
    assert src.count("Reflect.construct(") == 1
    # ...and the send wrapper only passes the game's own call through unchanged.
    assert src.count("nativeSend.apply(this, arguments)") == 1
    assert "nativeSend" in src and src.count("nativeSend") == 2  # definition + passthrough
    # Only our private frame-copy event is dispatched.
    calls = re.findall(r"dispatchEvent\(\s*([^,]*,)", src)
    assert calls == ["new CustomEvent(EVT,"], calls


def test_relay_reacts_only_to_display_messages():
    kinds = set(re.findall(r"m\.kind === '([a-z_]+)'", _src("relay.js")))
    assert kinds <= {"state", "server", "overlay", "frame"}, kinds


def test_background_pushes_only_display_messages_to_pages():
    kinds = set(re.findall(r"(?:broadcast|postMessage)\(\{\s*kind:\s*'([a-z_]+)'", _src("background.js")))
    assert kinds <= {"state", "server", "overlay"}, kinds


def test_server_pushes_only_state_and_pings():
    src = (ROOT / "server" / "main.py").read_text(encoding="utf-8")
    sends = re.findall(r"send_str\((.*)\)\s*$", src, flags=re.M)
    allowed = {"data", 'json.dumps({"kind": "state", "state": self.state()})', "'{\"kind\":\"ping\"}'"}
    assert set(sends) <= allowed, sends
    assert 'data = json.dumps({"kind": "state", "state": self.state()})' in src


def test_snapshot_declares_advisory_mode():
    from server.advisor import Advisor
    from server.betting import BetRamp
    from server.engine.strategy import Strategy, load_or_build
    from server.rules import Rules
    from server.table import Table

    r = Rules.load("infinite_blackjack")
    adv = Advisor(r, Strategy(load_or_build(r)["tables"]), BetRamp(unit=0.5))
    snap = adv.snapshot(Table(r))
    assert snap["mode"] == "advisory"


def test_bet_amount_label():
    from server.betting import BetRamp

    r = BetRamp(unit=0.5, currency="€")
    assert r.signal(3.4)["amount_label"] == "€2.00"   # 4 units
    assert r.signal(0.2)["amount"] is None                  # sit out
