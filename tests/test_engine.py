from functools import lru_cache

import pytest

from server.cards import full_composition
from server.engine.dealer import dealer_probs
from server.engine.ev import analyze
from server.engine.indices import generate
from server.engine.strategy import build, load_deviations
from server.rules import Rules

STD = Rules.load("standard_8d_s17_das")

# Textbook 8-deck, S17, DAS, no surrender basic strategy (upcards 2..9, T, A).
HARD = {5: "HHHHHHHHHH", 6: "HHHHHHHHHH", 7: "HHHHHHHHHH", 8: "HHHHHHHHHH",
        9: "HDDDDHHHHH", 10: "DDDDDDDDHH", 11: "DDDDDDDDDH", 12: "HHSSSHHHHH",
        13: "SSSSSHHHHH", 14: "SSSSSHHHHH", 15: "SSSSSHHHHH", 16: "SSSSSHHHHH",
        17: "SSSSSSSSSS", 18: "SSSSSSSSSS", 19: "SSSSSSSSSS", 20: "SSSSSSSSSS"}
SOFT = {13: "HHHDDHHHHH", 14: "HHHDDHHHHH", 15: "HHDDDHHHHH", 16: "HHDDDHHHHH",
        17: "HDDDDHHHHH", 18: ["S", "Ds", "Ds", "Ds", "Ds", "S", "S", "H", "H", "H"],
        19: "SSSSSSSSSS", 20: "SSSSSSSSSS"}
PAIRS = {"A": "PPPPPPPPPP", "T": "----------", "9": "PPPPP-PP--", "8": "PPPPPPPPPP",
         "7": "PPPPPP----", "6": "PPPPP-----", "5": "----------", "4": "---PP-----",
         "3": "PPPPPP----", "2": "PPPPPP----"}
UPS = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "A"]


@pytest.fixture(scope="module")
def std_build():
    return build(STD)


def test_dealer_distribution_sums_to_one():
    full = full_composition(8)
    for up in range(1, 11):
        c = list(full)
        c[up - 1] -= 1
        D, pbj = dealer_probs(c, up, False)
        assert abs(sum(D) - 1) < 1e-12
        assert (pbj > 0) == (up in (1, 10))


def test_dealer_matches_independent_infinite_deck():
    P = [1 / 13] * 9 + [4 / 13]

    @lru_cache(None)
    def bust(total, ace):
        st = total + 10 if ace and total + 10 <= 21 else total
        if total > 21:
            return 1.0
        if st >= 17:
            return 0.0
        return sum(P[i] * bust(total + i + 1, ace or i == 0) for i in range(10))

    big = [4000] * 9 + [16000]
    for up in range(2, 10):
        inf = sum(P[i] * bust(up + i + 1, i == 0) for i in range(10))
        D, _ = dealer_probs(big, up, False)
        assert abs(D[5] - inf) < 2e-4


def test_known_ev_16_vs_10():
    c = full_composition(8)
    for x in (10, 6, 10):
        c[x - 1] -= 1
    a = analyze(c, [10, 6], 10, STD)
    assert a.best == "hit"
    assert abs(a.ev["stand"] - (-0.5408)) < 0.002
    assert abs(a.ev["hit"] - (-0.5358)) < 0.002


def test_textbook_basic_strategy(std_build):
    t = std_build["tables"]
    for total, row in HARD.items():
        assert [t["hard"][str(total)][u] for u in UPS] == list(row), f"hard {total}"
    for total, row in SOFT.items():
        assert [t["soft"][str(total)][u] for u in UPS] == list(row), f"soft {total}"
    for v, row in PAIRS.items():
        assert [t["pairs"][v][u] for u in UPS] == list(row), f"pair {v}"


def test_house_edge_plausible(std_build):
    edge = -std_build["round_ev"]
    assert 0.003 < edge < 0.006  # 8D S17 DAS is ~0.4-0.55% depending on split rules


def test_six_card_charlie_lowers_edge():
    base = Rules.load("infinite_blackjack")
    with_c = -build(base)["round_ev"]
    without = -build(base.replace(six_card_charlie=False))["round_ev"]
    assert 0.001 < without - with_c < 0.0025  # published ~0.16%


def test_indices_close_to_illustrious_18():
    rows = generate(STD, load_deviations())
    for r in rows:
        assert r["index"] is not None, r
        assert r["when"] == r["reference_when"], r
        assert abs(r["index"] - r["reference_index"]) <= 1.0, r


def test_insurance_from_composition():
    c = full_composition(8)
    c[0] -= 1      # dealer ace
    c[9] -= 60     # lots of tens gone -> insurance bad
    a = analyze(c, [5, 6], 1, STD)
    assert a.insurance_ev < 0
    c = full_composition(8)
    c[0] -= 1
    for i in range(1, 6):
        c[i] -= 20  # small cards gone -> tens rich
    a = analyze(c, [5, 6], 1, STD)
    assert a.p_ten > 1 / 3 and a.insurance_ev > 0


def test_exact_mode_agrees_with_fast_mode():
    c = full_composition(8)
    for x in (2, 3, 6):
        c[x - 1] -= 1
    fast = analyze(c, [2, 3], 6, STD, exact=False)
    exact = analyze(c, [2, 3], 6, STD, exact=True)
    for k in fast.ev:
        assert abs(fast.ev[k] - exact.ev[k]) < 0.003
