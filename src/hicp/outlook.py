"""The live forecast from the latest origin: path, fan, contributions, base effect vs momentum.

Uses exactly the machinery that was backtested: the selected component models, the bottom-up
chain-link with the weights known at the origin, and the backtest's own out-of-sample errors
for the fan (empirical quantiles per horizon, not model-implied bands).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hicp import forecast as fc
from hicp.backtest import H, BacktestResult, Inputs, pump_feature
from hicp.chainlink import base_momentum, effective_weights, exact_contributions, yoy
from hicp.external import release_date

QUANTILES = (0.05, 0.16, 0.5, 0.84, 0.95)


def build_outlook(inp: Inputs, bt: BacktestResult) -> dict:
    s = inp.settings
    comps = s.components
    origin = inp.index.index.max()
    sel = pd.concat([bt.comp_fc[(bt.comp_fc.origin == origin) & (bt.comp_fc.coicop == c) & (bt.comp_fc.model == m)]
                     for c, m in bt.choice.items()])
    mom = sel.pivot(index="target", columns="coicop", values="fc")[comps]
    head_pub = inp.index[s.headline]
    path = fc.headline_path(inp.index[comps], mom, inp.weights.loc[origin.year], head_pub, origin)
    point = fc.yoy_path(path, head_pub)

    # Fan: point + empirical quantiles of out-of-sample errors (actual − forecast), per horizon.
    bu = bt.headline[(bt.headline.model == "bottom_up")].dropna(subset=["actual"])
    err_q = {h: (bu[bu.h == h].actual - bu[bu.h == h].fc).quantile(list(QUANTILES)) for h in range(1, H + 1)}

    # Extended frames: published history + forecast levels, for contributions and base effects.
    levels = inp.index.loc[:origin, comps].iloc[-1] * np.exp(mom.cumsum() / 100)
    ext = pd.concat([inp.index.loc[:origin, comps + [s.headline]],
                     levels.assign(**{s.headline: path})])
    w = inp.weights.copy()
    contrib = exact_contributions(ext, w, comps, s.headline)
    comp_yoy = yoy(ext[comps])
    weff = effective_weights(inp.index.loc[:origin], w, comps).loc[origin]

    points = []
    for h, t in enumerate(point.index, start=1):
        bm = base_momentum(ext[s.headline], origin, h)
        points.append({
            "date": f"{t:%Y-%m}", "horizon": h, "point": float(point[t]),
            "quantiles": {f"q{int(q * 100):02d}": float(point[t] + err_q[h][q]) for q in QUANTILES},
            "base_effect_pp": bm["base_effect_pp"], "momentum_pp": bm["momentum_pp"],
            "contributions": {c: float(contrib.at[t, c]) for c in comps},
            "component_yoy": {c: float(comp_yoy.at[t, c]) for c in comps},
            "component_mom": {c: float(mom.at[t, c]) for c in comps},
        })

    hist_months = contrib.index[(contrib.index <= origin) & (contrib.index >= origin - pd.DateOffset(years=6))]
    history = [{"date": f"{t:%Y-%m}", "yoy": float(yoy(head_pub)[t]),
                "contributions": {c: float(contrib.at[t, c]) for c in comps}} for t in hist_months]

    pump = pump_feature(inp, origin) if inp.pump_w is not None else None
    ext_cfg = s.raw["external"]
    cutoff = release_date(origin, ext_cfg["release_day"]) - pd.Timedelta(days=ext_cfg["bulletin_lag_days"])
    known_mondays = inp.pump_w[(inp.pump_w.index > origin + pd.offsets.MonthEnd(0)) & (inp.pump_w.index <= cutoff)]
    assumptions = [
        f"Origin {origin:%Y-%m} (last full Eurostat release). Target: Dec {origin.year} YoY at h=3.",
        f"Item weights {origin.year} (published); no new annual weights enter before January.",
        f"Fuels: Weekly Oil Bulletin Mondays known by {cutoff:%d %b %Y}: "
        f"{', '.join(f'{d:%d %b}' for d in known_mondays.index) or 'none'}; later weeks held flat at the last price.",
        "No Brent futures bridge: pump prices beyond the last bulletin are a no-change assumption.",
        "Fan: empirical quantiles of the backtest's own out-of-sample errors per horizon "
        f"({len(bu[bu.h == 1])} origins from {bu.origin.min():%Y-%m}), centred on the point forecast.",
    ]
    return {
        "origin": f"{origin:%Y-%m}", "last_actual_yoy": float(yoy(head_pub)[origin]), "ecb_target": 2.0,
        "points": points, "history": history, "selected_models": dict(bt.choice),
        "effective_weights": {c: float(weff[c]) for c in comps},
        "official_weights": {c: float(w.at[origin.year, c] / 1000) for c in comps},
        "pump_mom_assumed": {f"{t:%Y-%m}": float(pump[t]) for t in mom.index} if pump is not None else {},
        "assumptions": assumptions,
    }
