"""Chain-linking maths on toy baskets with hand-computed answers."""

import numpy as np
import pandas as pd
import pytest

from hicp.chainlink import (base_momentum, chain_link, effective_weights, exact_contributions,
                            mom_shares, yoy)


def months(start: str, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="MS")


@pytest.fixture
def toy():
    """Two items, Dec 2019 .. Dec 2022 (37 months), weights change every year.

    A: +1% a month throughout. B: flat in 2020, +2% a month in 2021, flat in 2022.
    The aggregate is built here by hand-coding the Laspeyres chain, independently of chain_link.
    """
    idx = months("2019-12-01", 37)
    a = 100 * 1.01 ** np.arange(37)
    b_mom = np.r_[0.0, np.zeros(12), np.full(12, 0.02), np.zeros(12)]
    b = 100 * np.cumprod(1 + b_mom)
    items = pd.DataFrame({"A": a, "B": b}, index=idx)
    weights = pd.DataFrame({"A": [600.0, 500.0, 300.0], "B": [400.0, 500.0, 700.0]},
                           index=[2020, 2021, 2022])
    total = np.empty(37)
    total[0] = 100.0
    level = 100.0
    for k, t in enumerate(idx[1:], start=1):
        d = pd.Timestamp(year=t.year - 1, month=12, day=1)
        sa, sb = weights.loc[t.year, "A"] / 1000, weights.loc[t.year, "B"] / 1000
        total[k] = level * (sa * items.at[t, "A"] / items.at[d, "A"] + sb * items.at[t, "B"] / items.at[d, "B"])
        if t.month == 12:
            level = total[k]
    items["TOTAL"] = total
    return items, weights


def test_chain_link_hand_computed_point(toy):
    items, w = toy
    rebuilt = chain_link(items, w, ["A", "B"], "2020-01", items["TOTAL"])
    # Jan 2020 by hand: 100 * (0.6 * 1.01 + 0.4 * 1.0) = 100.6
    assert rebuilt[pd.Timestamp("2020-01-01")] == pytest.approx(100.6, abs=1e-12)
    # Dec 2020: 100 * (0.6 * 1.01**12 + 0.4)
    dec20 = 100 * (0.6 * 1.01 ** 12 + 0.4)
    assert rebuilt[pd.Timestamp("2020-12-01")] == pytest.approx(dec20, abs=1e-10)
    # Jan 2021 links on Dec 2020 with the new 50/50 weights: dec20 * (0.5*1.01 + 0.5*1.02)
    assert rebuilt[pd.Timestamp("2021-01-01")] == pytest.approx(dec20 * 1.015, abs=1e-10)
    np.testing.assert_allclose(rebuilt.to_numpy(), items["TOTAL"].iloc[1:].to_numpy(), rtol=1e-13)


def test_weights_need_not_sum_to_1000(toy):
    items, w = toy
    a = chain_link(items, w, ["A", "B"], "2020-01", items["TOTAL"])
    b = chain_link(items, w * 1.0003, ["A", "B"], "2020-01", items["TOTAL"])  # rounding-sized drift
    np.testing.assert_allclose(a, b, rtol=1e-14)


def test_yoy_from_levels():
    s = pd.Series(100 * 1.01 ** np.arange(25), index=months("2020-01-01", 25))
    y = yoy(s)
    assert y.iloc[:12].isna().all()
    assert y.iloc[12] == pytest.approx(100 * (1.01 ** 12 - 1))


def test_contributions_add_up_to_headline_yoy_exactly(toy):
    items, w = toy
    c = exact_contributions(items, w, ["A", "B"], "TOTAL")
    headline = yoy(items["TOTAL"]).loc[c.index]
    np.testing.assert_allclose(c.sum(axis=1), headline, atol=1e-10)
    assert len(c) == 24  # 2021 and 2022: needs Dec(y-2) as well


def test_december_contribution_is_single_link(toy):
    items, w = toy
    c = exact_contributions(items, w, ["A", "B"], "TOTAL")
    t = pd.Timestamp("2022-12-01")
    d = pd.Timestamp("2021-12-01")
    # Only the 2022 link: 100 * s_A,2022 * (A_t/A_Dec - 1) * I_Dec / I_{t-12}, with I_{t-12} = I_Dec
    expected_a = 100 * 0.3 * (items.at[t, "A"] / items.at[d, "A"] - 1)
    assert c.at[t, "A"] == pytest.approx(expected_a, abs=1e-12)


