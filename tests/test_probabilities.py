"""Probability statements from the empirical error sample, in Python and in the browser engine."""

import json
import shutil
import subprocess

import pytest

from hicp.config import ROOT
from hicp.outlook import prob_above

FORECAST = ROOT / "outputs" / "forecast.json"


def test_prob_above_counts_errors():
    errs = [-1.0, -0.5, 0.0, 0.5, 1.0]
    assert prob_above(3.0, errs, 2.9) == pytest.approx(0.6)  # outcomes 2.0, 2.5, 3.0, 3.5, 4.0: three above 2.9
    assert prob_above(3.0, errs, 4.5) == 0.0
    assert prob_above(3.0, errs, -10) == 1.0


def test_prob_above_strict_inequality():
    assert prob_above(3.0, [0.0], 3.0) == 0.0


@pytest.mark.skipif(not FORECAST.exists(), reason="run `python run.py` first")
def test_probabilities_are_consistent_with_the_fan():
    f = json.loads(FORECAST.read_text())
    dec = f["points"][-1]
    errs = f["error_samples"]["3"]
    # the 84th percentile of outcomes has ~16% of outcomes above it
    assert prob_above(dec["point"], errs, dec["quantiles"]["q84"]) == pytest.approx(0.16, abs=0.02)
    assert prob_above(dec["point"], errs, dec["quantiles"]["q05"]) == pytest.approx(0.95, abs=0.02)
    assert len(errs) >= 190


@pytest.mark.skipif(not FORECAST.exists(), reason="run `python run.py` first")
def test_fan_coverage_reported_by_period():
    cov = {(c["sample"], c["h"]): c for c in json.loads(FORECAST.read_text())["fan_coverage"]}
    assert cov[("full", 3)]["in68"] == pytest.approx(0.68, abs=0.02)  # in-sample by construction
    assert cov[("2020-2023", 3)]["in68"] < cov[("2010-2019", 3)]["in68"]  # the fixed fan is too narrow in the crisis


@pytest.mark.skipif(shutil.which("node") is None or not FORECAST.exists(), reason="needs node and outputs")
def test_js_prob_above_matches_python():
    f = json.loads(FORECAST.read_text())
    errs, point = f["error_samples"]["3"], f["points"][-1]["point"]
    thresholds = [2.0, 3.0, 3.5, 4.0, 4.5, 5.0]
    js = subprocess.run(["node", "-e", f"""
        const E = require({json.dumps(str(ROOT / 'dashboard' / 'shock_engine.js'))});
        const errs = {json.dumps(errs)};
        process.stdout.write(JSON.stringify({json.dumps(thresholds)}.map(t => E.probAbove({point}, errs, t))));
    """], capture_output=True, text=True, check=True)
    assert json.loads(js.stdout) == [prob_above(point, errs, t) for t in thresholds]
