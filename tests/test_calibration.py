"""Fan calibration machinery (D28) on synthetic errors with known properties."""

import numpy as np
import pandas as pd
import pytest

from hicp.calibration import QS, build, pinball


def test_pinball_is_zero_only_when_bands_collapse_on_the_outcome():
    assert pinball(1.0, 1.0, {q: 0.0 for q in QS}) == 0.0
    assert pinball(1.0, 0.0, {q: 0.0 for q in QS}) > 0


def synthetic(n=300, calm=0.2, crisis=1.0, crisis_from=200, seed=0):
    rng = np.random.default_rng(seed)
    origins = pd.date_range("2005-01-01", periods=n, freq="MS")
    rows = []
    for k, o in enumerate(origins):
        sd = crisis if crisis_from <= k < crisis_from + 40 else calm
        for h in (1, 2, 3):
            err = rng.normal(0, sd * np.sqrt(h))
            rows.append({"origin": o, "h": h, "target": o + pd.DateOffset(months=h), "fc": 2.0, "actual": 2.0 + err})
    return pd.DataFrame(rows)


def test_coverage_is_near_nominal_when_errors_are_stable():
    s = pd.DataFrame(build(synthetic(crisis=0.2))["summary"])
    row = s[(s.fan == "A") & (s.h == 1) & (s.period == "all scored")].iloc[0]
    assert row.in68 == pytest.approx(0.68, abs=0.08) and row.in90 == pytest.approx(0.90, abs=0.06)


def test_scaled_fan_adapts_to_a_volatility_burst():
    cal = build(synthetic(crisis=1.0))
    rows = cal["rows"]
    burst = rows[(rows.h == 1) & (rows.origin >= pd.Timestamp("2022-06-01")) & (rows.origin < pd.Timestamp("2024-01-01"))]
    assert burst.loss_B.mean() < burst.loss_A.mean()  # B widens, A does not
    width = lambda q: q[0.84] - q[0.16]  # noqa: E731
    assert burst.qb.map(width).mean() > burst.qa.map(width).mean()


def test_no_look_ahead_in_the_fans():
    df = synthetic()
    cal = build(df)
    t = cal["rows"].origin.max()
    df2 = df.copy()
    df2.loc[df2.target > t, "actual"] += 100  # outcomes after the origin cannot change the fan at t
    cal2 = build(df2)
    a = cal["rows"].set_index(["origin", "h"]).qa
    b = cal2["rows"].set_index(["origin", "h"]).qa
    assert all(a.loc[i] == b.loc[i] for i in a.index if i[0] == t)


def test_coverage_columns_are_numeric():
    rows = build(synthetic())["rows"]
    assert rows["in68_A"].dropna().isin([0.0, 1.0]).all() and rows["in68_A"].dtype == float
