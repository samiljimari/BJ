"""Turn table state into the overlay snapshot: count, bet signal, recommended action."""

from __future__ import annotations

import time

from .betting import BetRamp
from .cards import parse_rank
from .engine.ev import analyze
from .engine.strategy import Strategy
from .rules import Rules
from .table import Table

ACTION_LABEL = {"stand": "STAND", "hit": "HIT", "double": "DOUBLE", "split": "SPLIT",
                "surrender": "SURRENDER", "blackjack": "BLACKJACK", "charlie": "CHARLIE",
                "bust": "BUST"}
CODE_TO_ACTION = {"S": "stand", "H": "hit", "D": "double", "P": "split", "R": "surrender"}


class Advisor:
    def __init__(self, rules: Rules, strategy: Strategy, ramp: BetRamp, house_edge: float | None = None):
        self.rules = rules
        self.strategy = strategy
        self.ramp = ramp
        self.house_edge = house_edge

    # ------------------------------------------------------- advice (pure part)
    def advice_inputs(self, table: Table) -> tuple | None:
        """Hashable snapshot of everything the advice depends on (None = no decision now)."""
        act = table.active_hand()
        if act is None:
            return None
        seat_name, idx, h = act
        seat = table.round.seats[seat_name]
        up = parse_rank(table.round.dealer[0])
        same_rank = len(h.ranks) == 2 and h.ranks[0] == h.ranks[1]
        return (
            table.shoe.composition(),
            tuple(h.values),
            up,
            seat_name, idx,
            h.from_split, seat.splits, h.doubled,
            not seat.acted and not h.from_split,      # first decision -> surrender allowed
            same_rank or not self.rules.split_requires_same_rank,
            round(table.shoe.true_count, 2),
            tuple(h.ranks),
        )

    def compute_advice(self, inputs: tuple) -> dict:
        (comp, values, up, seat_name, idx, from_split, splits, doubled, first, same_rank,
         tc, ranks) = inputs
        t0 = time.perf_counter()
        a = analyze(comp, list(values), up, self.rules,
                    can_double=True, can_split=True, can_surrender=first,
                    split_hand=from_split, splits_done=splits, doubled=doubled,
                    same_rank_pair=same_rank)
        d = a.to_dict()
        d["seat"] = seat_name
        d["hand"] = idx
        d["cards"] = list(ranks)
        d["upcard"] = up
        d["label"] = ACTION_LABEL.get(a.best or "", (a.best or "").upper())
        d["ranked"] = sorted(([k, round(v, 4)] for k, v in a.ev.items()), key=lambda kv: -kv[1])
        # Basic strategy + Hi-Lo index cross-check (what a human counter would do).
        if a.best not in ("blackjack", "charlie", "bust") and len(values) >= 2:
            nc = len(values)
            pair = values[0] if nc == 2 and values[0] == values[1] and same_rank else None
            can_double = "double" in a.ev
            can_split = "split" in a.ev
            can_surr = "surrender" in a.ev
            bs = self.strategy.basic(a.total, a.soft, nc, pair, up, can_double, can_split, can_surr)
            idx_play = self.strategy.action(a.total, a.soft, nc, pair, up, can_double, can_split,
                                            can_surr, tc)
            d["basic"] = CODE_TO_ACTION.get(bs)
            d["hilo_index_play"] = CODE_TO_ACTION.get(idx_play)
            d["deviation"] = a.best != d["basic"]
        d["insurance_hilo"] = self.strategy.take_insurance(tc) if up == 1 else None
        d["ms"] = round(1000 * (time.perf_counter() - t0), 1)
        return d

    # ----------------------------------------------------------------- snapshot
    def snapshot(self, table: Table) -> dict:
        shoe = table.shoe.snapshot()
        tc = table.shoe.true_count
        bet = self.ramp.signal(tc)
        return {
            "ts": time.time(),
            # The tool only advises: it never places bets or acts in the game.
            "mode": "advisory",
            "rules": self.rules.name,
            "house_edge": self.house_edge,
            "shoe": shoe,
            "bet": bet,
            "rounds_this_shoe": table.rounds_this_shoe,
            "from_shoe_start": table.from_shoe_start,
            "round": table.round_view(),
            "warnings": list(dict.fromkeys(table.warnings))[-3:],
        }
