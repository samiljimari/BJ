"""Table rules configuration (see rules/*.json)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


@dataclass(frozen=True)
class Rules:
    name: str = "custom"
    decks: int = 8
    dealer_hits_soft_17: bool = False
    blackjack_pays: float = 1.5
    # "any_two" | "9-11" | "10-11"
    double_on: str = "any_two"
    double_after_split: bool = True
    # Number of splits allowed per round (1 = split once -> max 2 hands).
    max_splits: int = 1
    resplit_aces: bool = False
    hit_split_aces: bool = False
    # Only identical ranks may be split (K-K yes, K-Q no). Matters for tens only.
    split_requires_same_rank: bool = True
    # "none" | "late" | "early"
    surrender: str = "none"
    # True/"ace_and_ten": dealer checks for BJ under A and T upcards before players act.
    # "ace": only under an ace.  False/"none": no peek (European / ENHC).
    dealer_peek: bool | str = True
    # Without a peek: True = doubles/splits are lost to a dealer blackjack,
    # False = only the original bet is lost (OBO).
    no_peek_lose_all: bool = False
    six_card_charlie: bool = True
    # A hand of 21 stands automatically (Infinite Blackjack does this).
    auto_stand_21: bool = True
    insurance: bool = True
    # The dealer always completes their hand even if "our" hand busted
    # (true for shared/multi-player tables - affects card usage in the simulator).
    dealer_always_draws: bool = True
    # ---- shoe handling (simulator) ----
    penetration: float = 0.75
    burn_cards: int = 0

    # ------------------------------------------------------------------ helpers
    @property
    def peek_upcards(self) -> frozenset[int]:
        p = self.dealer_peek
        if p is True or p == "ace_and_ten":
            return frozenset((1, 10))
        if p == "ace":
            return frozenset((1,))
        return frozenset()

    def can_double_total(self, hard_total: int, soft: bool) -> bool:
        """Whether doubling is permitted on a two-card hand with this (best) total."""
        if self.double_on == "any_two":
            return True
        # Restricted doubling is normally on *hard* 9-11 / 10-11.
        if soft:
            return False
        if self.double_on == "9-11":
            return 9 <= hard_total <= 11
        if self.double_on == "10-11":
            return 10 <= hard_total <= 11
        raise ValueError(f"unknown double_on {self.double_on!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        d = self.to_dict()
        d.pop("name", None)
        return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]

    @classmethod
    def from_dict(cls, data: dict) -> "Rules":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    @classmethod
    def load(cls, path_or_name: str | Path) -> "Rules":
        p = Path(path_or_name)
        if not p.exists():
            p = RULES_DIR / (str(path_or_name) if str(path_or_name).endswith(".json")
                             else f"{path_or_name}.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        data.setdefault("name", p.stem)
        return cls.from_dict(data)

    def replace(self, **changes) -> "Rules":
        d = self.to_dict()
        d.update(changes)
        return Rules.from_dict(d)
