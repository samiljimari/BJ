"""Evaluate every initial deal (player two cards x dealer upcard) for a composition.

Used for:
* the house edge / round EV of a composition (validation against published RTP),
* generating a total-dependent basic strategy table for a rule set.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cards import full_composition, soft_total
from ..rules import Rules
from .ev import Analysis, analyze


@dataclass
class DealRecord:
    c1: int
    c2: int
    up: int
    prob: float
    p_dealer_bj: float
    analysis: Analysis
    round_ev: float


def _p_dealer_bj(comp, up: int) -> float:
    n = float(sum(comp))
    if up == 1:
        return comp[9] / n
    if up == 10:
        return comp[0] / n
    return 0.0


def enumerate_deals(rules: Rules, comp=None) -> list[DealRecord]:
    comp = list(comp) if comp is not None else full_composition(rules.decks)
    N = float(sum(comp))
    peek = rules.peek_upcards
    out: list[DealRecord] = []
    for c1 in range(1, 11):
        p1 = comp[c1 - 1] / N
        if p1 <= 0:
            continue
        comp[c1 - 1] -= 1
        for c2 in range(c1, 11):
            p2 = comp[c2 - 1] / (N - 1)
            if p2 <= 0:
                continue
            comp[c2 - 1] -= 1
            for up in range(1, 11):
                p3 = comp[up - 1] / (N - 2)
                if p3 <= 0:
                    continue
                comp[up - 1] -= 1
                prob = p1 * p2 * p3 * (1 if c1 == c2 else 2)
                a = analyze(comp, [c1, c2], up, rules)
                pbj = _p_dealer_bj(comp, up)
                if a.best == "blackjack":
                    rev = (1 - pbj) * rules.blackjack_pays
                elif up in peek:
                    rev = pbj * -1.0 + (1 - pbj) * a.ev[a.best]
                else:
                    rev = a.ev[a.best]  # unresolved BJ risk already folded in
                out.append(DealRecord(c1, c2, up, prob, pbj, a, rev))
                comp[up - 1] += 1
            comp[c2 - 1] += 1
        comp[c1 - 1] += 1
    return out


def round_ev(rules: Rules, comp=None, deals: list[DealRecord] | None = None) -> float:
    """Expected result of one round (initial-bet units) with composition-dependent
    optimal play and no insurance. House edge = -round_ev."""
    deals = deals if deals is not None else enumerate_deals(rules, comp)
    tot_p = sum(d.prob for d in deals)
    return sum(d.prob * d.round_ev for d in deals) / tot_p


def hand_key(c1: int, c2: int) -> tuple[int, bool]:
    t = c1 + c2
    st = soft_total(t, 1 in (c1, c2))
    return st, st != t