def test_naive_weight_times_rate_is_not_exact(toy):
    items, w = toy
    c = exact_contributions(items, w, ["A", "B"], "TOTAL")
    naive = (w.loc[c.index.year].set_axis(c.index) / 1000) * yoy(items[["A", "B"]]).loc[c.index]
    assert (c - naive).abs().to_numpy().max() > 0.1


def test_effective_weights_formula_and_sum(toy):
    items, w = toy
    weff = effective_weights(items, w, ["A", "B"])
    t, d = pd.Timestamp("2020-06-01"), pd.Timestamp("2019-12-01")
    # w_eff = s * (I_i,t / I_i,Dec) * (I_Dec / I_t)
    expected = 0.6 * (items.at[t, "A"] / items.at[d, "A"]) * (items.at[d, "TOTAL"] / items.at[t, "TOTAL"])
    assert weff.at[t, "A"] == pytest.approx(expected, rel=1e-12)
    assert expected > 0.6  # A outpaced the basket, so its effective share drifted up
    np.testing.assert_allclose(weff.dropna().sum(axis=1), 1.0, atol=1e-14)


def test_mom_shares_make_headline_mom_exact(toy):
    items, w = toy
    phi = mom_shares(items, w, ["A", "B"]).dropna()
    mom = items.pct_change().loc[phi.index]
    np.testing.assert_allclose((phi * mom[["A", "B"]]).sum(axis=1), mom["TOTAL"], atol=1e-14)
    # January uses the new year's official weights
    assert phi.at[pd.Timestamp("2021-01-01"), "A"] == pytest.approx(0.5)


def test_base_momentum_adds_up(toy):
    items, _ = toy
    out = base_momentum(items["TOTAL"], pd.Timestamp("2021-09-01"), 3)
    assert out["momentum_pp"] + out["base_effect_pp"] == pytest.approx(out["delta_pp"], abs=1e-10)
    # B was rising 2% a month in Oct-Dec 2020? No: flat in 2020, so the base is A only (positive m/m),
    # which pulls YoY down: base effect < 0.
    assert out["base_effect_pp"] < 0


def test_changing_composition_new_member_enters_in_january():
    """Country C has prices before it joins, but only enters with a weight from 2021."""
    idx = months("2019-12-01", 25)
    a = pd.Series(100 * 1.002 ** np.arange(25), index=idx)
    c = pd.Series(100 * 1.05 ** np.arange(25), index=idx)  # fast inflation, should not leak into 2020
    ix = pd.DataFrame({"A": a, "C": c, "EA": 100.0}, index=idx)
    w = pd.DataFrame({"A": [1000.0, 900.0], "C": [np.nan, 100.0]}, index=[2020, 2021])
    out = chain_link(ix, w, ["A", "C"], "2020-01", ix["EA"])
    np.testing.assert_allclose(out.loc["2020"], (100 * a / a.iloc[0]).loc["2020"], rtol=1e-13)
    jan21 = out.loc["2020-12-01"] * (0.9 * a["2021-01-01"] / a["2020-12-01"] + 0.1 * 1.05)
    assert out.loc["2021-01-01"] == pytest.approx(jan21, rel=1e-13)


def test_contributions_of_new_member_count_only_from_its_first_link():
    """A country with no weight last year contributes only through this year's link."""
    idx = months("2019-12-01", 37)
    a = pd.Series(100 * 1.002 ** np.arange(37), index=idx)
    c = pd.Series(100 * 1.01 ** np.arange(37), index=idx)
    w = pd.DataFrame({"A": [1000.0, 1000.0, 900.0], "C": [np.nan, np.nan, 100.0]}, index=[2020, 2021, 2022])
    ix = pd.DataFrame({"A": a, "C": c})
    ix["EA"] = pd.concat([pd.Series([100.0], index=idx[:1]), chain_link(ix, w, ["A", "C"], "2020-01", pd.Series(100.0, index=idx))])
    contrib = exact_contributions(ix, w, ["A", "C"], "EA")
    np.testing.assert_allclose(contrib.sum(axis=1), yoy(ix["EA"]).loc[contrib.index], atol=1e-10)
    assert (contrib.loc["2021", "C"] == 0).all() and (contrib.loc["2022", "C"] > 0).all()
