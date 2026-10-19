"""Multi-leg scenarios: regression to the single-shock engine, and the new algebra."""

import json
import math

import pytest

from hicp.config import ROOT
from hicp.schemas import Leg, Profile, Scenario, ShockBasis
from hicp.shocks import _first_round, simulate

REF = json.loads((ROOT / "tests" / "data_single_leg_reference.json").read_text())
BASIS = ShockBasis.model_validate(REF["basis"])


def sc(*legs, **kw):
    return Scenario(name="test scenario", legs=list(legs), rationale="x" * 40, sources=["t"], **kw)


def leg(components, countries=(), size=10.0, profile=None, start="2026-11"):
    return Leg(components=list(components), countries=list(countries), size_pct=size,
               profile=profile or Profile(kind="permanent"), start=start)


@pytest.mark.parametrize("case", REF["cases"], ids=lambda c: c["scenario"].get("name", "?")[:40])
def test_single_shock_results_unchanged_by_the_refactor(case):
    """Old one-shock JSON loads as a one-leg scenario and reproduces the frozen results exactly."""
    new = simulate(Scenario.model_validate(case["scenario"]), BASIS)
    old = case["result"]
    for key in ("delta_yoy_pp", "delta_first_round_pp", "delta_second_round_pp", "delta_total_low_pp", "delta_total_high_pp"):
        assert getattr(new, key) == pytest.approx(old[key], abs=1e-12), key
    assert new.peak_month == old["peak_month"]
    assert new.leg_first_round_pp[0] == pytest.approx(new.delta_first_round_pp, abs=1e-12)


def test_two_legs_on_disjoint_countries_equal_one_leg_on_the_union():
    two = simulate(sc(leg(["FUEL"], ["DE"]), leg(["FUEL"], ["IT"])), BASIS)
    one = simulate(sc(leg(["FUEL"], ["DE", "IT"])), BASIS)
    assert two.delta_yoy_pp == pytest.approx(one.delta_yoy_pp, abs=1e-12)


def test_legs_on_the_same_cell_compound_on_the_price_level():
    twice = simulate(sc(leg(["SERV"], ["FR"], 10), leg(["SERV"], ["FR"], 10)), BASIS)
    once = simulate(sc(leg(["SERV"], ["FR"], 100 * (1.1 ** 2 - 1))), BASIS)  # +21%
    assert twice.delta_yoy_pp == pytest.approx(once.delta_yoy_pp, abs=1e-12)
    # and +10% then -10% is not a wash: 1.1 * 0.9 = 0.99
    net = simulate(sc(leg(["SERV"], ["FR"], 10), leg(["SERV"], ["FR"], -10)), BASIS)
    assert net.peak_pp < 0 and net.peak_pp == pytest.approx(
        simulate(sc(leg(["SERV"], ["FR"], -1)), BASIS).peak_pp, abs=1e-9)


def test_leg_order_does_not_matter():
    a = leg(["ELC_GAS"], ["ES"], -15)
    b = leg(["FUEL"], ["DE"], 20, Profile(kind="decaying", half_life_months=3), "2026-10")
    c = leg(["FOOD_P"], ["MT"], 8, Profile(kind="temporary", months=4), "2027-01")
    assert simulate(sc(a, b, c), BASIS).delta_yoy_pp == pytest.approx(simulate(sc(c, a, b), BASIS).delta_yoy_pp, abs=1e-13)


def test_disjoint_legs_add_in_the_level_effect():
    legs = [leg(["ELC_GAS"], ["ES"], -15), leg(["FUEL"], ["DE"], 20), leg(["FOOD_P", "FOOD_NP"], ["MT"], 8)]
    total, _ = _first_round(legs, BASIS)
    parts = [_first_round([lg], BASIS)[0] for lg in legs]
    assert total == pytest.approx([sum(p[t] for p in parts) for t in range(len(total))], abs=1e-15)


def test_spain_down_germany_up_malta_up_matches_hand_calculation():
    """First month of the user's sentence, by hand: Σ W · (e^L − 1) for the three cells, times (1+pi)."""
    legs = [leg(["ELC_GAS"], ["ES"], -15, start="2026-10"), leg(["FUEL"], ["DE"], 20, start="2026-10"),
            leg(["FOOD_P", "FOOD_NP"], ["MT"], 8, start="2026-10")]
    r = simulate(sc(*legs), BASIS)
    W = BASIS.weight_matrix
    level = (W["ES"]["ELC_GAS"] * -0.15 + W["DE"]["FUEL"] * 0.20 + (W["MT"]["FOOD_P"] + W["MT"]["FOOD_NP"]) * 0.08)
    assert r.delta_yoy_pp[0] == pytest.approx(100 * BASIS.growth_factor[0] * level, rel=1e-12)
    assert r.delta_yoy_pp[0] > 0 and r.leg_first_round_pp[0][0] < 0  # Spain's leg pulls down, Germany's pushes up


def test_each_legs_own_start_month_is_respected():
    r = simulate(sc(leg(["FUEL"], ["DE"], 10, start="2026-10"), leg(["SERV"], ["FR"], 10, start="2027-03")), BASIS)
    assert r.leg_first_round_pp[1][BASIS.months.index("2027-02")] == 0
    assert r.leg_first_round_pp[1][BASIS.months.index("2027-03")] > 0
    assert r.leg_first_round_pp[0][0] > 0


def test_second_round_uses_the_combined_energy_deviation():
    legs = [leg(["ELC_GAS"], ["ES"], 30), leg(["FUEL"], ["DE"], 30)]
    both = simulate(sc(*legs, second_round=True), BASIS)
    parts = [simulate(sc(lg, second_round=True), BASIS).delta_second_round_pp for lg in legs]
    assert both.delta_second_round_pp == pytest.approx([a + b for a, b in zip(*parts)], rel=0.05, abs=1e-3)


def test_schema_limits():
    with pytest.raises(Exception):
        Scenario(name="no legs", legs=[], rationale="x" * 40, sources=["t"])
    with pytest.raises(Exception):
        sc(*[leg(["FUEL"]) for _ in range(9)])
    assert math.isclose(sum(BASIS.ea_effective_weights.values()), 1.0, abs_tol=1e-6)
