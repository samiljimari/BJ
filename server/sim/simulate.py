"""Shoe simulator: edge by true count, bet-ramp results, SD, N0, risk of ruin.

    python -m server.sim.simulate --rounds 2000000 --workers 4
    python -m server.sim.simulate --rules infinite_blackjack --penetration 0.5
"""

from __future__ import annotations

import argparse
import math
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from ..betting import BetRamp, risk_of_ruin
from ..engine.strategy import Strategy, load_deviations, load_or_build
from ..rules import Rules
from .game import SimShoe, play_round

TC_MIN, TC_MAX = -6, 10


@dataclass
class Stats:
    rounds: int = 0
    flat_sum: float = 0.0
    flat_sq: float = 0.0
    played: int = 0
    wagered: float = 0.0
    net: float = 0.0
    net_sq: float = 0.0
    shoes: int = 0
    buckets: dict = field(default_factory=dict)  # tc -> [n, sum, sumsq]

    def merge(self, o: "Stats") -> None:
        for k in ("rounds", "flat_sum", "flat_sq", "played", "wagered", "net", "net_sq", "shoes"):
            setattr(self, k, getattr(self, k) + getattr(o, k))
        for tc, (n, s, q) in o.buckets.items():
            b = self.buckets.setdefault(tc, [0, 0.0, 0.0])
            b[0] += n; b[1] += s; b[2] += q


def run_chunk(args) -> Stats:
    rules_d, tables, devs, ramp_steps, rounds, seed, use_devs = args
    R = Rules.from_dict(rules_d)
    S = Strategy(tables, devs, charlie=R.six_card_charlie)
    ramp = BetRamp(steps=ramp_steps)
    rng = random.Random(seed)
    sh = SimShoe(R, rng)
    st = Stats(shoes=1)
    buckets = st.buckets
    for _ in range(rounds):
        if sh.needs_shuffle():
            sh.shuffle()
            st.shoes += 1
        tc = sh.tc()
        units = ramp.units(tc)
        res = play_round(sh, R, S, use_devs)
        st.rounds += 1
        st.flat_sum += res
        st.flat_sq += res * res
        b = int(math.floor(tc))
        b = TC_MIN if b < TC_MIN else (TC_MAX if b > TC_MAX else b)
        bk = buckets.get(b)
        if bk is None:
            bk = buckets[b] = [0, 0.0, 0.0]
        bk[0] += 1; bk[1] += res; bk[2] += res * res
        if units > 0:
            st.played += 1
            st.wagered += units
            w = units * res
            st.net += w
            st.net_sq += w * w
    return st


def simulate(rules: Rules, rounds: int, workers: int = 1, seed: int = 1,
             ramp: BetRamp | None = None, use_devs: bool = True, deviations=None) -> Stats:
    data = load_or_build(rules)
    devs = load_deviations() if deviations is None else deviations
    ramp = ramp or BetRamp()
    workers = max(1, workers)
    per = rounds // workers
    jobs = [(rules.to_dict(), data["tables"], devs, ramp.steps, per, seed * 1000 + i, use_devs)
            for i in range(workers)]
    total = Stats()
    if workers == 1:
        total.merge(run_chunk(jobs[0]))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for st in ex.map(run_chunk, jobs):
                total.merge(st)
    return total


