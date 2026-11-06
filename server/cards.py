"""Card helpers.

Internally a card is its blackjack value 1..10 (1 = ace, 10 = any ten-valued card).
A composition is a list/tuple of 10 counts where index ``v - 1`` holds the number of
cards of value ``v`` (index 0 = aces, index 9 = tens).
"""

from __future__ import annotations

ACE = 1
TEN = 10
VALUES = tuple(range(1, 11))
VALUE_CHARS = "A23456789T"

# Hi-Lo tag per value (index v - 1).
HILO = (-1, 1, 1, 1, 1, 1, 0, 0, 0, -1)

_RANK_ALIASES = {
    "A": 1, "ACE": 1, "1": 1, "11": 1,
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "T": 10, "10": 10, "J": 10, "Q": 10, "K": 10,
    "JACK": 10, "QUEEN": 10, "KING": 10, "TEN": 10,
    "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6,
    "SEVEN": 7, "EIGHT": 8, "NINE": 9,
}


def parse_rank(rank: str | int) -> int:
    """Return the blackjack value (1..10) for a rank such as 'A', '7', 'T', '10', 'K'."""
    if isinstance(rank, int):
        if 1 <= rank <= 10:
            return rank
        if rank in (11, 12, 13):  # J/Q/K encoded numerically
            return 10
        raise ValueError(f"bad rank {rank!r}")
    key = str(rank).strip().upper()
    if key in _RANK_ALIASES:
        return _RANK_ALIASES[key]
    raise ValueError(f"bad rank {rank!r}")


def normalize_rank(rank: str | int) -> str:
    """Canonical rank string: 'A','2'..'9','T','J','Q','K'. Keeps J/Q/K distinct
    (matters for 'split equal rank only' rules)."""
    if isinstance(rank, int):
        return {1: "A", 10: "T", 11: "J", 12: "Q", 13: "K"}.get(rank, str(rank))
    key = str(rank).strip().upper()
    if key in ("10", "TEN"):
        return "T"
    if key in ("J", "Q", "K", "T", "A"):
        return key
    if key in ("JACK", "QUEEN", "KING", "ACE"):
        return key[0]
    v = parse_rank(key)
    return VALUE_CHARS[v - 1]


def value_char(v: int) -> str:
    return VALUE_CHARS[v - 1]


def full_composition(decks: int) -> list[int]:
    return [4 * decks] * 9 + [16 * decks]


def hand_total(values) -> tuple[int, bool]:
    """Return (best total, is_soft) for a list of card values."""
    total = sum(values)
    if ACE in values and total + 10 <= 21:
        return total + 10, True
    return total, False


def hard_total_and_ace(values) -> tuple[int, bool]:
    """(hard total counting aces as 1, has_ace)."""
    return sum(values), ACE in values


def soft_total(hard: int, has_ace: bool) -> int:
    return hard + 10 if has_ace and hard + 10 <= 21 else hard
