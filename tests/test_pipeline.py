"""Simulator -> events -> table must agree card for card; demo frames -> parser -> table too."""
import json
import random

from server.demo import round_messages
from server.engine.strategy import Strategy, load_or_build
from server.parser import get_parser
from server.rules import Rules
from server.sim.game import _VAL, SimShoe, play_round
from server.table import Table

R = Rules.load("infinite_blackjack")


def _strategy():
    return Strategy(load_or_build(R)["tables"], None, charlie=R.six_card_charlie)


def test_sim_events_reproduce_shoe_state():
    strat = _strategy()
    sh = SimShoe(R, random.Random(3))
    t = Table(R)
    t.apply({"type": "shoe_change"})
    while not sh.needs_shuffle():
        ev = []
        t.apply({"type": "round_start"})
        play_round(sh, R, strat, use_devs=False, events=ev)
        for e in ev:
            t.apply(e)
        assert t.shoe.running_count == sh.rc
        unseen = [0] * 10
        for r in sh.cards[sh.pos:]:
            unseen[_VAL[r] - 1] += 1
        assert list(t.shoe.remaining) == unseen


def test_demo_parser_counts_full_shoes():
    strat = _strategy()
    rng = random.Random(11)
    sh = SimShoe(R, rng)
    p = get_parser("demo")
    t = Table(R)
    n = 0
    for _ in range(2):
        sh.shuffle()
        msgs = [{"msg": "shuffle"}]
        while not sh.needs_shuffle():
            n += 1
            msgs += [m for m, _ in round_messages(sh, R, strat, rng, n)]
        for m in msgs:
            for ev in p.feed({"kind": "frame", "dir": "in", "binary": False, "data": json.dumps(m)}):
                t.apply(ev)
        assert t.shoe.cards_seen == sh.pos
        assert t.shoe.running_count == sh.rc
        assert t.shoe.integrity_ok


def test_normalized_parser_passthrough():
    p = get_parser("normalized")
    evs = p.feed({"dir": "in", "data": json.dumps({"events": [{"type": "shoe_change"}, {"type": "junk"}]})})
    assert evs == [{"type": "shoe_change"}]
