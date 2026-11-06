"""Write demo-protocol frame fixtures (for parser tests and trying out tools/recon.py).

    python tools/make_demo_fixture.py --shoes 5 --out fixtures/demo/demo_shoes.jsonl
    python tools/make_demo_fixture.py --reshuffle-every-round --out fixtures/demo/demo_csm.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.demo import round_messages  # noqa: E402
from server.engine.strategy import Strategy, load_or_build  # noqa: E402
from server.rules import Rules  # noqa: E402
from server.sim.game import SimShoe  # noqa: E402


def make(rules: Rules, shoes: int, seed: int, reshuffle_every_round: bool, rounds: int) -> list[dict]:
    rng = random.Random(seed)
    strat = Strategy(load_or_build(rules)["tables"], None, charlie=rules.six_card_charlie)
    sh = SimShoe(rules, rng)
    frames, ts, n_round, shoes_done = [], 1_700_000_000_000, 0, 0

    def emit(msg):
        nonlocal ts
        ts += 700
        frames.append({"kind": "frame", "dir": "in", "socket": 1, "url": "ws://localhost:8766/ws",
                       "binary": False, "data": json.dumps(msg), "ts": ts})

    if reshuffle_every_round:
        emit({"msg": "shuffle"})  # one "shoe" event, then every round from a fresh shuffle
        while n_round < rounds:
            sh.shuffle()
            n_round += 1
            for msg, _ in round_messages(sh, rules, strat, rng, n_round):
                emit(msg)
        return frames
    while shoes_done < shoes:
        sh.shuffle()
        emit({"msg": "shuffle"})
        while not sh.needs_shuffle():
            n_round += 1
            for msg, _ in round_messages(sh, rules, strat, rng, n_round):
                emit(msg)
        shoes_done += 1
    emit({"msg": "shuffle"})
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", default="infinite_blackjack")
    ap.add_argument("--shoes", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--reshuffle-every-round", action="store_true",
                    help="simulate a game that reshuffles before every round (counting useless)")
    ap.add_argument("--rounds", type=int, default=300, help="rounds for --reshuffle-every-round")
    ap.add_argument("--out", default="fixtures/demo/demo_shoes.jsonl")
    a = ap.parse_args()
    frames = make(Rules.load(a.rules), a.shoes, a.seed, a.reshuffle_every_round, a.rounds)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(f) + "\n" for f in frames), encoding="utf-8")
    print(f"wrote {len(frames)} frames to {out}")


if __name__ == "__main__":
    main()
