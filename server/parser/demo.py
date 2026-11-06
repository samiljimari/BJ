"""Parser for the bundled demo table (server/demo.py).

The demo protocol is deliberately "provider-like" (its own message names, card codes
like "Kh"/"10s", a hidden hole card) so the full extension -> server -> parser ->
overlay path can be tested without a casino. Use it as a template for real parsers.
"""

from __future__ import annotations

from .base import Parser


class DemoParser(Parser):
    name = "demo"

    def parse(self, frame: dict) -> list[dict]:
        if frame.get("dir") != "in":
            return []
        msg = self.json(frame)
        if not isinstance(msg, dict):
            return []
        m = msg.get("msg")
        if m == "shuffle":
            return [{"type": "shoe_change"}]
        if m == "newRound":
            return [{"type": "round_start", "round_id": str(msg.get("id")), "seats": ["shared"]}]
        if m == "deal":
            code = msg.get("card")
            if not code or code == "XX":  # face-down card: not visible yet
                return []
            rank, suit = code[:-1], code[-1]
            who = msg.get("to")
            if who == "dealer":
                target = {"kind": "dealer"}
            elif who == "burn":
                target = {"kind": "burn"}
            else:
                target = {"kind": "player", "seat": "shared", "hand": int(msg.get("box", 0))}
            return [{"type": "card", "rank": rank, "suit": suit.lower(), "target": target,
                     "round_id": str(msg.get("round"))}]
        if m == "decision":
            return [{"type": "decision", "seat": "shared", "hand": int(msg.get("box", 0)),
                     "action": msg.get("action")}]
        if m == "result":
            return [{"type": "round_end", "round_id": str(msg.get("id")), "result": msg.get("outcome")}]
        return []
