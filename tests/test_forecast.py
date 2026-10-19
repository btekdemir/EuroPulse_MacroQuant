"""Forecasting maths: model fitting, information set, DM test, bottom-up aggregation."""

import numpy as np
import pandas as pd
import pytest

from hicp import backtest as bt
from hicp import forecast as fc
from hicp.external import pump_monthly_known


def test_seasonal_mean_recovers_calendar_means():
    idx = pd.date_range("2001-01-01", periods=240, freq="MS")
    y = pd.Series(np.tile(np.arange(12, dtype=float), 20), index=idx)
    f = fc.fit(y, fc.ModelSpec("SM"))
    p = fc.predict(f, y, 3)
    assert list(p.round(10)) == [0.0, 1.0, 2.0]  # Jan, Feb, Mar of the next year


def test_ar1_recovers_coefficient():
    rng = np.random.default_rng(0)
    e = rng.normal(size=3000)
    y = np.zeros(3000)
    for t in range(1, 3000):
        y[t] = 0.6 * y[t - 1] + e[t]
    s = pd.Series(y, index=pd.date_range("1800-01-01", periods=3000, freq="MS"))
    f = fc.fit(s, fc.ModelSpec("AR1", ar=1))
    assert f.beta[12] == pytest.approx(0.6, abs=0.04)


def test_aic_picks_true_order():
    rng = np.random.default_rng(1)
    y = np.zeros(2000)
    for t in range(2, 2000):
        y[t] = 0.5 * y[t - 1] - 0.3 * y[t - 2] + rng.normal()
    s = pd.Series(y, index=pd.date_range("1850-01-01", periods=2000, freq="MS"))
    assert fc.fit(s, fc.ModelSpec("ARP", ar="aic")).p == 2


def test_easter_regressor():
    d = pd.DatetimeIndex(["2016-03-01", "2016-04-01", "2017-03-01", "2017-04-01"])  # Easter 27 Mar 2016, 16 Apr 2017
    assert list(fc.easter_regressor(d)) == [1.0, -1.0, 0.0, 0.0]


def test_pump_information_set_has_no_look_ahead():
    mondays = pd.date_range("2026-08-03", "2026-12-28", freq="W-MON")
    w = pd.Series(np.arange(len(mondays), dtype=float) + 100, index=mondays)
    known = pump_monthly_known(w, pd.Timestamp("2026-09-01"), 3, release_day=17, lag_days=3)
    # Cutoff 14 Oct: Mondays 5 and 12 Oct are known; 19 and 26 Oct are held at the 12 Oct price.
    p5, p12 = w["2026-10-05"], w["2026-10-12"]
    assert known["2026-10-01"] == pytest.approx((p5 + 3 * p12) / 4)
    assert known["2026-11-01"] == known["2026-12-01"] == p12
    assert known["2026-09-01"] == pytest.approx(w["2026-09"].mean())


def test_seasonal_rw_on_mom_is_identical_to_rw_on_yoy():
    """Why the seasonal random walk is not scored separately (backtest.seasonal_rw)."""
    rng = np.random.default_rng(2)
    idx = pd.date_range("2010-01-01", periods=60, freq="MS")
    head = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.15, 0.3, 60)) / 100), index=idx)
    t = idx[40]
    mom = 100 * np.log(head).diff()
    targets = [t + pd.DateOffset(months=h) for h in (1, 2, 3)]
    path = head[t] * np.exp(pd.Series([mom[d - pd.DateOffset(years=1)] for d in targets], index=targets).cumsum() / 100)
    srw = fc.yoy_path(path, head)
    assert np.allclose(srw, 100 * (head[t] / head[t - pd.DateOffset(years=1)] - 1))


def test_dm_test_detects_better_model_and_not_equal_ones():
    rng = np.random.default_rng(3)
    e_bench = rng.normal(size=300)
    _, p_better = bt.diebold_mariano(0.5 * e_bench + 0.1 * rng.normal(size=300), e_bench, 1)
    _, p_same = bt.diebold_mariano(rng.normal(size=300), rng.normal(size=300), 3)
    assert p_better < 0.001 and p_same > 0.05


def _toy_basket():
    idx = pd.date_range("2019-12-01", periods=25, freq="MS")
    rng = np.random.default_rng(4)
    comps = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.2, 0.5, (25, 2)), axis=0) / 100), index=idx, columns=["A", "B"])
    w = pd.DataFrame({"A": [700.0, 400.0], "B": [300.0, 600.0]}, index=[2020, 2021])
    head = [100.0]
    level = 100.0
    for t in idx[1:]:
        d = pd.Timestamp(year=t.year - 1, month=12, day=1)
        s = w.loc[t.year] / 1000
        head.append(level * float((s * comps.loc[t] / comps.loc[d]).sum()))
        if t.month == 12:
            level = head[-1]
    return comps, w, pd.Series(head, index=idx)


def test_headline_path_with_true_mom_reproduces_headline_within_year():
    comps, w, head = _toy_basket()
    origin = pd.Timestamp("2021-05-01")
    true_mom = (100 * np.log(comps).diff()).loc["2021-06-01":"2021-08-01"]
    path = fc.headline_path(comps, true_mom, w.loc[2021], head, origin)
    np.testing.assert_allclose(path, head.loc[path.index], rtol=1e-12)


def test_headline_path_across_january_uses_known_weights_only():
    comps, w, head = _toy_basket()
    origin = pd.Timestamp("2020-11-01")  # Jan 2021 weights are not yet known at this origin
    true_mom = (100 * np.log(comps).diff()).loc["2020-12-01":"2021-02-01"]
    path = fc.headline_path(comps, true_mom, w.loc[2020], head, origin)
    assert path["2020-12-01"] == pytest.approx(head["2020-12-01"], rel=1e-12)  # same year: exact
    s = w.loc[2020] / 1000  # Jan 2021 is linked on Dec 2020 with the old (known) weights
    d = pd.Timestamp("2020-12-01")
    expected = head[d] * float((s * comps.loc["2021-01-01"] / comps.loc[d]).sum())
    assert path["2021-01-01"] == pytest.approx(expected, rel=1e-12)
    assert path["2021-01-01"] != pytest.approx(head["2021-01-01"], rel=1e-9)  # new weights would differ
