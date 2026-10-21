"""Round 3 (pre-registered in docs/DECISIONS.md D56, commit a55dbf6): direct headline models against the random walk.

Implements exactly what D56 fixed before any of it ran: M1 naive (no change; seasonal naive, which is the same
thing algebraically and is checked), M2 SARIMA airline model, M3 Elastic Net, M4 histogram gradient boosting
(the LightGBM family, from scikit-learn), M5 equal-weight M3+M4. Direct models predict the change in headline
y/y from t to t+h from features known at t, trained only on pairs whose target month is <= t. Holm at 5% over
{M2..M5}, DM against the random walk at h = 3 on all origins.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from hicp import backtest as bt
from hicp.chainlink import yoy
from hicp.round2 import holm

H = 3
FIRST_ROW = pd.Timestamp("2001-01-01")      # first feature row with every lag available
SARIMA_START = pd.Timestamp("2002-01-01")
FAMILY = ["M2_sarima", "M3_enet", "M4_gbm", "M5_ensemble"]
SAMPLES = {"full": ("1900-01", "2100-12"), "2010-2019": ("2010-01", "2019-12"), "2020-on": ("2020-01", "2100-12")}


# --------------------------------------------------------------------------- features (all known at the origin)
def feature_table(ix: pd.DataFrame, comps: list[str], headline: str) -> pd.DataFrame:
    hy = yoy(ix[headline])
    f = pd.DataFrame({"y0": hy, "y1": hy.shift(1), "y2": hy.shift(2), "y6": hy.shift(6), "y12": hy.shift(12)})
    for c in comps:
        cy = yoy(ix[c])
        f[f"c_{c}"] = cy
        f[f"d3_{c}"] = cy - cy.shift(3)
    return f


def base_effect(ix: pd.Series, h: int) -> pd.Series:
    """At origin t: sum of last year's headline log m/m for the months t+1-12 .. t+h-12 (they drop out by t+h)."""
    lm = 100 * np.log(ix).diff()
    return sum(lm.shift(12 - k) for k in range(1, h + 1))


def design(ix: pd.DataFrame, comps: list[str], headline: str, h: int) -> tuple[pd.DataFrame, pd.Series]:
    f = feature_table(ix, comps, headline)
    f["base"] = base_effect(ix[headline], h)
    f["month"] = [((t.month + h - 1) % 12) + 1 for t in f.index]   # calendar month of the target
    hy = yoy(ix[headline])
    target = hy.shift(-h) - hy                                       # change in y/y from t to t+h
    return f, target


def _month_dummies(X: pd.DataFrame) -> pd.DataFrame:
    d = pd.get_dummies(X["month"].astype(int), prefix="m").reindex(columns=[f"m_{k}" for k in range(1, 13)], fill_value=0)
    return pd.concat([X.drop(columns="month"), d.astype(float)], axis=1)


# --------------------------------------------------------------------------- models
def _enet():
    from sklearn.linear_model import ElasticNetCV
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), ElasticNetCV(l1_ratio=[0.1, 0.5, 0.9], alphas=30, cv=TimeSeriesSplit(5), max_iter=10000))


def _gbm():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_depth=2, max_iter=200, learning_rate=0.05, min_samples_leaf=20,
                                         l2_regularization=1.0, early_stopping=False, random_state=0)


def direct_forecasts(ix: pd.DataFrame, comps: list[str], headline: str, origins: list[pd.Timestamp]) -> pd.DataFrame:
    """M3, M4, M5 at every origin and horizon, expanding window, refitted each time."""
    hy = yoy(ix[headline])
    rows = []
    for h in range(1, H + 1):
        X, y = design(ix, comps, headline, h)
        ok = X.notna().all(axis=1) & (X.index >= FIRST_ROW)
        for t in origins:
            tr = ok & y.notna() & (X.index + pd.DateOffset(months=h) <= t)   # target month already published at t
            if tr.sum() < 60 or not ok.get(t, False):
                continue
            Xtr, ytr, xt = X[tr], y[tr], X.loc[[t]]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                en = _enet().fit(_month_dummies(Xtr), ytr).predict(_month_dummies(xt))[0]
            gb = _gbm().fit(Xtr, ytr).predict(xt)[0]
            base = float(hy[t])
            target = t + pd.DateOffset(months=h)
            rows += [(t, h, target, base + en, "M3_enet"), (t, h, target, base + gb, "M4_gbm"),
                     (t, h, target, base + (en + gb) / 2, "M5_ensemble")]
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc", "model"])


