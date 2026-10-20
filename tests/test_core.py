"""Core inflation by-product (D44): the aggregation reproduces Eurostat's core, and the output is coherent."""

import json

import numpy as np
import pandas as pd
import pytest

from hicp import forecast as fc
from hicp.clean import CleanData
from hicp.config import ROOT, load_settings
from hicp.core import CORE, ITEMS

OUT = ROOT / "outputs" / "core.json"
pytestmark = pytest.mark.skipif(not OUT.exists(), reason="run `python run.py` first")


@pytest.mark.skipif(not (ROOT / "data" / "clean" / "index.parquet").exists(), reason="needs the cleaned data: run `python run.py`")
def test_perfect_component_forecasts_reproduce_published_core():
    s = load_settings()
    d = CleanData.load(s)
    ix, w = d.index_wide(s.ea), d.weights_wide(s.ea)
    core = ix[CORE]
    cy = 100 * (core / core.shift(12) - 1)
    errs = []
    for o in pd.date_range("2011-01-01", "2026-06-01", freq="12MS"):
        tg = pd.date_range(o + pd.DateOffset(months=1), periods=3, freq="MS")
        mom = (100 * np.log(ix[ITEMS]).diff()).loc[tg]
        yy = fc.yoy_path(fc.headline_path(ix[ITEMS], mom, w.loc[o.year], core, o), core)
        errs += list((yy - cy.reindex(yy.index)).abs())
    assert max(errs) < 0.06


def test_output_is_coherent():
    k = json.loads(OUT.read_text())
    assert k["max_abs_gap_pp"] < 0.02
    assert [p["horizon"] for p in k["points"]] == [1, 2, 3]
    for p in k["points"]:
        q = p["quantiles"]
        assert q["q05"] <= q["q16"] <= q["q84"] <= q["q95"]
        assert abs(sum(p["contributions"].values()) - p["point"]) < 0.03
        assert p["base_effect_pp"] + p["momentum_pp"] == pytest.approx(p["point"] - k["last_actual"], abs=1e-6)
    full = {r["h"]: r for r in k["metrics"] if r["sample"] == "full"}
    assert set(full) == {1, 2, 3} and all(r["n"] >= 190 for r in full.values())
    assert k["history"][-1]["core_yoy"] == pytest.approx(k["last_actual"])
