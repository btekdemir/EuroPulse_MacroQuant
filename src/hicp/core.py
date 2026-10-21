"""Core inflation (HICP excluding energy, food, alcohol and tobacco: Eurostat TOT_X_NRG_FOOD) as a by-product.

No new model: core is the chain-linked aggregate of two of the six components already forecast for the
headline (non-energy industrial goods and services), with the same component models (chosen for the
headline by the D9 rule), the same weights known at each origin and the same bottom-up machinery. The
published TOT_X_NRG_FOOD index is the actual, so the aggregation itself is checked against Eurostat.

Because the models were selected for the headline, the core backtest below is a check, not a selection:
it reports how well the by-product does, against a random walk on core, on the same origins.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hicp import forecast as fc
from hicp.backtest import H, BacktestResult, Inputs, headline_metrics
from hicp.chainlink import base_momentum, exact_contributions, yoy

CORE = "TOT_X_NRG_FOOD"
ITEMS = ["IGD_NNRG", "SERV"]
SAMPLES = {"full": ("1900-01", "2100-12"), "2010-2019": ("2010-01", "2019-12"), "2020-2023": ("2020-01", "2023-12"),
           "2024-now": ("2024-01", "2100-12")}
QUANTILES = (0.05, 0.16, 0.84, 0.95)


def _paths(inp: Inputs, bt: BacktestResult) -> pd.DataFrame:
    """Core y/y forecasts h=1..3 for every backtest origin, from the selected goods and services models."""
    core = inp.index[CORE]
    sel = pd.concat([bt.comp_fc[(bt.comp_fc.coicop == c) & (bt.comp_fc.model == bt.choice[c])] for c in ITEMS])
    rows = []
    for t, g in sel.groupby("origin"):
        wide = g.pivot(index="target", columns="coicop", values="fc")[ITEMS]
        path = fc.headline_path(inp.index[ITEMS], wide, inp.weights.loc[t.year], core, t)
        for h, (target, v) in enumerate(fc.yoy_path(path, core).items(), start=1):
            rows.append((t, h, target, float(v)))
    df = pd.DataFrame(rows, columns=["origin", "h", "target", "fc"])
    cy = yoy(core)
    return df.assign(actual=df.target.map(cy), last=df.origin.map(cy))


def core_view(inp: Inputs, bt: BacktestResult) -> dict:
    core, head = inp.index[CORE], inp.index[inp.settings.headline]
    cy, hy = yoy(core), yoy(head)
    df = _paths(inp, bt)
    rw = df[["origin", "h", "target"]].assign(fc=df["last"])
    metrics = []
    for h in range(1, H + 1):
        for name, (a, b) in SAMPLES.items():
            m = (df.h == h) & (df.origin >= pd.Timestamp(a)) & (df.origin <= pd.Timestamp(b))
            sub = df[m].dropna(subset=["actual"])
            if len(sub) > 10:
                r = headline_metrics(sub, rw)
                metrics.append({"h": h, "sample": name, **{k: (None if isinstance(v, float) and np.isnan(v) else v)
                                                           for k, v in r.items() if k != "direction_accuracy"}})

    # live forecast from the latest origin, with a fan from the core backtest's own errors
    origin = inp.index.index.max()
    live = df[df.origin == origin].sort_values("h")
    known = df.dropna(subset=["actual"])
    err = {h: (known[known.h == h].actual - known[known.h == h].fc) for h in range(1, H + 1)}
    sel = pd.concat([bt.comp_fc[(bt.comp_fc.origin == origin) & (bt.comp_fc.coicop == c) & (bt.comp_fc.model == bt.choice[c])]
                     for c in ITEMS])
    mom = sel.pivot(index="target", columns="coicop", values="fc")[ITEMS]
    path = fc.headline_path(inp.index[ITEMS], mom, inp.weights.loc[origin.year], core, origin)
    levels = inp.index.loc[:origin, ITEMS].iloc[-1] * np.exp(mom.cumsum() / 100)
    ext = pd.concat([inp.index.loc[:origin, ITEMS + [CORE]], levels.assign(**{CORE: path})])
    contrib = exact_contributions(ext, inp.weights, ITEMS, CORE)
    points = []
    for r in live.itertuples():
        bm = base_momentum(ext[CORE], origin, int(r.h))
        points.append({"date": f"{r.target:%Y-%m}", "horizon": int(r.h), "point": r.fc,
                       "quantiles": {f"q{int(q * 100):02d}": float(r.fc + err[r.h].quantile(q)) for q in QUANTILES},
                       "contributions": {c: float(contrib.at[r.target, c]) for c in ITEMS},
                       "base_effect_pp": bm["base_effect_pp"], "momentum_pp": bm["momentum_pp"]})

    # aggregation check: goods + services contributions vs the published core y/y
    hist = contrib.index[(contrib.index <= origin) & (contrib.index >= pd.Timestamp("2010-01-01"))]
    gap = float((contrib.loc[hist, ITEMS].sum(axis=1) - cy.reindex(hist)).abs().max())
    window = list(hist)  # from 2010, so the "All" button shows the whole scored period (D61)
    history = [{"date": f"{t:%Y-%m}", "core_yoy": float(cy[t]), "headline_yoy": float(hy[t]),
                "contributions": {c: float(contrib.at[t, c]) for c in ITEMS}} for t in window]
    return {"origin": f"{origin:%Y-%m}", "last_actual": float(cy[origin]), "points": points, "history": history,
            "metrics": metrics, "max_abs_gap_pp": gap, "n_origins": int(df.origin.nunique()),
            "models": {c: bt.choice[c] for c in ITEMS}}
