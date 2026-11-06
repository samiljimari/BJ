import math

from server.betting import BetRamp, risk_of_ruin
from server.rules import Rules
from server.sim.simulate import simulate


def test_ramp():
    r = BetRamp()
    assert r.units(0.9) == 0 and r.signal(0.5)["sit_out"]
    assert r.units(1.0) == 1 and r.units(2.7) == 2 and r.units(3.2) == 4 and r.units(9) == 8


def test_ror_monotonic():
    assert risk_of_ruin(0.05, 3.5, 400) < risk_of_ruin(0.05, 3.5, 200) < 1


def test_simulator_runs_and_is_deterministic():
    rules = Rules.load("infinite_blackjack")
    a = simulate(rules, 3000, workers=1, seed=5)
    b = simulate(rules, 3000, workers=1, seed=5)
    assert a.rounds == 3000 and a.flat_sum == b.flat_sum
    assert -0.2 < a.flat_sum / a.rounds < 0.2
    assert math.isfinite(a.net)
