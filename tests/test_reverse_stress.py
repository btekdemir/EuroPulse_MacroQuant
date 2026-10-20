"""Reverse stress test: solve for the shock that reaches a target, in Python and in the browser engine."""

import json
import shutil
import subprocess

import pytest

from hicp.config import ROOT
from hicp.outlook import prob_above
from hicp.schemas import Leg, Profile, Scenario, ShockBasis
from hicp.shocks import SIZE_HIGH, SIZE_LOW, brent_equivalent, required_point, simulate, solve_size

REF = json.loads((ROOT / "tests" / "data_single_leg_reference.json").read_text())
BASIS = ShockBasis.model_validate(REF["basis"])
DEC = "2026-12"


def sc(*legs):
    return Scenario(name="reverse test", legs=list(legs), rationale="x" * 40, sources=["t"])


def leg(comps, countries=(), size=10.0, profile=None, start="2026-10"):
    return Leg(components=list(comps), countries=list(countries), size_pct=size,
               profile=profile or Profile(kind="permanent"), start=start)


@pytest.mark.parametrize("comps,countries,target", [
    (["ELC_GAS"], ["DE", "IT"], 3.2), (["FUEL"], [], 4.5), (["SERV"], ["FR"], 3.9), (["IGD_NNRG", "FOOD_P"], ["ES"], 3.6)])
def test_solution_reproduces_the_target_through_the_forward_engine(comps, countries, target):
    s = sc(leg(comps, countries))
    r = solve_size(s, BASIS, 0, DEC, target)
    assert r["feasible"]
    back = simulate(sc(leg(comps, countries, r["size_pct"])), BASIS).shocked_yoy[BASIS.months.index(DEC)]
    assert back == pytest.approx(target, abs=1e-9)
    assert SIZE_LOW < r["size_pct"] < SIZE_HIGH


def test_direction_of_the_answer():
    base = BASIS.baseline_yoy[BASIS.months.index(DEC)]
    up = solve_size(sc(leg(["FUEL"])), BASIS, 0, DEC, base + 0.5)
    down = solve_size(sc(leg(["FUEL"])), BASIS, 0, DEC, base - 0.3)
    assert up["size_pct"] > 0 > down["size_pct"]
    assert solve_size(sc(leg(["FUEL"])), BASIS, 0, DEC, base)["size_pct"] == pytest.approx(0, abs=1e-6)


def test_other_legs_are_held_fixed():
    other = leg(["SERV"], ["DE"], 5.0)
    r = solve_size(sc(other, leg(["FUEL"], size=0.0)), BASIS, 1, DEC, 4.5)
    s2 = sc(other, leg(["FUEL"], size=r["size_pct"]))
    assert simulate(s2, BASIS).shocked_yoy[BASIS.months.index(DEC)] == pytest.approx(4.5, abs=1e-9)
    assert r["size_pct"] < solve_size(sc(leg(["FUEL"], size=0.0)), BASIS, 0, DEC, 4.5)["size_pct"]  # the SERV leg already helps


def test_unreachable_target_reports_the_reachable_range():
    r = solve_size(sc(leg(["FOOD_NP"], ["MT"])), BASIS, 0, DEC, 3.0)  # Malta food is far too small a lever
    assert r["feasible"] is False and r["reason"] == "out_of_range" and r["reach_low"] > 3.0  # even -49.9% stays above
    far = solve_size(sc(leg(["FOOD_NP"], ["MT"])), BASIS, 0, DEC, 9.0)
    assert far["feasible"] is False and far["reach_high"] < 9.0


def test_a_shock_that_starts_after_the_target_month_has_no_effect():
    r = solve_size(sc(leg(["FUEL"], start="2027-03")), BASIS, 0, DEC, 4.0)
    assert r["feasible"] is False and r["reason"] == "no_effect"


def test_required_point_inverts_the_probability():
    f = json.loads((ROOT / "outputs" / "forecast.json").read_text()) if (ROOT / "outputs" / "forecast.json").exists() else None
    if f is None:
        pytest.skip("run run.py first")
    errs = f["error_samples"]["3"]
    for thr, p in [(4.0, 0.5), (3.0, 0.9), (4.5, 0.2)]:
        pt = required_point(thr, errs, p)
        assert prob_above(pt, errs, thr) == pytest.approx(p, abs=1.5 / len(errs))


def test_brent_equivalent_is_the_inverse_of_the_elasticity_mapping():
    import math
    eps = BASIS.fuel_brent_elasticity["total"]
    fuel = 100 * math.expm1(eps * math.log1p(0.30))
    assert brent_equivalent(fuel, BASIS) == pytest.approx(30.0, abs=1e-9)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_solver_matches_python():
    cases = [(sc(leg(["ELC_GAS"], ["DE", "IT"])), 0, 3.2), (sc(leg(["SERV"], ["DE"], 5.0), leg(["FUEL"], size=0.0)), 1, 4.5),
             (sc(leg(["FOOD_NP"], ["MT"])), 0, 9.0), (sc(leg(["FUEL"], start="2027-03")), 0, 4.0)]
    payload = [{"scenario": s.model_dump(mode="json"), "leg": k, "target": t} for s, k, t in cases]
    script = f"""
      const E = require({json.dumps(str(ROOT / 'dashboard' / 'shock_engine.js'))});
      const basis = {json.dumps(REF['basis'])};
      const cs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify(cs.map(c => E.solveSize(c.scenario, basis, c.leg, {json.dumps(DEC)}, c.target))));
    """
    js = json.loads(subprocess.run(["node", "-e", script], input=json.dumps(payload), capture_output=True,
                                   text=True, check=True).stdout)
    for (s, k, t), r_js in zip(cases, js, strict=True):
        r_py = solve_size(s, BASIS, k, DEC, t)
        assert r_py["feasible"] == r_js["feasible"] and r_py["reason"] == r_js["reason"]
        if r_py["feasible"]:
            assert r_py["size_pct"] == pytest.approx(r_js["size_pct"], abs=1e-9)
        assert r_py["reach_high"] == pytest.approx(r_js["reach_high"], abs=1e-9)


@pytest.mark.skipif(shutil.which("node") is None or not (ROOT / "outputs" / "forecast.json").exists(), reason="needs node")
def test_js_required_point_matches_python():
    errs = json.loads((ROOT / "outputs" / "forecast.json").read_text())["error_samples"]["3"]
    cases = [(4.0, 0.5), (3.0, 0.9), (4.5, 0.2), (3.5, 0.05)]
    js = json.loads(subprocess.run(["node", "-e", f"""
        const E = require({json.dumps(str(ROOT / 'dashboard' / 'shock_engine.js'))});
        process.stdout.write(JSON.stringify({json.dumps(cases)}.map(c => E.requiredPoint(c[0], {json.dumps(errs)}, c[1]))));
    """], capture_output=True, text=True, check=True).stdout)
    for (thr, p), v in zip(cases, js, strict=True):
        assert required_point(thr, errs, p) == pytest.approx(v, abs=1e-12)
