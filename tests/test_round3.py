"""Round 3 (D56): no look-ahead in the direct models' features, the naive identity, and the decision rule."""

import json

import numpy as np
import pandas as pd
import pytest

from hicp.config import ROOT
from hicp.round3 import FAMILY, base_effect, design, seasonal_naive

OUT = ROOT / "outputs" / "round3.json"


def synthetic_index(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2000-01-01", periods=n, freq="MS")
    cols = ["TOTAL", "A", "B"]
    return pd.DataFrame({c: 100 * np.exp(np.cumsum(rng.normal(0.002, 0.003, n))) for c in cols}, index=idx)


def test_features_at_t_do_not_use_the_future():
    ix = synthetic_index()
    t = ix.index[200]
    for h in (1, 2, 3):
        X1, _ = design(ix, ["A", "B"], "TOTAL", h)
        future = ix.copy()
        future.loc[future.index > t] *= 1.5          # change everything after the origin
        X2, _ = design(future, ["A", "B"], "TOTAL", h)
        pd.testing.assert_series_equal(X1.loc[t], X2.loc[t])


def test_base_effect_is_last_years_drop_outs():
    ix = synthetic_index()["TOTAL"]
    t = ix.index[100]
    lm = 100 * np.log(ix).diff()
    expected = sum(lm[t + pd.DateOffset(months=k) - pd.DateOffset(years=1)] for k in (1, 2, 3))
    assert base_effect(ix, 3)[t] == pytest.approx(expected)


def test_seasonal_naive_is_the_random_walk():
    ix = synthetic_index()["TOTAL"]
    origins = list(ix.index[30:60])
    sn = seasonal_naive(ix, origins)
    yy = 100 * (ix / ix.shift(12) - 1)
    assert np.allclose(sn.fc.to_numpy(), yy.reindex(sn.origin).to_numpy(), atol=1e-10)


@pytest.mark.skipif(not OUT.exists(), reason="run `python run.py` first")
def test_report_follows_the_pre_registered_rule():
    r = json.loads(OUT.read_text())
    assert [d["name"] for d in r["holm"]] and {d["name"] for d in r["holm"]} == set(FAMILY)
    ps = sorted(d["p"] for d in r["holm"])
    assert [d["threshold"] for d in r["holm"]] == pytest.approx([0.05 / (4 - i) for i in range(4)])
    assert [d["p"] for d in r["holm"]] == pytest.approx(ps)
    full3 = {m["model"]: m for m in r["metrics"] if m["h"] == 3 and m["sample"] == "full"}
    passing = [d["name"] for d in r["holm"] if d["rejected"] and full3[d["name"]]["rmse_ratio_vs_rw"] < 1]
    assert r["candidate"] == (min(passing, key=lambda k: full3[k]["rmse"]) if passing else None)
    assert r["naive_equals_rw_max_gap"] < 1e-9
    assert set(r["latest"]) == set(FAMILY) and all(len(v) == 3 for v in r["latest"].values())
