"""The dashboard's JS shock engine must give exactly what the Python engine gives."""

import json
import shutil
import subprocess

import pytest

from hicp.config import ROOT
from hicp.schemas import Leg, Profile, Scenario, ShockBasis
from hicp.shocks import profile_fraction, simulate

BASIS = ROOT / "outputs" / "shock_basis.json"
pytestmark = [pytest.mark.skipif(shutil.which("node") is None, reason="node not installed"),
              pytest.mark.skipif(not BASIS.exists(), reason="run `python run.py` first")]

EXTRA = [
    Scenario(name="decaying multi-country", components=["FUEL", "SERV"], countries=["DE", "IT", "BG"],
             size_pct=-12.5, profile=Profile(kind="decaying", half_life_months=4), start="2026-10",
             second_round=True, rationale="x" * 40, sources=["test"]),
    Scenario(name="temporary food", components=["FOOD_P", "FOOD_NP"], size_pct=5,
             profile=Profile(kind="temporary", months=3), start="2027-03", rationale="x" * 40, sources=["test"]),
    Scenario(name="ramp energy pre2020", components=["ELC_GAS", "FUEL"], size_pct=40,
             profile=Profile(kind="ramp", months=4), start="2026-11", second_round=True,
             second_round_regime="pre2020", rationale="x" * 40, sources=["test"]),
]


MULTI = [
    Scenario(name="three legs different countries", rationale="x" * 40, sources=["test"], second_round=True, legs=[
        Leg(components=["ELC_GAS"], countries=["ES"], size_pct=-15, profile=Profile(kind="permanent"), start="2026-11"),
        Leg(components=["FUEL"], countries=["DE"], size_pct=20, profile=Profile(kind="decaying", half_life_months=3), start="2026-10"),
        Leg(components=["FOOD_P", "FOOD_NP"], countries=["MT"], size_pct=8, profile=Profile(kind="temporary", months=4), start="2027-01")]),
    Scenario(name="overlapping legs same cell", rationale="x" * 40, sources=["test"], legs=[
        Leg(components=["SERV", "FUEL"], countries=["FR", "DE"], size_pct=10, profile=Profile(kind="permanent"), start="2026-10"),
        Leg(components=["FUEL"], countries=["DE"], size_pct=10, profile=Profile(kind="ramp", months=5), start="2026-12"),
        Leg(components=["IGD_NNRG"], size_pct=-3, profile=Profile(kind="permanent"), start="2027-02")]),
]


def test_js_engine_matches_python():
    basis = ShockBasis.model_validate_json(BASIS.read_text())
    scenarios = MULTI + list(basis.presets) + [p.model_copy(update={"second_round": True}) for p in basis.presets] + EXTRA
    script = f"""
      const E = require({json.dumps(str(ROOT / 'dashboard' / 'shock_engine.js'))});
      const basis = JSON.parse(require('fs').readFileSync({json.dumps(str(BASIS))}, 'utf8'));
      const scs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify(scs.map(s => E.simulate(s, basis))));
    """
    out = subprocess.run(["node", "-e", script], input=json.dumps([s.model_dump(mode="json") for s in scenarios]),
                         capture_output=True, text=True, check=True)
    js = json.loads(out.stdout)
    for sc, r_js in zip(scenarios, js, strict=True):
        r_py = simulate(sc, basis)
        for key in ("delta_yoy_pp", "delta_first_round_pp", "delta_second_round_pp", "delta_total_low_pp",
                    "delta_total_high_pp"):
            assert getattr(r_py, key) == pytest.approx(r_js[key], abs=1e-12), (sc.name, key)
        assert r_py.peak_month == r_js["peak_month"]
        for ly, lj in zip(r_py.leg_first_round_pp, r_js["leg_first_round_pp"], strict=True):
            assert ly == pytest.approx(lj, abs=1e-12), (sc.name, "leg")


def test_profiles():
    assert profile_fraction(Profile(kind="permanent"), 30) == 1
    assert profile_fraction(Profile(kind="decaying", half_life_months=3), 3) == pytest.approx(0.5)
    assert [profile_fraction(Profile(kind="temporary", months=2), m) for m in range(3)] == [1, 1, 0]
    assert [profile_fraction(Profile(kind="ramp", months=4), m) for m in range(5)] == [0.25, 0.5, 0.75, 1, 1]
    assert profile_fraction(Profile(kind="custom", fractions=[0.5, 0.9, 1.0]), 7) == 1.0
    assert profile_fraction(Profile(kind="permanent"), -1) == 0


def test_permanent_shock_drops_out_after_12_months():
    basis = ShockBasis.model_validate_json(BASIS.read_text())
    sc = Scenario(name="perm", components=["SERV"], size_pct=1, profile=Profile(kind="permanent"),
                  start=basis.months[0], rationale="x" * 40, sources=["t"])
    r = simulate(sc, basis)
    assert all(v > 0 for v in r.delta_yoy_pp[:12]) and abs(r.delta_yoy_pp[12]) < 1e-12
    # first-order size: 1% x services effective weight x (1 + baseline YoY)
    assert r.delta_yoy_pp[0] == pytest.approx(basis.ea_effective_weights["SERV"] * basis.growth_factor[0], rel=1e-3)
