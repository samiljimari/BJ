"""Shoe state: remaining composition, Hi-Lo running/true count, integrity checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from .cards import HILO, full_composition, parse_rank, value_char


@dataclass
class ShoeWarning:
    kind: str
    message: str


class Shoe:
    """Tracks every card seen since the last shuffle.

    ``remaining`` is the composition of all *unseen* cards (including those behind the
    cut card - they are unknown to us, so they are part of the probability pool).
    """

    def __init__(self, decks: int = 8):
        self.decks = decks
        self.total_cards = 52 * decks
        self.shoe_number = 0
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self) -> None:
        self.remaining: list[int] = full_composition(self.decks)
        self.seen: list[int] = []          # values in order seen (for undo / logs)
        self.running_count = 0
        self.warnings: list[ShoeWarning] = []
        self.shoe_number += 1

    def add(self, rank) -> bool:
        """Count a card. Returns False if the card is impossible for this shoe
        (more cards of that rank than the shoe holds) - the card is NOT counted then
        and an integrity warning is recorded."""
        v = parse_rank(rank)
        if self.remaining[v - 1] <= 0:
            self.warnings.append(ShoeWarning(
                "overflow",
                f"Saw more '{value_char(v)}' cards than {self.decks} decks contain "
                f"after {self.cards_seen} cards - missed shoe change, parser error, "
                f"or the game is not dealt from a single shoe.",
            ))
            return False
        self.remaining[v - 1] -= 1
        self.seen.append(v)
        self.running_count += HILO[v - 1]
        return True

    def remove_last(self) -> int | None:
        """Undo the last counted card."""
        if not self.seen:
            return None
        v = self.seen.pop()
        self.remaining[v - 1] += 1
        self.running_count -= HILO[v - 1]
        return v

    # ------------------------------------------------------------- derived
    @property
    def cards_seen(self) -> int:
        return len(self.seen)

    @property
    def cards_left(self) -> int:
        return self.total_cards - self.cards_seen

    @property
    def decks_remaining(self) -> float:
        return self.cards_left / 52.0

    @property
    def true_count(self) -> float:
        d = self.decks_remaining
        # Avoid blow-ups in the (never really reached) tail of the shoe.
        return self.running_count / max(d, 0.25)

    @property
    def penetration(self) -> float:
        return self.cards_seen / self.total_cards

    @property
    def integrity_ok(self) -> bool:
        return not any(w.kind == "overflow" for w in self.warnings)

    def composition(self) -> tuple[int, ...]:
        return tuple(self.remaining)

    def snapshot(self) -> dict:
        return {
            "shoe_number": self.shoe_number,
            "decks": self.decks,
            "running_count": self.running_count,
            "true_count": round(self.true_count, 2),
            "decks_remaining": round(self.decks_remaining, 2),
            "cards_seen": self.cards_seen,
            "cards_left": self.cards_left,
            "penetration": round(self.penetration, 4),
            "remaining": {value_char(i + 1): c for i, c in enumerate(self.remaining)},
            "integrity_ok": self.integrity_ok,
            "warnings": [w.message for w in self.warnings[-5:]],
        }
