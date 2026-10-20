"""Dashboard interactions: the browser maths equals Python (month explanation, October-print scenario)."""

import json
import shutil
import subprocess

import pandas as pd
import pytest

from hicp.chainlink import base_momentum
from hicp.config import ROOT

F = ROOT / "outputs" / "forecast.json"
pytestmark = [pytest.mark.skipif(shutil.which("node") is None, reason="node not installed"),
              pytest.mark.skipif(not F.exists(), reason="run `python run.py` first")]
ENGINE = json.dumps(str(ROOT / "dashboard" / "shock_engine.js"))


def node(expr: str, idx: dict):
    js = f"const E = require({ENGINE}); const idx = {json.dumps(idx)}; process.stdout.write(JSON.stringify({expr}));"
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)


@pytest.fixture(scope="module")
def idx():
    return json.loads(F.read_text())["headline_index"]


def test_headline_index_covers_history_and_forecast(idx):
    f = json.loads(F.read_text())
    assert all(p["date"] in idx for p in f["points"]) and len(idx) >= 12 * 8
    dec = f["points"][-1]
    assert 100 * (idx[dec["date"]] / idx["2025-12"] - 1) == pytest.approx(dec["point"], abs=1e-9)


@pytest.mark.parametrize("ym", ["2022-10", "2024-01", "2026-09", "2026-12"])
def test_explain_month_matches_python_base_momentum(idx, ym):
    s = pd.Series({pd.Timestamp(k + "-01"): v for k, v in idx.items()}).sort_index()
    t = pd.Timestamp(ym + "-01")
    py = base_momentum(s, t - pd.DateOffset(months=1), 1)
    js = node(f"E.explainMonth(idx, {json.dumps(ym)})", idx)
    assert js["momentum_pp"] == pytest.approx(py["momentum_pp"], abs=1e-9)
    assert js["base_effect_pp"] == pytest.approx(py["base_effect_pp"], abs=1e-9)
    assert js["momentum_pp"] + js["base_effect_pp"] == pytest.approx(js["delta_pp"], abs=1e-9)


def test_explain_month_needs_a_year_and_a_month_of_history(idx):
    first = min(idx)
    assert node(f"E.explainMonth(idx, {json.dumps(first)})", idx) is None


def test_october_print_scenario(idx):
    f = json.loads(F.read_text())
    oct_fc = f["points"][0]["point"]
    months = [p["date"] for p in f["points"]]
    same = node(f"E.conditionalPath(idx, '2026-10', {oct_fc}, {json.dumps(months)})", idx)
    assert [same[m] for m in months] == pytest.approx([p["point"] for p in f["points"]], abs=1e-9)  # no surprise: unchanged
    up = node(f"E.conditionalPath(idx, '2026-10', {oct_fc + 0.3}, {json.dumps(months)})", idx)
    assert up["2026-10"] == pytest.approx(oct_fc + 0.3, abs=1e-9)
    # a level surprise persists: Dec moves by about the same amount (scaled by relative base levels)
    k = idx["2025-10"] * (1 + (oct_fc + 0.3) / 100) / idx["2026-10"]
    assert up["2026-12"] == pytest.approx(100 * (idx["2026-12"] * k / idx["2025-12"] - 1), abs=1e-9)
    assert 0.25 < up["2026-12"] - f["points"][-1]["point"] < 0.35
