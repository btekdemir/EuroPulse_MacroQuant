"""Break tests on synthetic data with a known (or no) change in pass-through."""

import numpy as np
import pandas as pd
import pytest

from hicp.passthrough import QLR_CRIT_Q1, break_tests


def synthetic_index(break_date: str | None, before: float, after: float, n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Energy m/m is white noise (sd 2%); core m/m = pass-through × energy(lag 0) + noise (sd 0.1%)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2001-01-01", periods=n, freq="MS")
    e = rng.normal(0, 2.0, n)
    b = np.full(n, before)
    if break_date:
        b[idx >= pd.Timestamp(break_date)] = after
    core = b * e + rng.normal(0, 0.1, n)
    return pd.DataFrame({"NRG": 100 * np.exp(np.cumsum(e) / 100),
                         "TOT_X_NRG_FOOD": 100 * np.exp(np.cumsum(core) / 100)}, index=idx)


def test_detects_known_break_and_locates_it_roughly():
    """The test statistic sums 13 lag coefficients, so it needs a clear break to have power, and the
    sup-Wald date is only a rough location (within two years here, across seeds 0-3)."""
    for seed in range(4):
        ix = synthetic_index("2014-01", before=0.0, after=0.20, seed=seed)
        r = break_tests(ix, known="2014-01", sensitivity=("2014-01",))
        assert r["chow"]["p_cumulative"] < 0.001
        assert r["chow"]["diff_cumulative"] == pytest.approx(0.20, abs=0.06)
        assert r["sup_wald"]["reject_5pct"]
        found = pd.Timestamp(r["sup_wald"]["argmax"] + "-01")
        assert abs((found.year - 2014) * 12 + found.month - 1) <= 24


def test_no_false_alarm_without_break():
    ix = synthetic_index(None, before=0.03, after=0.03, seed=1)
    r = break_tests(ix, known="2014-01", sensitivity=("2014-01",))
    assert r["chow"]["p_cumulative"] > 0.05
    assert r["sup_wald"]["stat"] < QLR_CRIT_Q1["5%"]


def test_sup_wald_covers_trimmed_range_only():
    ix = synthetic_index(None, before=0.0, after=0.0, seed=2)
    path = break_tests(ix, sensitivity=())["sup_wald"]["path"]
    n = len(path) / 0.70  # 15% trimmed each side
    assert 0.6 < len(path) / n < 0.8 and path[0]["date"] > "2002-12"
