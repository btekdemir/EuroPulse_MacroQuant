"""Component models for monthly HICP log changes, and the bottom-up aggregation to headline.

Target variable per component: y_t = 100 · Δln I_t (≈ % m/m), not seasonally adjusted.
Every model is OLS with 12 calendar-month dummies (no constant), plus optionally:

* AR(p) lags of y, p fixed or chosen by AIC over 0..3 on a common sample;
* an Easter regressor (services: package holidays and accommodation move with Easter);
* the contemporaneous change in the Weekly Oil Bulletin pump-price index (fuels).

Forecasts are iterated: h = 2 uses the h = 1 forecast as its lag. The pump regressor uses the
bulletins known at the origin, with unknown weeks held flat (``external.pump_monthly_known``).

Bottom-up: component levels I_i,t+h = I_i,t · exp(Σ y/100) are chain-linked with the weights
known at the origin (``headline_path``), then YoY is taken against the published headline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from dateutil.easter import easter

from hicp.chainlink import dec

MAX_AR = 3


@dataclass(frozen=True)
class ModelSpec:
    name: str
    ar: int | str = 0          # int, or "aic" for 0..MAX_AR by AIC
    easter: bool = False
    pump: bool = False
    window: int | None = None  # None = expanding; else rolling window length in months
    ppi_lags: int = 0          # >0: add lags 1..ppi_lags of producer energy price m/m (round 2, D27)


def easter_regressor(dates: pd.DatetimeIndex) -> np.ndarray:
    """+1 in March and −1 in April when Easter falls in March, else 0. With month dummies,
    this shifts the Easter price effect between March and April in early-Easter years."""
    out = np.zeros(len(dates))
    for k, d in enumerate(dates):
        if d.month in (3, 4) and easter(d.year).month == 3:
            out[k] = 1.0 if d.month == 3 else -1.0
    return out


def _ppi_lags(dates: pd.DatetimeIndex, ppi: pd.Series, n: int) -> list[np.ndarray]:
    return [ppi.reindex(dates - pd.DateOffset(months=k)).to_numpy() for k in range(1, n + 1)]


def _design(dates: pd.DatetimeIndex, lags: np.ndarray | None, spec: ModelSpec,
            pump: pd.Series | None, ppi: pd.Series | None = None) -> np.ndarray:
    cols = [(dates.month.to_numpy() == m).astype(float) for m in range(1, 13)]
    if lags is not None and lags.size:
        cols += list(lags.T)
    if spec.easter:
        cols.append(easter_regressor(dates))
    if spec.pump:
        cols.append(pump.reindex(dates).to_numpy())
    if spec.ppi_lags:
        cols += _ppi_lags(dates, ppi, spec.ppi_lags)
    return np.column_stack(cols)


def _lag_matrix(y: np.ndarray, p: int, start: int) -> np.ndarray:
    return np.column_stack([y[start - k:len(y) - k] for k in range(1, p + 1)]) if p else np.empty((len(y) - start, 0))


@dataclass
class Fitted:
    spec: ModelSpec
    p: int
    beta: np.ndarray
    sigma: float
    n: int


def fit(y: pd.Series, spec: ModelSpec, pump: pd.Series | None = None, ppi: pd.Series | None = None) -> Fitted:
    """Fit on the whole of ``y`` (the caller truncates to the information set)."""
    y = y.dropna()
    if spec.pump:
        y = y[y.index.isin(pump.dropna().index)]
    if spec.ppi_lags:
        have = np.all(~np.isnan(np.column_stack(_ppi_lags(y.index, ppi, spec.ppi_lags))), axis=1)
        y = y[have]
    if spec.window:
        y = y.iloc[-spec.window:]
    v = y.to_numpy()
    start = MAX_AR  # common sample for every p, so AIC values are comparable
    dates = y.index[start:]
    target = v[start:]
    candidates = range(MAX_AR + 1) if spec.ar == "aic" else [int(spec.ar)]
    best = None
    for p in candidates:
        X = _design(dates, _lag_matrix(v, p, start), spec, pump, ppi)
        beta, *_ = np.linalg.lstsq(X, target, rcond=None)
        rss = float(((target - X @ beta) ** 2).sum())
        n, k = len(target), X.shape[1]
        aic = n * np.log(rss / n) + 2 * k
        if best is None or aic < best[0]:
            best = (aic, p, beta, np.sqrt(rss / (n - k)), n)
    _, p, beta, sigma, n = best
    return Fitted(spec=spec, p=p, beta=beta, sigma=float(sigma), n=n)


def predict(f: Fitted, y: pd.Series, horizon: int, pump: pd.Series | None = None,
            ppi: pd.Series | None = None) -> pd.Series:
    """Iterated h-step forecasts of y after its last observation."""
    hist = list(y.dropna().to_numpy())
    t0 = y.dropna().index[-1]
    out = {}
    for h in range(1, horizon + 1):
        d = pd.DatetimeIndex([t0 + pd.DateOffset(months=h)])
        lags = np.array([[hist[-k] for k in range(1, f.p + 1)]]) if f.p else None
        x = _design(d, lags, f.spec, pump, ppi)
        val = float((x @ f.beta)[0])
        hist.append(val)
        out[d[0]] = val
    return pd.Series(out)


def headline_path(comp_index: pd.DataFrame, comp_fc: pd.DataFrame, weights_known: pd.Series,
                  headline: pd.Series, origin: pd.Timestamp) -> pd.Series:
    """Chain-link component forecasts to the headline index for months after ``origin``.

    comp_index:    published component index levels up to the origin (and before)
    comp_fc:       forecast m/m log changes (×100), rows = target months, columns = components
    weights_known: weights of year(origin) (per mille); also used for year(origin)+1 because the
                   new year's weights are not published until its January data.
    headline:      published headline up to the origin
    Returns forecast headline index levels: H_{t+h} = H_t · A_{t+h} / A_t, with A the chain-linked
    aggregate of the components, so published-vs-rebuilt level differences cancel.
    """
    items = list(comp_fc.columns)
    s = weights_known[items] / weights_known[items].sum()
    lev = comp_index.loc[:origin, items].copy()
    last = lev.loc[origin]
    cum = np.exp(comp_fc.cumsum() / 100)
    fc_levels = cum.mul(last, axis=1)
    lev = pd.concat([lev, fc_levels])
    y = origin.year

    def agg(t: pd.Timestamp, base_year: int, base_level: float) -> float:
        return base_level * float((s * lev.loc[t, items] / lev.loc[dec(base_year), items]).sum())

    a_origin = agg(origin, y - 1, 1.0)
    a_dec = agg(dec(y), y - 1, 1.0) if dec(y) in lev.index else None
    out = {}
    for t in comp_fc.index:
        a_t = agg(t, y - 1, 1.0) if t.year == y else agg(t, y, a_dec)
        out[t] = float(headline.loc[origin]) * a_t / a_origin
    return pd.Series(out)


def yoy_path(path: pd.Series, headline: pd.Series) -> pd.Series:
    """YoY (%) of forecast levels against the published headline 12 months earlier."""
    base = headline.reindex(path.index - pd.DateOffset(years=1)).to_numpy()
    return pd.Series(100 * (path.to_numpy() / base - 1), index=path.index)