def sarima_forecasts(ix: pd.Series, origins: list[pd.Timestamp]) -> pd.DataFrame:
    """M2: airline model (0,1,1)(0,1,1)_12 on 100·log index, fitted at each origin on data from 2002-01."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    lg = 100 * np.log(ix)
    rows = []
    for t in origins:
        endog = lg.loc[SARIMA_START:t].asfreq("MS")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = SARIMAX(endog, order=(0, 1, 1), seasonal_order=(0, 1, 1, 12)).fit(disp=False)
        path = res.get_forecast(H).predicted_mean
        for h, (target, v) in enumerate(path.items(), start=1):
            rows.append((t, h, target, float(100 * (np.exp(v / 100) / ix[target - pd.DateOffset(years=1)] - 1)), "M2_sarima"))
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc", "model"])


def seasonal_naive(ix: pd.Series, origins: list[pd.Timestamp]) -> pd.DataFrame:
    """M1b: the next h months repeat last year's monthly changes. Equals 'no change in y/y' algebraically."""
    rows = []
    for t in origins:
        for h in range(1, H + 1):
            target = t + pd.DateOffset(months=h)
            lvl = ix[t] * ix[target - pd.DateOffset(years=1)] / ix[t - pd.DateOffset(years=1)]
            rows.append((t, h, target, float(100 * (lvl / ix[target - pd.DateOffset(years=1)] - 1)), "M1b_seasonal_naive"))
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc", "model"])


# --------------------------------------------------------------------------- evaluation (D56 rule)
def run_round3(inp: bt.Inputs, res: bt.BacktestResult) -> dict:
    # One native thread pool: on macOS, scikit-learn's OpenMP and the BLAS behind numpy/statsmodels running many
    # threads side by side crashed the process intermittently (segfault, about one run in two). Single-threaded,
    # it is stable and the models are small enough that it costs little time.
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        return _run_round3(inp, res)


def _run_round3(inp: bt.Inputs, res: bt.BacktestResult) -> dict:
    s = inp.settings
    ix = inp.index
    origins = sorted(res.headline[res.headline.model == "bottom_up"].origin.unique())
    rw = bt.attach_actual_yoy(res.headline[res.headline.model == "RW"][["origin", "h", "target", "fc"]], inp)
    bu = bt.attach_actual_yoy(res.headline[res.headline.model == "bottom_up"][["origin", "h", "target", "fc"]], inp)

    naive = bt.attach_actual_yoy(seasonal_naive(ix[s.headline], origins), inp)
    chk = naive.merge(rw[["origin", "h", "fc"]], on=["origin", "h"], suffixes=("", "_rw"))
    naive_gap = float((chk.fc - chk.fc_rw).abs().max())

    cands = pd.concat([sarima_forecasts(ix[s.headline], origins), direct_forecasts(ix, s.components, s.headline, origins)],
                      ignore_index=True)
    cands = bt.attach_actual_yoy(cands[["origin", "h", "target", "fc"]].assign(model=cands.model), inp)

    rows = []
    for k in FAMILY:
        for h in range(1, H + 1):
            for sname, (a, b) in SAMPLES.items():
                sel = lambda d: d[(d.h == h) & (d.origin >= pd.Timestamp(a)) & (d.origin <= pd.Timestamp(b))]  # noqa: E731
                mk = sel(cands[cands.model == k])
                if mk.actual.notna().sum() < 10:
                    continue
                met = bt.headline_metrics(mk, sel(rw))
                ref = sel(bu).merge(mk[["origin", "h", "fc"]], on=["origin", "h"], suffixes=("_bu", "")).dropna(subset=["actual"])
                p_bu = bt.diebold_mariano((ref.actual - ref.fc).to_numpy(), (ref.actual - ref.fc_bu).to_numpy(), h)[1]
                rows.append({"model": k, "h": h, "sample": sname, **{x: met[x] for x in ("n", "rmse", "mae", "rmse_rw", "rmse_ratio_vs_rw", "dm_p", "bias")},
                             "dm_p_vs_bottom_up": p_bu})
    metrics = pd.DataFrame(rows)
    full3 = metrics[(metrics.h == H) & (metrics["sample"] == "full")].set_index("model")
    decision = holm({k: float(full3.at[k, "dm_p"]) for k in FAMILY})
    passed = [d["name"] for d in decision if d["rejected"] and full3.at[d["name"], "rmse_ratio_vs_rw"] < 1]
    candidate = min(passed, key=lambda k: full3.at[k, "rmse"]) if passed else None
    last = cands[cands.origin == cands.origin.max()].sort_values(["model", "h"])
    latest = {k: [{"target": f"{r.target:%Y-%m}", "h": int(r.h), "fc": float(r.fc)} for r in g.itertuples()] for k, g in last.groupby("model")}
    return {"metrics": metrics, "holm": decision, "candidate": candidate, "naive_equals_rw_max_gap": naive_gap,
            "latest": latest, "origin": f"{max(origins):%Y-%m}", "headline": cands}
