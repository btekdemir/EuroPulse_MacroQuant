"""Estimated pass-through used by the shock engine: distributed-lag regressions with HAC errors.

1. Fuel elasticity to Brent (preset "oil supply shock"):
       fuel_t = Σ_m δ_m·month_m + Σ_{k=0..2} β_k · brent_eur_{t-k} + ε_t
   with 100·Δln of the HICP fuel index and of the monthly-average Brent price in EUR.
   ε = Σ β_k is the % change in fuel consumer prices per 1% Brent change after 2 months.
   It is far below 1 because excise duties are a fixed amount per litre and VAT/margins dilute it.

2. Second-round energy → core (optional in the simulator, off by default):
       core_t = Σ_m δ_m·month_m + Σ_{k=0..12} γ_k · energy_{t-k} + u_t
   estimated separately on 2001–2019 and 2020–latest (regime dependence). Σ_{k≤h} γ_k is the %
   change in the core price level h months after a 1% energy price-level shock.

Pure distributed lags (no lagged dependent variable), so OLS is consistent under exogenous energy,
and Newey-West (Bartlett, floor(4·(T/100)^(2/9)) lags) fixes the inference.
Caveat stated in the dashboard: energy is treated as exogenous; euro-wide demand shocks move both.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import statsmodels.api as sm

Z95 = 1.959964


def _design(y: pd.Series, x: pd.Series, lags: int) -> tuple[pd.Series, pd.DataFrame, list[str]]:
    names = [f"x_l{k}" for k in range(lags + 1)]
    X = pd.concat({n: x.shift(k) for k, n in enumerate(names)}, axis=1)
    months = pd.get_dummies(pd.Series(y.index.month, index=y.index), prefix="m", dtype=float)
    data = pd.concat([y.rename("y"), X, months], axis=1).dropna()
    return data["y"], data.drop(columns="y"), names


def distributed_lag(y: pd.Series, x: pd.Series, lags: int, start: str, end: str | None = None) -> dict:
    y, x = y.loc[start:end], x.loc[start:end] if end else x.loc[start:]
    yy, X, names = _design(y, x.reindex(y.index.union(x.index)), lags)
    nw = int(math.floor(4 * (len(yy) / 100) ** (2 / 9)))
    res = sm.OLS(yy, X).fit(cov_type="HAC", cov_kwds={"maxlags": nw, "kernel": "bartlett"})
    cov = res.cov_params().loc[names, names].to_numpy()
    b = res.params[names].to_numpy()
    cum, se = np.cumsum(b), []
    for h in range(lags + 1):
        a = np.r_[np.ones(h + 1), np.zeros(lags - h)]
        se.append(float(np.sqrt(a @ cov @ a)))
    se = np.array(se)
    return {"start": f"{yy.index.min():%Y-%m}", "end": f"{yy.index.max():%Y-%m}", "n": int(len(yy)),
            "nw_lags": nw, "beta": b.tolist(), "cumulative": cum.tolist(),
            "ci_low": (cum - Z95 * se).tolist(), "ci_high": (cum + Z95 * se).tolist(),
            "total": float(cum[-1]), "total_se": float(se[-1])}


# Andrews (1993) / Stock & Watson (Table 14.5) critical values for the QLR (sup-Wald) statistic,
# one restriction, 15% trimming: 10% / 5% / 1%.
QLR_CRIT_Q1 = {"10%": 7.12, "5%": 8.68, "1%": 12.16}


def _break_fit(y: pd.Series, x: pd.Series, lags: int, brk: pd.Timestamp, nw: int | None = None):
    """Full-sample distributed lag with a post-break intercept and post-break lag coefficients:
        y_t = Σ_m δ_m·month_m + θ·D_t + Σ_k β_k·x_{t-k} + Σ_k γ_k·D_t·x_{t-k} + u_t,  D_t = 1[t ≥ brk].
    Returns the HAC fit, the γ names, and the Newey-West lag used."""
    yy, X, names = _design(y, x, lags)
    d = (X.index >= brk).astype(float)
    inter = [f"post_{n}" for n in names]
    X = X.assign(post=d, **{p: X[n] * d for p, n in zip(inter, names)})
    nw = nw if nw is not None else int(math.floor(4 * (len(yy) / 100) ** (2 / 9)))
    res = sm.OLS(yy, X).fit(cov_type="HAC", cov_kwds={"maxlags": nw, "kernel": "bartlett"})
    return res, inter, names, nw


def _wald_sum(res, names: list[str]) -> tuple[float, float, float]:
    """Wald statistic for H0: Σ coefficients over ``names`` = 0. Returns (sum, se, W)."""
    cov = res.cov_params().loc[names, names].to_numpy()
    est = float(res.params[names].sum())
    se = float(np.sqrt(np.ones(len(names)) @ cov @ np.ones(len(names))))
    return est, se, (est / se) ** 2


def break_tests(index: pd.DataFrame, lags: int = 12, start: str = "2001-01", known: str = "2020-01",
                trim: float = 0.15, sensitivity: tuple[str, ...] = ("2019-01", "2020-01", "2021-01", "2022-01")) -> dict:
    """Is energy -> core pass-through different after a break? Three views:

    1. Chow-type test at a known date (2020-01): HAC Wald tests of (a) the cumulative 12-month
       pass-through difference Σγ_k = 0 (χ²(1)) and (b) all γ_k = 0 jointly (χ²(lags+1)).
    2. Unknown break date: sup-Wald / QLR (Andrews 1993) of Σγ_k = 0 over all candidate dates in the
       central (1 − 2·trim) of the sample. Critical values are Andrews' (not χ²), because the date
       is chosen by the data.
    3. Sensitivity of the post-break cumulative pass-through to the break year.
    """
    from scipy import stats

    lc = 100 * np.log(index[["TOT_X_NRG_FOOD", "NRG"]]).diff().loc[start:]
    y, x = lc["TOT_X_NRG_FOOD"], lc["NRG"]

    res, inter, names, nw = _break_fit(y, x, lags, pd.Timestamp(known))
    diff, diff_se, w1 = _wald_sum(res, inter)
    pre_sum, pre_se, _ = _wald_sum(res, names)
    post_sum = pre_sum + diff
    joint = res.wald_test(np.eye(len(res.params))[[list(res.params.index).index(n) for n in inter]],
                          scalar=True, use_f=False)
    chow = {"break": known, "n": int(res.nobs), "nw_lags": nw,
            "pre_cumulative": pre_sum, "pre_se": pre_se, "post_cumulative": post_sum,
            "diff_cumulative": diff, "diff_se": diff_se, "wald_cumulative": w1,
            "p_cumulative": float(stats.chi2.sf(w1, 1)),
            "wald_joint": float(joint.statistic), "df_joint": len(inter), "p_joint": float(joint.pvalue)}

    # sup-Wald over candidate dates (same NW lag throughout, so statistics are comparable)
    dates = res.model.data.row_labels
    lo, hi = int(len(dates) * trim), int(len(dates) * (1 - trim))
    path = []
    for brk in dates[lo:hi]:
        r, it, _, _ = _break_fit(y, x, lags, brk, nw)
        d, d_se, w = _wald_sum(r, it)
        path.append({"date": f"{brk:%Y-%m}", "wald": w, "diff_cumulative": d})
    best = max(path, key=lambda p: p["wald"])
    sup = {"stat": best["wald"], "argmax": best["date"], "diff_at_argmax": best["diff_cumulative"],
           "range": [path[0]["date"], path[-1]["date"]], "trim": trim, "critical_values": QLR_CRIT_Q1,
           "reject_5pct": best["wald"] > QLR_CRIT_Q1["5%"], "wald_at_known": w1, "path": path}

    sens = []
    for b in sensitivity:
        r, it, nm, _ = _break_fit(y, x, lags, pd.Timestamp(b), nw)
        d, d_se, w = _wald_sum(r, it)
        p_s, _, _ = _wald_sum(r, nm)
        sens.append({"break": b, "pre_cumulative": p_s, "post_cumulative": p_s + d, "diff": d, "diff_se": d_se,
                     "p_cumulative": float(stats.chi2.sf(w, 1)),
                     "n_post": int((r.model.data.row_labels >= pd.Timestamp(b)).sum())})
    # Sub-sample estimates: where is the higher pass-through? (the single-break sup-Wald cannot say)
    subs = []
    for label, a_, b_, mask in [("2001-2012", "2001-01", "2012-08", None), ("2012-2019", "2012-09", "2019-12", None),
                                ("2019-now", "2019-01", None, None),
                                ("2019-now excl. peak 2022-01..2023-06", "2019-01", None, ("2022-01", "2023-06"))]:
        yy = y.copy()
        if mask:
            yy.loc[mask[0]:mask[1]] = np.nan  # drops those target months; lags still use energy data
        o = distributed_lag(yy, x, lags, a_, b_)
        subs.append({"label": label, "start": o["start"], "end": o["end"], "n": o["n"],
                     "cumulative": o["total"], "se": o["total_se"]})
    return {"chow": chow, "sup_wald": sup, "sensitivity": sens, "subsamples": subs}


def estimate_all(index: pd.DataFrame, brent_eur: pd.Series) -> dict:
    """index: EA I25 wide with FUEL, NRG, TOT_X_NRG_FOOD."""
    lc = 100 * np.log(index).diff()
    brent = 100 * np.log(brent_eur.resample("MS").mean()).diff()
    last_full = index.index.max()
    fuel = distributed_lag(lc["FUEL"], brent.loc[:last_full], 2, "2005-01")
    pre = distributed_lag(lc["TOT_X_NRG_FOOD"], lc["NRG"], 12, "2001-01", "2019-12")
    post = distributed_lag(lc["TOT_X_NRG_FOOD"], lc["NRG"], 12, "2020-01")
    return {"fuel_brent": fuel, "second_round": {"pre2020": pre, "post2020": post},
            "break_test": break_tests(index)}
