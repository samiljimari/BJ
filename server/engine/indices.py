"""Estimate Hi-Lo index numbers for a rule set using the EV engine.

Method: for a range of true counts build a *synthetic* remaining composition
(Hi-Lo low cards depleted / high cards enriched uniformly so that RC/decks = TC),
evaluate the two competing actions with the EV engine and find the TC where the
deviation becomes better. This is the classic "linear composition" estimate - good
for cross-checking published indices, not a substitute for a full simulation.
"""

from __future__ import annotations

from ..rules import Rules
from .ev import analyze

TC_GRID = [x / 2 for x in range(-20, 31)]  # -10 .. +15


def synthetic_comp(tc: float, decks_remaining: float) -> list[float]:
    D = decks_remaining
    rc = tc * D
    low = 20 * D - rc / 2.0   # 2..6 remaining
    high = 20 * D + rc / 2.0  # T, A remaining
    return [high / 5.0] + [low / 5.0] * 5 + [4.0 * D] * 3 + [high * 4.0 / 5.0]


def representative_cards(hand: str) -> list[int]:
    kind, val = hand.lower().split()
    if kind == "pair":
        v = 1 if val.upper() == "A" else (10 if val.upper() in ("T", "10") else int(val))
        return [v, v]
    t = int(val)
    if kind == "soft":
        return [1, t - 11]
    special = {8: [5, 3], 9: [5, 4], 10: [6, 4], 11: [6, 5]}
    if t in special:
        return special[t]
    if 12 <= t <= 19:
        return [10, t - 10]
    return [t - 2, 2]


_OTHER = {"stand": "hit", "hit": "stand", "double": "hit", "split": "stand", "surrender": "hit"}


def _diff(rules: Rules, tc: float, decks_rem: float, cards: list[int], up: int, action: str) -> float | None:
    comp = synthetic_comp(tc, decks_rem)
    if action == "insurance":
        p_ten = comp[9] / sum(comp)
        return 3 * p_ten - 1
    a = analyze(comp, cards, up, rules, exact=False)
    other = _OTHER[action]
    if action == "split" and cards[0] == 10:
        other = "stand"
    if action not in a.ev or other not in a.ev:
        return None
    return a.ev[action] - a.ev[other]


def estimate_index(rules: Rules, hand: str, up: int, action: str, decks_remaining: float = 4.0):
    """Return (index, better_when) where better_when is '>=' if the action is better
    above the index, '<' if below, or (None, None) if no crossing in -10..+15."""
    cards = [] if hand == "insurance" else representative_cards(hand)
    diffs = [(tc, _diff(rules, tc, decks_remaining, cards, up, action)) for tc in TC_GRID]
    diffs = [(tc, d) for tc, d in diffs if d is not None]
    for (t0, d0), (t1, d1) in zip(diffs, diffs[1:]):
        if (d0 < 0) != (d1 < 0):
            x = t0 + (t1 - t0) * (-d0) / (d1 - d0) if d1 != d0 else t0
            return round(x, 1), (">=" if d1 > d0 else "<")
    if diffs and all(d >= 0 for _, d in diffs):
        return float("-inf"), ">="
    if diffs and all(d < 0 for _, d in diffs):
        return float("inf"), ">="
    return None, None


def generate(rules: Rules, deviations: list[dict], decks_remaining: float = 4.0) -> list[dict]:
    out = []
    for d in deviations:
        hand = d["hand"]
        if hand.startswith("_"):
            continue
        up_s = str(d["up"]).upper()
        up = 1 if up_s == "A" else (10 if up_s in ("T", "10") else int(up_s))
        idx, when = estimate_index(rules, hand, up, d["action"], decks_remaining)
        out.append({**d, "reference_index": d["index"], "reference_when": d.get("when", ">="),
                    "index": idx, "when": when})
    return out
