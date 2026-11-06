"""Fast single-hand blackjack round simulation (one shared hand = Infinite Blackjack)."""

from __future__ import annotations

import random

from ..cards import HILO
from ..engine.strategy import Strategy
from ..rules import Rules

# Shoe stores ranks 1..13 (so "split equal ranks only" can be honoured); value = min(rank, 10).
_VAL = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10)
_HILO_R = (0,) + tuple(HILO[_VAL[r] - 1] for r in range(1, 14))


class SimShoe:
    def __init__(self, rules: Rules, rng: random.Random):
        self.rules = rules
        self.rng = rng
        self.cards = [r for r in range(1, 14) for _ in range(4 * rules.decks)]
        self.n = len(self.cards)
        self.cut = int(self.n * rules.penetration)
        self.shuffle()

    def shuffle(self) -> None:
        self.rng.shuffle(self.cards)
        self.pos = 0
        self.rc = 0
        self.pos += self.rules.burn_cards  # burned face down: not counted

    def needs_shuffle(self) -> bool:
        return self.pos >= self.cut

    def draw(self) -> int:
        """Draw a visible card (counted immediately). Returns the rank."""
        r = self.cards[self.pos]
        self.pos += 1
        self.rc += _HILO_R[r]
        return r

    def draw_hidden(self) -> int:
        r = self.cards[self.pos]
        self.pos += 1
        return r

    def reveal(self, r: int) -> None:
        self.rc += _HILO_R[r]

    def tc(self) -> float:
        return self.rc / max((self.n - self.pos) / 52.0, 0.25)


def _value(ranks) -> tuple[int, bool]:
    t = 0
    ace = False
    for r in ranks:
        v = _VAL[r]
        t += v
        if v == 1:
            ace = True
    if ace and t + 10 <= 21:
        return t + 10, True
    return t, False


class _Hand:
    __slots__ = ("cards", "bet", "from_split", "split_aces", "state")

    def __init__(self, cards, from_split=False, split_aces=False):
        self.cards = cards
        self.bet = 1.0
        self.from_split = from_split
        self.split_aces = split_aces
        self.state = ""  # "", "bust", "charlie", "surrender"


def play_round(sh: SimShoe, R: Rules, S: Strategy, use_devs: bool = True,
               events: list | None = None) -> float:
    """Play one round, return the result in units of the initial bet.

    ``events`` - optional list that receives normalized event dicts (used by the
    fake live feed); None in the hot simulation path.
    """
    def ev_card(rank, kind, hand=0):
        if events is not None:
            events.append({"type": "card", "rank": "A23456789TJQK"[rank - 1],
                           "target": {"kind": kind, "seat": "shared", "hand": hand}})

    p1 = sh.draw(); ev_card(p1, "player")
    up_r = sh.draw(); ev_card(up_r, "dealer")
    p2 = sh.draw(); ev_card(p2, "player")
    hole = sh.draw_hidden()
    up = _VAL[up_r]
    hv = _VAL[hole]
    dealer_bj = (up == 1 and hv == 10) or (up == 10 and hv == 1)
    v1, v2 = _VAL[p1], _VAL[p2]
    player_bj = (v1 == 1 and v2 == 10) or (v1 == 10 and v2 == 1)
    result = 0.0

    if up == 1 and R.insurance and use_devs and S.take_insurance(sh.tc()):
        result += 1.0 if dealer_bj else -0.5
        if events is not None:
            events.append({"type": "decision", "seat": "shared", "hand": 0, "action": "insurance"})

    def finish_dealer(cards):
        sh.reveal(hole)
        if events is not None:
            ev_card(hole, "dealer")
        while True:
            t, soft = _value(cards)
            if t > 21 or t > 17 or (t == 17 and not (soft and R.dealer_hits_soft_17)):
                return t
            c = sh.draw()
            ev_card(c, "dealer")
            cards.append(c)

    peeked = up in R.peek_upcards
    if dealer_bj and peeked:
        sh.reveal(hole)
        if events is not None:
            ev_card(hole, "dealer")
        return result + (0.0 if player_bj else -1.0)
    if player_bj:
        if R.dealer_always_draws or dealer_bj:
            finish_dealer([up_r, hole])
        else:
            sh.reveal(hole)
        return result + (0.0 if dealer_bj else R.blackjack_pays)

    hands = [_Hand([p1, p2])]
    splits = 0
    i = 0
    while i < len(hands):
        h = hands[i]
        hi = i
        if len(h.cards) == 1:
            c = sh.draw(); ev_card(c, "player", hi)
            h.cards.append(c)
        while True:
            total, soft = _value(h.cards)
            nc = len(h.cards)
            if total > 21:
                h.state = "bust"
                break
            if R.six_card_charlie and nc >= 6:
                h.state = "charlie"
                break
            if total == 21 and R.auto_stand_21:
                break
            if h.split_aces and not R.hit_split_aces:
                break
            can_double = nc == 2 and R.can_double_total(total, soft) and (
                not h.from_split or R.double_after_split)
            pair = None
            if nc == 2 and _VAL[h.cards[0]] == _VAL[h.cards[1]]:
                if not (R.split_requires_same_rank and h.cards[0] != h.cards[1]):
                    pair = _VAL[h.cards[0]]
            can_split = pair is not None and splits < R.max_splits and (
                pair != 1 or not h.from_split or R.resplit_aces)
            can_surr = (R.surrender != "none" and nc == 2 and not h.from_split)
            act = S.action(total, soft, nc, pair, up, can_double, can_split, can_surr,
                           sh.tc() if use_devs else None)
            if events is not None and act != "S" and act != "H":
                events.append({"type": "decision", "seat": "shared", "hand": hi,
                               "action": {"D": "double", "P": "split", "R": "surrender"}[act]})
            if act == "S":
                break
            if act == "H":
                c = sh.draw(); ev_card(c, "player", hi)
                h.cards.append(c)
                continue
            if act == "D":
                h.bet = 2.0
                c = sh.draw(); ev_card(c, "player", hi)
                h.cards.append(c)
                if _value(h.cards)[0] > 21:
                    h.state = "bust"
                break
            if act == "R":
                h.state = "surrender"
                break
            # split
            splits += 1
            aces = pair == 1
            moved = h.cards.pop()
            h.from_split = True
            h.split_aces = aces
            hands.insert(i + 1, _Hand([moved], from_split=True, split_aces=aces))
            c = sh.draw(); ev_card(c, "player", hi)
            h.cards.append(c)
        if events is not None and h.state == "":
            events.append({"type": "decision", "seat": "shared", "hand": hi, "action": "stand"})
        i += 1

    live = [h for h in hands if h.state == ""]
    if live or R.dealer_always_draws or dealer_bj:
        dt = finish_dealer([up_r, hole])
    else:
        sh.reveal(hole)
        dt = 0

    if dealer_bj:  # not peeked
        if R.no_peek_lose_all:
            return result - sum(h.bet for h in hands if h.state != "surrender") - 0.5 * sum(
                1 for h in hands if h.state == "surrender")
        return result - 1.0

    for h in hands:
        st = h.state
        if st == "bust":
            result -= h.bet
        elif st == "charlie":
            result += h.bet
        elif st == "surrender":
            result -= 0.5
        else:
            pt = _value(h.cards)[0]
            if dt > 21 or pt > dt:
                result += h.bet
            elif pt < dt:
                result -= h.bet
    return result
