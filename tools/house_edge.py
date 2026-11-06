"""House edge of a rule set + which unknown rules are consistent with the published RTP.

    python tools/house_edge.py                       # infinite_blackjack.json
    python tools/house_edge.py --rules standard_8d_s17_das
    python tools/house_edge.py --explore             # try combinations of the unverified rules
    python tools/house_edge.py --chart               # also print the basic strategy chart

Uses the composition-dependent EV engine on a full shoe (no count, no insurance).
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.engine.fullshoe import round_ev  # noqa: E402
from server.engine.strategy import build, format_chart  # noqa: E402
from server.rules import Rules  # noqa: E402

PUBLISHED_EDGE = 0.0053  # Infinite Blackjack RTP 99.47%


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", default="infinite_blackjack")
    ap.add_argument("--explore", action="store_true")
    ap.add_argument("--chart", action="store_true")
    ap.add_argument("--target", type=float, default=PUBLISHED_EDGE, help="published house edge (fraction)")
    a = ap.parse_args()
    rules = Rules.load(a.rules)

    if a.chart:
        data = build(rules)
        print(f"{rules.name}: house edge {-100 * data['round_ev']:.3f}%\n")
        print(format_chart(data["tables"]))
    else:
        print(f"{rules.name}: house edge {-100 * round_ev(rules):.3f}%")

    if a.explore:
        grid = {
            "dealer_peek": [True, "ace", False],
            "no_peek_lose_all": [False, True],
            "double_after_split": [True, False],
            "double_on": ["any_two", "9-11"],
            "six_card_charlie": [True],
            "dealer_hits_soft_17": [False],
        }
        rows = []
        for combo in itertools.product(*grid.values()):
            ch = dict(zip(grid, combo))
            if ch["dealer_peek"] is True and ch["no_peek_lose_all"]:
                continue  # irrelevant combination
            r = rules.replace(**ch)
            rows.append((-round_ev(r), ch))
        rows.sort(key=lambda x: abs(x[0] - a.target))
        print(f"\nRule combinations closest to the published edge {100 * a.target:.2f}%:")
        print("   edge   peek          lose-all-vs-BJ  DAS    double_on")
        for edge, ch in rows:
            print(f" {100 * edge:6.3f}%  {str(ch['dealer_peek']):12s}  {str(ch['no_peek_lose_all']):14s}  "
                  f"{str(ch['double_after_split']):5s}  {ch['double_on']}")
        print("\nOnly a hint: several combinations can give similar edges. The in-game Help panel decides.")


if __name__ == "__main__":
    main()
