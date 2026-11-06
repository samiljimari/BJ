"""Estimate Hi-Lo indices for a rule set and compare with the reference table.

    python tools/gen_indices.py                        # rules/infinite_blackjack.json
    python tools/gen_indices.py --decks-remaining 3 --write

--write saves rules/generated/<rules>.indices.json (same format as
rules/deviations_i18.json, so it can be passed to the server with --deviations).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.engine.indices import generate  # noqa: E402
from server.engine.strategy import GENERATED_DIR, load_deviations  # noqa: E402
from server.rules import Rules  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", default="infinite_blackjack")
    ap.add_argument("--reference", default=str(Path(__file__).resolve().parent.parent / "rules" / "deviations_i18.json"))
    ap.add_argument("--decks-remaining", type=float, default=4.0)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    rules = Rules.load(a.rules)
    rows = generate(rules, load_deviations(a.reference), a.decks_remaining)
    print(f"{rules.name}: estimated at {a.decks_remaining:g} decks remaining\n")
    print(f"{'hand':10s} {'up':>2s}  {'action':9s} {'reference':>10s} {'engine':>8s}")
    out = []
    for r in rows:
        idx = r["index"]
        shown = "never" if idx is None or (isinstance(idx, float) and math.isinf(idx)) else f"{r['when']}{idx:+.1f}"
        print(f"{r['hand']:10s} {r['up']:>2s}  {r['action']:9s} {r['reference_when'] + format(r['reference_index'], '+d'):>10s} {shown:>8s}")
        if idx is not None and not math.isinf(idx):
            rounded = math.ceil(idx) if r["when"] == ">=" else math.floor(idx)
            out.append({"hand": r["hand"], "up": r["up"], "action": r["action"], "index": rounded, "when": r["when"],
                        "estimate": idx})
    if a.write:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        p = GENERATED_DIR / f"{rules.name}.indices.json"
        p.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"\nwrote {p}")


if __name__ == "__main__":
    main()
