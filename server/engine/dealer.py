"""Dealer final-total distribution from an exact shoe composition.

Outcome vector index: 0..4 -> final 17..21, 5 -> bust.
The returned distribution is conditional on the dealer NOT having blackjack;
the blackjack probability is returned separately so callers can apply peek /
no-peek rules.
"""

from __future__ import annotations

from functools import lru_cache

BUST = 5
# Memo key weights: a dealer never draws 32+ cards of one value.
W = tuple(32 ** i for i in range(10))


def _rec(comp: list, n: float, total: int, has_ace: bool, key: int, memo: dict, h17: bool) -> list:
    """Distribution for a dealer holding hard ``total`` who must still draw.

    ``key`` encodes the multiset of cards drawn so far, which (for a fixed
    starting composition and upcard) uniquely identifies this state.
    """
    r = memo.get(key)
    if r is not None:
        return r
    res = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    for i in range(10):
        c = comp[i]
        if c <= 0:
            continue
        p = c / n
        t = total + i + 1
        if t > 21:
            res[5] += p
            continue
        a = has_ace or i == 0
        if a and t + 10 <= 21:
            st = t + 10
            if st >= 17 and not (h17 and st == 17):
                res[st - 17] += p
                continue
        elif t >= 17:
            res[t - 17] += p
            continue
        comp[i] = c - 1
        sub = _rec(comp, n - 1, t, a, key + W[i], memo, h17)
        comp[i] = c
        res[0] += p * sub[0]
        res[1] += p * sub[1]
        res[2] += p * sub[2]
        res[3] += p * sub[3]
        res[4] += p * sub[4]
        res[5] += p * sub[5]
    memo[key] = res
    return res


def dealer_probs(comp, up: int, h17: bool) -> tuple[tuple[float, ...], float]:
    """Return (distribution over [17,18,19,20,21,bust] given no dealer BJ, P(dealer BJ)).

    ``comp`` is the composition of unseen cards (the upcard and all other visible
    cards already removed).
    """
    comp = list(comp)
    n = float(sum(comp))
    memo: dict = {}
    res = [0.0] * 6
    p_bj = 0.0
    for i in range(10):
        c = comp[i]
        if c <= 0:
            continue
        p = c / n
        v = i + 1
        if (up == 1 and v == 10) or (up == 10 and v == 1):
            p_bj += p
            continue
        t = up + v
        a = up == 1 or v == 1
        st = t + 10 if a and t + 10 <= 21 else t
        if st >= 17 and not (h17 and st == 17 and st != t):
            res[st - 17] += p
            continue
        comp[i] = c - 1
        sub = _rec(comp, n - 1, t, a, W[i], memo, h17)
        comp[i] = c
        for k in range(6):
            res[k] += p * sub[k]
    norm = 1.0 - p_bj
    if norm > 0:
        res = [x / norm for x in res]
    return tuple(res), p_bj


@lru_cache(maxsize=4096)
def dealer_probs_cached(comp: tuple, up: int, h17: bool) -> tuple[tuple[float, ...], float]:
    return dealer_probs(comp, up, h17)