def report(st: Stats, bankroll_units: float, rounds_per_hour: float) -> str:
    out = []
    n = st.rounds
    mean = st.flat_sum / n
    var = st.flat_sq / n - mean * mean
    out.append(f"Rounds observed: {n:,}   shoes: {st.shoes:,}   rounds/shoe: {n / max(st.shoes, 1):.1f}")
    out.append(f"Flat 1-unit every round: edge {100 * mean:+.3f}% +/- {100 * math.sqrt(var / n):.3f}% (1 SE),"
               f"  SD/round {math.sqrt(var):.3f}")
    out.append("")
    out.append("  TC   freq%    edge%     +/-SE%")
    xs, ys, ws = [], [], []
    for tc in sorted(st.buckets):
        bn, bs, bq = st.buckets[tc]
        if bn < 100:
            continue
        m = bs / bn
        v = bq / bn - m * m
        se = math.sqrt(v / bn)
        label = f"<={tc}" if tc == TC_MIN else (f">={tc}" if tc == TC_MAX else f"{tc:+d}")
        out.append(f"{label:>5} {100 * bn / n:6.2f} {100 * m:+8.3f} {100 * se:9.3f}")
        if -2 <= tc <= 6:
            xs.append(tc + 0.5); ys.append(m); ws.append(1 / max(se * se, 1e-12))
    if len(xs) >= 3:
        sw = sum(ws)
        mx = sum(w * x for w, x in zip(ws, xs)) / sw
        my = sum(w * y for w, y in zip(ws, ys)) / sw
        sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
        sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
        slope = sxy / sxx
        out.append(f"\nFitted edge(TC) ~= {100 * (my - slope * mx):+.3f}% + {100 * slope:.3f}% x TC"
                   f"   (use as base_edge / edge_per_tc in the bet ramp)")
    out.append("")
    if st.played:
        ev_obs = st.net / n                       # per observed round (incl. sitting out)
        ev_play = st.net / st.played
        var_play = st.net_sq / st.played - ev_play ** 2
        sd_play = math.sqrt(var_play)
        out.append(f"Bet ramp (wonging): played {100 * st.played / n:.1f}% of rounds, avg bet "
                   f"{st.wagered / st.played:.2f}u")
        out.append(f"  edge on money wagered: {100 * st.net / st.wagered:+.3f}%")
        out.append(f"  EV per played round {ev_play:+.4f}u, SD per played round {sd_play:.3f}u")
        out.append(f"  EV per 100 observed rounds {100 * ev_obs:+.3f}u   per hour ({rounds_per_hour:g} rounds/h)"
                   f" {ev_obs * rounds_per_hour:+.3f}u")
        if ev_play > 0:
            n0 = (sd_play / ev_play) ** 2
            out.append(f"  N0 = {n0:,.0f} played rounds (~{n0 * n / st.played / rounds_per_hour:,.0f} hours"
                       f" at {rounds_per_hour:g} rounds/h observed)")
            ror = risk_of_ruin(ev_play, sd_play, bankroll_units)
            out.append(f"  Risk of ruin with {bankroll_units:g}u bankroll: {100 * ror:.2f}%")
        else:
            out.append("  Negative expectation with this ramp/penetration - no N0 / RoR.")
    return "\n".join(out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", default="infinite_blackjack")
    ap.add_argument("--rounds", type=int, default=500_000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--penetration", type=float, help="override rules penetration (0..1)")
    ap.add_argument("--no-deviations", action="store_true", help="basic strategy only")
    ap.add_argument("--ramp", help="JSON bet ramp file (see rules/bet_ramp.json)")
    ap.add_argument("--bankroll", type=float, default=400, help="bankroll in units for risk of ruin")
    ap.add_argument("--rounds-per-hour", type=float, default=60)
    a = ap.parse_args(argv)

    rules = Rules.load(a.rules)
    if a.penetration:
        rules = rules.replace(penetration=a.penetration)
    ramp = BetRamp.load(a.ramp) if a.ramp else BetRamp()
    t = time.perf_counter()
    st = simulate(rules, a.rounds, a.workers, a.seed, ramp, use_devs=not a.no_deviations)
    dt = time.perf_counter() - t
    print(f"Rules: {rules.name}  penetration {rules.penetration:.0%}  deviations "
          f"{'off' if a.no_deviations else 'on'}  ({dt:.1f}s, {st.rounds / dt:,.0f} rounds/s)\n")
    print(report(st, a.bankroll, a.rounds_per_hour))


if __name__ == "__main__":
    main()
