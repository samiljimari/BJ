"""Basic strategy generation (from the EV engine) and lookup with count deviations."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ..cards import full_composition, value_char
from ..rules import RULES_DIR, Rules
from .ev import EVCalc
from .fullshoe import DealRecord, enumerate_deals, hand_key, round_ev

UPS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 1)
UP_KEYS = tuple(value_char(u) for u in UPS)
GENERATED_DIR = RULES_DIR / "generated"
# Bump when engine changes alter results, so cached strategy files are rebuilt.
ENGINE_VERSION = 1
DEFAULT_DEVIATIONS = RULES_DIR / "deviations_i18.json"


def _code(evs: dict) -> str:
    """Chart code from averaged action EVs: H S D Ds Rh Rs."""
    best = max(evs, key=evs.get)
    hs = "H" if evs["hit"] >= evs["stand"] else "S"
    if best == "double":
        return "D" if hs == "H" else "Ds"
    if best == "surrender":
        return "R" + hs.lower()
    return hs


def build_tables(rules: Rules, deals: list[DealRecord] | None = None) -> dict:
    """Total-dependent basic strategy for the rule set (full-shoe composition).

    Two-card rows average each action's EV over all card combinations making that
    total (weighted by deal probability). Rows for 3/4/5-card hands only choose hit
    vs stand (they matter with Six Card Charlie).
    """
    deals = deals if deals is not None else enumerate_deals(rules)
    acc: dict = defaultdict(lambda: defaultdict(float))
    wsum: dict = defaultdict(float)
    pairs: dict = {}
    for d in deals:
        a = d.analysis
        if a.best in ("blackjack",):
            continue
        st, soft = hand_key(d.c1, d.c2)
        key = ("soft" if soft else "hard", st, d.up)
        for act, ev in a.ev.items():
            if act == "split":
                continue
            acc[key][act] += d.prob * ev
        wsum[key] += d.prob
        if d.c1 == d.c2 and "split" in a.ev:
            other = max(v for k, v in a.ev.items() if k != "split")
            pairs[(d.c1, d.up)] = "P" if a.ev["split"] > other else "-"

    tables: dict = {"hard": {}, "soft": {}, "pairs": {}, "multi": {}}
    for (kind, st, up), evs in acc.items():
        w = wsum[(kind, st, up)]
        avg = {k: v / w for k, v in evs.items()}
        tables[kind].setdefault(str(st), {})[value_char(up)] = _code(avg)
    for (v, up), code in pairs.items():
        tables["pairs"].setdefault(value_char(v), {})[value_char(up)] = code

    # Multi-card hit/stand tables (state based, composition = full shoe minus upcard).
    full = full_composition(rules.decks)
    for nc in (3, 4, 5):
        multi = {"hard": {}, "soft": {}}
        for up in UPS:
            comp = list(full)
            comp[up - 1] -= 1
            calc = EVCalc(comp, up, rules)
            for t in range(5, 21):
                s, h = calc.stand(t, False), calc.hit(t, False, nc)
                multi["hard"].setdefault(str(t), {})[value_char(up)] = "H" if h > s else "S"
            for st in range(13, 21):
                hard = st - 10
                s, h = calc.stand(hard, True), calc.hit(hard, True, nc)
                multi["soft"].setdefault(str(st), {})[value_char(up)] = "H" if h > s else "S"
        tables["multi"][str(nc)] = multi
    return tables


def build(rules: Rules) -> dict:
    deals = enumerate_deals(rules)
    return {
        "rules": rules.to_dict(),
        "fingerprint": rules.fingerprint(),
        "round_ev": round_ev(rules, deals=deals),
        "tables": build_tables(rules, deals),
    }


def load_or_build(rules: Rules, cache_dir: Path = GENERATED_DIR) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{rules.name}-{rules.fingerprint()}-v{ENGINE_VERSION}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = build(rules)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def format_chart(tables: dict) -> str:
    lines = []
    head = "      " + " ".join(f"{u:>3}" for u in UP_KEYS)
    for kind, label, keys in (
        ("hard", "Hard", [str(t) for t in range(5, 21)]),
        ("soft", "Soft", [str(t) for t in range(13, 21)]),
        ("pairs", "Pairs", ["A", "T", "9", "8", "7", "6", "5", "4", "3", "2"]),
    ):
        lines.append(f"{label}\n{head}")
        for k in keys:
            row = tables[kind].get(k)
            if not row:
                continue
            name = f"A,{int(k) - 11}" if kind == "soft" else (f"{k},{k}" if kind == "pairs" else k)
            lines.append(f"{name:>5} " + " ".join(f"{row.get(u, '?'):>3}" for u in UP_KEYS))
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------- lookup
def load_deviations(path: Path | str | None = DEFAULT_DEVIATIONS) -> list[dict]:
    if path is None:
        return []
    p = Path(path)
    if not p.exists():
        return []
    devs = json.loads(p.read_text(encoding="utf-8"))
    return [d for d in devs if not str(d.get("hand", "")).startswith("_")]


class Strategy:
    """Fast table lookup used by the simulator and as a cross-check in the overlay."""

    def __init__(self, tables: dict, deviations: list[dict] | None = None, charlie: bool = False):
        self.charlie = charlie
        # Pre-index tables: [kind][total][up] -> code
        self.hard = {int(t): {_up_val(u): c for u, c in row.items()} for t, row in tables["hard"].items()}
        self.soft = {int(t): {_up_val(u): c for u, c in row.items()} for t, row in tables["soft"].items()}
        self.pairs = {_up_val(v): {_up_val(u): c for u, c in row.items()} for v, row in tables["pairs"].items()}
        self.multi = {
            int(nc): {
                kind: {int(t): {_up_val(u): c for u, c in row.items()} for t, row in m[kind].items()}
                for kind in ("hard", "soft")
            }
            for nc, m in tables["multi"].items()
        }
        self.insurance_index: float | None = None
        self.devs: dict = defaultdict(list)
        for d in deviations or []:
            hand = d["hand"].strip().lower()
            up = _up_val(d["up"])
            if hand == "insurance":
                self.insurance_index = float(d["index"])
                continue
            kind, val = hand.split()
            v = _up_val(val) if kind == "pair" else int(val)
            self.devs[(kind, v, up)].append(
                (d["action"][0].upper(), float(d["index"]), d.get("when", ">=")))

    def take_insurance(self, tc: float | None) -> bool:
        return self.insurance_index is not None and tc is not None and tc >= self.insurance_index

    def basic(self, total: int, soft: bool, ncards: int, pair: int | None, up: int,
              can_double: bool, can_split: bool, can_surrender: bool) -> str:
        """Basic strategy action code: H S D P R."""
        if total >= 21:
            return "S"
        if pair is not None and can_split and self.pairs.get(pair, {}).get(up) == "P":
            return "P"
        if ncards <= 2:
            code = (self.soft if soft else self.hard).get(total, {}).get(up, "H" if total < 17 else "S")
        else:
            table = self.multi.get(min(ncards, 5), {}).get("soft" if soft else "hard", {})
            code = table.get(total, {}).get(up, "H" if total < 12 else "S")
        if code == "D":
            return "D" if can_double else "H"
        if code == "Ds":
            return "D" if can_double else "S"
        if code in ("Rh", "Rs"):
            return "R" if can_surrender else code[1].upper()
        return code

    def action(self, total: int, soft: bool, ncards: int, pair: int | None, up: int,
               can_double: bool, can_split: bool, can_surrender: bool,
               tc: float | None = None) -> str:
        if tc is not None and self.devs and not (self.charlie and ncards > 3):
            if pair is not None and can_split:
                for act, idx, when in self.devs.get(("pair", pair, up), ()):
                    if (tc >= idx) if when == ">=" else (tc < idx):
                        return act
            kind = "soft" if soft else "hard"
            for act, idx, when in self.devs.get((kind, total, up), ()):
                if (tc >= idx) if when == ">=" else (tc < idx):
                    if act == "D" and not can_double:
                        continue
                    return act
        return self.basic(total, soft, ncards, pair, up, can_double, can_split, can_surrender)


def _up_val(u) -> int:
    s = str(u).strip().upper()
    if s in ("A", "1", "11"):
        return 1
    if s in ("T", "10", "J", "Q", "K"):
        return 10
    return int(s)
