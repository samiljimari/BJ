"""Composition-dependent expected values for player actions.

All EVs are in units of the hand's initial bet.

Approximations (documented, deliberate):
* By default the dealer's final-total distribution is computed once, from the
  composition at decision time. Cards the player draws while hitting do update
  the player's own draw probabilities, but not the dealer's distribution.
  In an 8-deck shoe the error is ~0.001 EV. ``exact=True`` recomputes the dealer
  distribution at every player state (slow; used to validate the approximation).
* Split: each split hand is valued independently from the same composition
  (no card-removal interaction between the two hands). Resplits recurse the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..cards import soft_total
from ..rules import Rules
from .dealer import W, dealer_probs_cached

ACTION_ORDER = ("stand", "hit", "double", "split", "surrender")
ACTION_CODES = {"stand": "S", "hit": "H", "double": "D", "split": "P", "surrender": "R"}


def stand_table(D) -> list[float]:
    """EV of standing on each best total 0..21 versus dealer distribution D."""
    bust = D[5]
    tab = [2.0 * bust - 1.0] * 22  # totals <= 16 win only when the dealer busts
    for t in range(17, 22):
        win = bust
        lose = 0.0
        for k in range(5):
            dt = 17 + k
            if dt < t:
                win += D[k]
            elif dt > t:
                lose += D[k]
        tab[t] = win - lose
    return tab


class EVCalc:
    """EV calculator bound to one composition + dealer upcard."""

    def __init__(self, comp, up: int, rules: Rules, exact: bool = False):
        self.base = list(comp)
        self.n = float(sum(self.base))
        self.up = up
        self.rules = rules
        self.h17 = rules.dealer_hits_soft_17
        self.exact = exact
        D, p_bj = dealer_probs_cached(tuple(self.base), up, self.h17)
        self.D = D
        self.p_bj = p_bj
        self.stand_tab = stand_table(D)
        self.charlie = rules.six_card_charlie
        self.auto21 = rules.auto_stand_21
        self._hit_memo: dict = {}
        self._split_memo: dict = {}
        self._dealer_memo: dict = {0: self.stand_tab}

    # ------------------------------------------------------------ primitives
    def _stand(self, st: int, dkey: int, comp) -> float:
        if not self.exact or dkey == 0:
            return self.stand_tab[st]
        tab = self._dealer_memo.get(dkey)
        if tab is None:
            D, _ = dealer_probs_cached(tuple(comp), self.up, self.h17)
            tab = stand_table(D)
            self._dealer_memo[dkey] = tab
        return tab[st]

    def _best(self, comp, n, total, has_ace, ncards, dkey) -> float:
        """Best of stand/hit for a hand that may only stand or hit."""
        if total > 21:
            return -1.0
        if self.charlie and ncards >= 6:
            return 1.0
        st = total + 10 if has_ace and total + 10 <= 21 else total
        s = self._stand(st, dkey, comp)
        if st == 21 and self.auto21:
            return s
        h = self._hit(comp, n, total, has_ace, ncards, dkey)
        return s if s >= h else h

    def _hit(self, comp, n, total, has_ace, ncards, dkey) -> float:
        key = (dkey, total, has_ace, ncards)
        r = self._hit_memo.get(key)
        if r is not None:
            return r
        ev = 0.0
        for i in range(10):
            c = comp[i]
            if c <= 0:
                continue
            p = c / n
            t = total + i + 1
            if t > 21:
                ev -= p
                continue
            comp[i] = c - 1
            ev += p * self._best(comp, n - 1, t, has_ace or i == 0, ncards + 1, dkey + W[i])
            comp[i] = c
        self._hit_memo[key] = ev
        return ev

    def _double(self, comp, n, total, has_ace, dkey) -> float:
        ev = 0.0
        for i in range(10):
            c = comp[i]
            if c <= 0:
                continue
            p = c / n
            t = total + i + 1
            if t > 21:
                ev -= 2.0 * p
                continue
            st = soft_total(t, has_ace or i == 0)
            if self.exact:
                comp[i] = c - 1
                s = self._stand(st, dkey + W[i], comp)
                comp[i] = c
            else:
                s = self.stand_tab[st]
            ev += 2.0 * p * s
        return ev

    def _split_hand(self, comp, n, v, resplits_left, dkey) -> float:
        """EV of ONE hand that starts with the single card ``v`` after a split."""
        key = (dkey, v, resplits_left)
        r = self._split_memo.get(key)
        if r is not None:
            return r
        rules = self.rules
        ev = 0.0
        for i in range(10):
            c = comp[i]
            if c <= 0:
                continue
            p = c / n
            w = i + 1
            comp[i] = c - 1
            nk = dkey + W[i]
            total = v + w
            has_ace = v == 1 or w == 1
            st = soft_total(total, has_ace)
            if v == 1 and not rules.hit_split_aces:
                val = self._stand(st, nk, comp)  # split aces: one card, 21 is not a blackjack
                if w == 1 and rules.resplit_aces and resplits_left > 0:
                    val = max(val, 2.0 * self._split_hand(comp, n - 1, 1, resplits_left - 1, nk))
            else:
                val = self._best(comp, n - 1, total, has_ace, 2, nk)
                if rules.double_after_split and rules.can_double_total(st, st != total):
                    val = max(val, self._double(comp, n - 1, total, has_ace, nk))
                if w == v and resplits_left > 0 and (v != 1 or rules.resplit_aces):
                    rs = 2.0 * self._split_hand(comp, n - 1, v, resplits_left - 1, nk)
                    if v == 10 and rules.split_requires_same_rank:
                        # only ~1/4 of ten-valued cards match the rank being split
                        val = 0.25 * max(val, rs) + 0.75 * val
                    else:
                        val = max(val, rs)
            comp[i] = c
            ev += p * val
        self._split_memo[key] = ev
        return ev

    # ------------------------------------------------------------- public API
    def stand(self, total, has_ace) -> float:
        return self.stand_tab[soft_total(total, has_ace)]

    def hit(self, total, has_ace, ncards) -> float:
        return self._hit(list(self.base), self.n, total, has_ace, ncards, 0)

    def best_stand_hit(self, total, has_ace, ncards) -> float:
        return self._best(list(self.base), self.n, total, has_ace, ncards, 0)

    def double(self, total, has_ace) -> float:
        return self._double(list(self.base), self.n, total, has_ace, 0)

    def split(self, v: int, splits_done: int = 0) -> float:
        resplits_left = max(0, self.rules.max_splits - splits_done - 1)
        return 2.0 * self._split_hand(list(self.base), self.n, v, resplits_left, 0)


@dataclass
class Analysis:
    total: int
    soft: bool
    ncards: int
    ev: dict = field(default_factory=dict)       # action -> EV (initial-bet units)
    best: str | None = None                     # action name, or 'blackjack' / 'charlie' / 'bust'
    second: str | None = None
    margin: float = 0.0
    p_dealer_bj: float = 0.0
    dealer_bj_resolved: bool = True               # True if the dealer already peeked
    insurance_ev: float | None = None             # EV of taking insurance (main-bet units)
    p_ten: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "soft": self.soft,
            "ncards": self.ncards,
            "ev": {k: round(v, 4) for k, v in self.ev.items()},
            "best": self.best,
            "second": self.second,
            "margin": round(self.margin, 4),
            "p_dealer_bj": round(self.p_dealer_bj, 4),
            "dealer_bj_resolved": self.dealer_bj_resolved,
            "insurance_ev": None if self.insurance_ev is None else round(self.insurance_ev, 4),
            "insurance_take": None if self.insurance_ev is None else self.insurance_ev > 0,
            "p_ten": None if self.p_ten is None else round(self.p_ten, 4),
            "note": self.note,
        }


AUTO_EXACT_MARGIN = 0.005


def analyze(comp, cards: list[int], up: int, rules: Rules, *, exact: bool | str = "auto",
            **kw) -> Analysis:
    """Evaluate every legal action for the current hand.

    ``comp``  - composition of unseen cards (all visible cards already removed).
    ``cards`` - card values (1..10) in the hand.
    ``exact`` - False: fast (fixed dealer distribution); True: exact dealer
                distribution at every player state; "auto": fast, then exact when
                the best two actions are within AUTO_EXACT_MARGIN.
    Keyword options: can_double, can_split, can_surrender, split_hand, splits_done,
    doubled, same_rank_pair (False for e.g. K-Q when only equal ranks may split).
    """
    if exact == "auto":
        a = _analyze(comp, cards, up, rules, exact=False, **kw)
        if a.second is not None and a.margin < AUTO_EXACT_MARGIN:
            a = _analyze(comp, cards, up, rules, exact=True, **kw)
            a.note = (a.note + " " if a.note else "") + "(exact)"
        return a
    return _analyze(comp, cards, up, rules, exact=bool(exact), **kw)


def _analyze(comp, cards: list[int], up: int, rules: Rules, *,
             can_double: bool = True, can_split: bool = True, can_surrender: bool = True,
             split_hand: bool = False, splits_done: int = 0, doubled: bool = False,
             same_rank_pair: bool = True, exact: bool = False) -> Analysis:
    total = sum(cards)
    has_ace = 1 in cards
    st = soft_total(total, has_ace)
    nc = len(cards)
    a = Analysis(total=st, soft=st != total, ncards=nc)

    if total > 21:
        a.best = "bust"
        return a
    if nc == 2 and st == 21 and not split_hand:
        a.best = "blackjack"
        a.note = "Blackjack"
        _insurance(a, comp, up, rules)
        return a
    if rules.six_card_charlie and nc >= 6:
        a.best = "charlie"
        a.note = "Six Card Charlie"
        return a
    if doubled:
        a.best = "stand"
        a.note = "Doubled - hand complete"
        return a

    calc = EVCalc(comp, up, rules, exact=exact)
    peeked = up in rules.peek_upcards
    a.p_dealer_bj = calc.p_bj
    a.dealer_bj_resolved = peeked or up not in (1, 10)

    ev = {"stand": calc.stand(total, has_ace)}
    if split_hand and nc == 2 and cards[0] == 1 and not rules.hit_split_aces:
        a.note = "Split aces - one card only"
    elif st == 21 and rules.auto_stand_21:
        a.note = "21 - auto stand"
    else:
        ev["hit"] = calc.hit(total, has_ace, nc)
        if (can_double and nc == 2 and rules.can_double_total(st, st != total)
                and (not split_hand or rules.double_after_split)):
            ev["double"] = calc.double(total, has_ace)
    if (can_split and nc == 2 and cards[0] == cards[1] and same_rank_pair
            and splits_done < rules.max_splits
            and (not split_hand or cards[0] != 1 or rules.resplit_aces)):
        ev["split"] = calc.split(cards[0], splits_done)
    if can_surrender and rules.surrender != "none" and nc == 2 and not split_hand:
        ev["surrender"] = -0.5

    # Dealer blackjack still possible (no peek for this upcard): fold that risk in.
    if not a.dealer_bj_resolved and calc.p_bj > 0:
        p = calc.p_bj
        for act in list(ev):
            if act == "surrender":
                ev[act] = -0.5 if rules.surrender == "early" else (1 - p) * -0.5 + p * -1.0
                continue
            if rules.no_peek_lose_all:
                loss = -2.0 if act in ("double", "split") else -1.0
            else:
                loss = -0.5 if split_hand else -1.0
            ev[act] = (1 - p) * ev[act] + p * loss

    a.ev = ev
    ranked = sorted(ev.items(), key=lambda kv: kv[1], reverse=True)
    a.best = ranked[0][0]
    if len(ranked) > 1:
        a.second = ranked[1][0]
        a.margin = ranked[0][1] - ranked[1][1]
    if nc == 2 and not split_hand:
        _insurance(a, comp, up, rules)
    return a


def _insurance(a: Analysis, comp, up: int, rules: Rules) -> None:
    if up != 1 or not rules.insurance:
        return
    n = float(sum(comp))
    if n <= 0:
        return
    p_ten = comp[9] / n
    a.p_ten = p_ten
    # Insurance stake = half the main bet, pays 2:1.
    a.insurance_ev = 0.5 * (3.0 * p_ten - 1.0)
