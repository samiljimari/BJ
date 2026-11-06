"""Bet / sit-out signal from the true count."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

# Project notes section 8 starting ramp: TC +1 -> 1u, +2 -> 2u, +3 -> 4u, +4 -> 6u, +5+ -> 8u.
DEFAULT_RAMP = [(1.0, 1.0), (2.0, 2.0), (3.0, 4.0), (4.0, 6.0), (5.0, 8.0)]


@dataclass
class BetRamp:
    # (minimum TC, units). Below the first threshold -> sit out (wong out).
    steps: list[tuple[float, float]] = field(default_factory=lambda: list(DEFAULT_RAMP))
    # Edge model used for display: edge(TC) ~= base_edge + edge_per_tc * TC.
    # Defaults are rules-of-thumb; replace with the simulator's fitted numbers.
    base_edge: float = -0.0053
    edge_per_tc: float = 0.005
    # Optional: TC is floored before lookup (common practice). False = use exact TC.
    floor_tc: bool = True
    # Money per betting unit (None = show units only) and currency symbol.
    unit: float | None = None
    currency: str = "\u20ac"

    def units(self, tc: float) -> float:
        t = math.floor(tc) if self.floor_tc else tc
        u = 0.0
        for thr, units in sorted(self.steps):
            if t >= thr:
                u = units
        return u

    def est_edge(self, tc: float) -> float:
        return self.base_edge + self.edge_per_tc * tc

    def signal(self, tc: float) -> dict:
        """Suggested bet for the NEXT round. Advice only - the player places it."""
        u = self.units(tc)
        amount = None if (self.unit is None or u <= 0) else round(u * self.unit, 2)
        return {
            "units": u,
            "sit_out": u <= 0,
            "label": "SIT OUT" if u <= 0 else f"BET {u:g}u",
            "amount": amount,
            "amount_label": None if amount is None else f"{self.currency}{amount:.2f}",
            "est_edge": round(self.est_edge(tc), 5),
        }

    @classmethod
    def load(cls, path: str | Path) -> "BetRamp":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        steps = [(float(s["tc"]), float(s["units"])) for s in d.get("steps", [])] or list(DEFAULT_RAMP)
        return cls(steps=steps,
                   base_edge=float(d.get("base_edge", -0.0053)),
                   edge_per_tc=float(d.get("edge_per_tc", 0.005)),
                   floor_tc=bool(d.get("floor_tc", True)),
                   unit=None if d.get("unit") is None else float(d["unit"]),
                   currency=str(d.get("currency", "\u20ac")))


def kelly_bet(bankroll: float, edge: float, variance: float = 1.33, fraction: float = 0.5) -> float:
    """Fractional-Kelly bet size for a single hand (blackjack variance ~1.3)."""
    if edge <= 0:
        return 0.0
    return bankroll * fraction * edge / variance


def risk_of_ruin(ev_per_round: float, sd_per_round: float, bankroll_units: float) -> float:
    """Classic diffusion approximation for a fixed betting unit and unlimited play."""
    if ev_per_round <= 0:
        return 1.0
    return math.exp(-2.0 * ev_per_round * bankroll_units / (sd_per_round ** 2))
