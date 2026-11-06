"""Round / hand state built from normalized events.

Normalized events (project notes section 5):
  {"type": "round_start", "round_id": "...", "seats": ["shared"]}
  {"type": "card", "rank": "T", "suit": "h", "target": {"kind": "player|dealer|other|burn", "seat": "shared", "hand": 0}}
  {"type": "decision", "seat": "shared", "hand": 0, "action": "hit|stand|double|split|surrender|insurance"}
  {"type": "round_end", "round_id": "...", "result": "..."}
  {"type": "shoe_change"}
A card with rank null/"?" (face-down burn) is ignored by the count.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .cards import normalize_rank, parse_rank
from .rules import Rules
from .shoe import Shoe


@dataclass
class HandState:
    ranks: list[str] = field(default_factory=list)
    doubled: bool = False
    from_split: bool = False
    split_aces: bool = False
    surrendered: bool = False
    done: bool = False

    @property
    def values(self) -> list[int]:
        return [parse_rank(r) for r in self.ranks]

    def total(self) -> tuple[int, bool]:
        vals = self.values
        t = sum(vals)
        if 1 in vals and t + 10 <= 21:
            return t + 10, True
        return t, False

    def to_dict(self) -> dict:
        t, soft = self.total()
        return {"cards": list(self.ranks), "total": t, "soft": soft, "doubled": self.doubled,
                "from_split": self.from_split, "done": self.done, "surrendered": self.surrendered,
                "bust": t > 21}


@dataclass
class SeatState:
    hands: list[HandState] = field(default_factory=lambda: [HandState()])
    splits: int = 0
    insurance: bool = False
    acted: bool = False  # any decision taken (surrender only allowed before)


@dataclass
class Round:
    round_id: str
    started: float = field(default_factory=time.time)
    dealer: list[str] = field(default_factory=list)
    seats: dict[str, SeatState] = field(default_factory=dict)
    ended: bool = False
    result: str | None = None

    def seat(self, name: str) -> SeatState:
        if name not in self.seats:
            self.seats[name] = SeatState()
        return self.seats[name]

    @property
    def phase(self) -> str:
        if self.ended:
            return "ended"
        if len(self.dealer) >= 2:
            return "dealer"
        if not self.dealer or not any(len(h.ranks) >= 2 for s in self.seats.values() for h in s.hands):
            return "dealing"
        return "decisions"


class Table:
    def __init__(self, rules: Rules, my_seats: tuple[str, ...] = ("shared",)):
        self.rules = rules
        self.my_seats = set(my_seats)
        self.shoe = Shoe(rules.decks)
        self.round: Round | None = None
        self.history: list[dict] = []   # events since last shoe change (for undo/replay)
        self.rounds_this_shoe = 0
        self.warnings: list[str] = []
        self._auto_id = 0
        # False until we have seen a shoe change: if we joined mid-shoe the count
        # is missing the cards dealt before we started watching.
        self.from_shoe_start = False

    # ----------------------------------------------------------------- events
    def apply(self, ev: dict, record: bool = True) -> None:
        t = ev.get("type")
        if t == "shoe_change":
            self.shoe.reset()
            self.round = None
            self.history = []
            self.rounds_this_shoe = 0
            self.warnings = []
            self.from_shoe_start = True
            return
        if record:
            self.history.append(ev)
        if t == "round_start":
            self._new_round(ev.get("round_id"))
        elif t == "card":
            self._card(ev)
        elif t == "decision":
            self._decision(ev)
        elif t == "round_end":
            if self.round:
                self.round.ended = True
                self.round.result = ev.get("result")
                for s in self.round.seats.values():
                    for h in s.hands:
                        h.done = True

    def undo(self) -> dict | None:
        """Remove the last event and rebuild state by replaying the shoe's history."""
        if not self.history:
            return None
        last = self.history.pop()
        events = self.history
        shoe_no = self.shoe.shoe_number
        self.shoe.reset()
        self.shoe.shoe_number = shoe_no
        self.round = None
        self.rounds_this_shoe = 0
        self.history = []
        self.warnings = []
        for e in events:
            self.apply(e)
        return last

    # -------------------------------------------------------------- internals
    def _new_round(self, rid: str | None) -> Round:
        if self.round and not self.round.ended:
            self.round.ended = True
        self._auto_id += 1
        self.round = Round(round_id=str(rid or f"r{self._auto_id}"))
        self.rounds_this_shoe += 1
        return self.round

    def _card(self, ev: dict) -> None:
        rank = ev.get("rank")
        target = ev.get("target") or {}
        kind = target.get("kind", "other")
        if rank in (None, "", "?"):
            return  # face-down / unknown card: not part of the count
        rank = normalize_rank(rank)
        if not self.shoe.add(rank):
            self.warnings.append(self.shoe.warnings[-1].message)
            return
        if kind in ("other", "burn"):
            return
        if self.round is None or self.round.ended:
            self._new_round(None)
        r = self.round
        if kind == "dealer":
            r.dealer.append(rank)
            if len(r.dealer) >= 2:
                for s in r.seats.values():
                    for h in s.hands:
                        h.done = True
            return
        seat = r.seat(str(target.get("seat", "shared")))
        idx = int(target.get("hand", 0) or 0)
        while len(seat.hands) <= idx:
            seat.hands.append(HandState(from_split=True))
        h = seat.hands[idx]
        h.ranks.append(rank)
        self._auto_done(h)

    def _auto_done(self, h: HandState) -> None:
        t, _ = h.total()
        n = len(h.ranks)
        if t > 21 or (t == 21 and (self.rules.auto_stand_21 or n == 2)):
            h.done = True
        elif self.rules.six_card_charlie and n >= 6:
            h.done = True
        elif h.doubled and n >= 3:
            h.done = True
        elif h.split_aces and n >= 2 and not self.rules.hit_split_aces:
            h.done = True

    def _decision(self, ev: dict) -> None:
        if not self.round:
            return
        seat = self.round.seat(str(ev.get("seat", "shared")))
        idx = int(ev.get("hand", 0) or 0)
        if idx >= len(seat.hands):
            return
        h = seat.hands[idx]
        action = ev.get("action")
        if action != "insurance":
            seat.acted = True
        if action == "stand":
            h.done = True
        elif action == "double":
            h.doubled = True
            self._auto_done(h)
        elif action == "surrender":
            h.surrendered = True
            h.done = True
        elif action == "insurance":
            seat.insurance = True
        elif action == "split" and len(h.ranks) == 2:
            moved = h.ranks.pop()
            aces = parse_rank(moved) == 1
            h.from_split = True
            h.split_aces = aces
            seat.hands.insert(idx + 1, HandState(ranks=[moved], from_split=True, split_aces=aces))
            seat.splits += 1

    # ----------------------------------------------------- manual-entry helpers
    def my_seat(self) -> str:
        return sorted(self.my_seats)[0]

    def dealer_done(self) -> bool:
        """Dealer hand complete per the rules (stands, busts or has blackjack)."""
        r = self.round
        if not r or len(r.dealer) < 2:
            return False
        vals = [parse_rank(x) for x in r.dealer]
        t = sum(vals)
        soft = 1 in vals and t + 10 <= 21
        st = t + 10 if soft else t
        if st > 21 or st > 17:
            return True
        return st == 17 and not (soft and self.rules.dealer_hits_soft_17)

    def auto_target(self) -> dict:
        """Where the next manually entered card most likely goes (Infinite deal order:
        player, dealer up, player, then player hits, then dealer)."""
        seat = self.my_seat()
        r = self.round
        if r is None or r.ended or self.dealer_done():
            return {"kind": "player", "seat": seat, "hand": 0, "new_round": True}
        s = r.seats.get(seat)
        first = len(s.hands[0].ranks) if s else 0
        if not r.dealer:
            return {"kind": "player", "seat": seat, "hand": 0} if first == 0 else {"kind": "dealer"}
        if len(r.dealer) == 1 and s:
            for i, h in enumerate(s.hands):
                if not h.done:
                    return {"kind": "player", "seat": seat, "hand": i}
        if len(r.dealer) == 1 and not s:
            return {"kind": "player", "seat": seat, "hand": 0}
        return {"kind": "dealer"}

    def current_hand_index(self) -> int | None:
        r = self.round
        s = r.seats.get(self.my_seat()) if r else None
        if not s:
            return None
        for i, h in enumerate(s.hands):
            if not h.done:
                return i
        return None

    # ------------------------------------------------------------------ views
    def active_hand(self) -> tuple[str, int, HandState] | None:
        """The hand of mine currently awaiting a decision (if any)."""
        r = self.round
        if not r or r.ended or len(r.dealer) != 1:
            return None
        for name in sorted(r.seats):
            if name not in self.my_seats:
                continue
            for i, h in enumerate(r.seats[name].hands):
                if h.done:
                    continue
                if len(h.ranks) >= 2:
                    return name, i, h
                return None  # waiting for this hand's next card
        return None

    def round_view(self) -> dict | None:
        r = self.round
        if not r:
            return None
        return {
            "round_id": r.round_id,
            "phase": "ended" if self.dealer_done() else r.phase,
            "dealer": list(r.dealer),
            "seats": {name: {"hands": [h.to_dict() for h in s.hands], "splits": s.splits,
                             "insurance": s.insurance, "mine": name in self.my_seats}
                      for name, s in r.seats.items()},
            "result": r.result,
        }
