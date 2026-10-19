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


def estimate_all(index: pd.DataFrame, brent_eur: pd.Series) -> dict:
    """index: EA I25 wide with FUEL, NRG, TOT_X_NRG_FOOD."""
    lc = 100 * np.log(index).diff()
    brent = 100 * np.log(brent_eur.resample("MS").mean()).diff()
    last_full = index.index.max()
    fuel = distributed_lag(lc["FUEL"], brent.loc[:last_full], 2, "2005-01")
    pre = distributed_lag(lc["TOT_X_NRG_FOOD"], lc["NRG"], 12, "2001-01", "2019-12")
    post = distributed_lag(lc["TOT_X_NRG_FOOD"], lc["NRG"], 12, "2020-01")
    return {"fuel_brent": fuel, "second_round": {"pre2020": pre, "post2020": post}}
