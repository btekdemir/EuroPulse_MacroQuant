"""Real-time robustness check (docs/DECISIONS.md D29): score the backtest against what Eurostat
published at the time, with a random walk that also uses only first-published figures.

First releases: legacy ``prc_hicp_fp`` (ver.1, CP00) up to Dec 2025 (flash from Aug 2017); ``prc_hicp_fpd``
(ver.2, TOTAL) from Jan 2026. ``prc_hicp_fpd`` values before 2026 are reclassified back-series, not used.
Inputs to the forecasts stay latest-vintage: full real-time component vintages do not exist.
"""

from __future__ import annotations

import pandas as pd

from hicp import backtest as bt
from hicp.clean import CleanData

SWITCH = pd.Timestamp("2026-01-01")


def first_releases(d: CleanData) -> dict[str, pd.Series]:
    out = {}
    for rel in ("FIN", "FLS"):
        old = d.first_release_legacy[d.first_release_legacy.release == rel].set_index("date")["value"]
        new = d.first_release[d.first_release.release == rel].set_index("date")["value"]
        out[rel] = pd.concat([old[old.index < SWITCH], new[new.index >= SWITCH]]).sort_index()
    return out


def evaluate(d: CleanData, res: bt.BacktestResult, models: tuple[str, ...] = ("bottom_up", "direct_AR")) -> list[dict]:
    fr = first_releases(d)
    head = res.headline
    rows = []
    for target_rel, label in (("FIN", "first full release"), ("FLS", "flash")):
        outcome = fr[target_rel]
        rw_rt = fr["FIN"]  # the last print as first published at the origin
        for m in models:
            for h in (1, 2, 3):
                g = head[(head.model == m) & (head.h == h)].copy()
                g["actual_rt"] = g.target.map(outcome)
                g["rw_rt"] = g.origin.map(rw_rt)
                g = g.dropna(subset=["actual_rt", "rw_rt", "actual"])
                if len(g) < 20:
                    continue
                rw = head[(head.model == "RW") & (head.h == h)].set_index("origin")["fc"]
                e_m = g.actual_rt - g.fc
                e_rw = g.actual_rt - g.rw_rt
                stat, p = bt.diebold_mariano(e_m.to_numpy(), e_rw.to_numpy(), h)
                e_m_lv = g.actual - g.fc  # same origins, latest-vintage outcome and random walk
                e_rw_lv = g.actual - g.origin.map(rw)
                stat_lv, p_lv = bt.diebold_mariano(e_m_lv.to_numpy(), e_rw_lv.to_numpy(), h)
                rmse = lambda e: float((e ** 2).mean() ** 0.5)  # noqa: E731
                rows.append({"target": label, "model": m, "h": h, "n": int(len(g)),
                             "from": f"{g.origin.min():%Y-%m}", "to": f"{g.origin.max():%Y-%m}",
                             "rmse": rmse(e_m), "rmse_rw": rmse(e_rw), "ratio": rmse(e_m) / rmse(e_rw), "dm_p": p,
                             "ratio_latest_vintage": rmse(e_m_lv) / rmse(e_rw_lv), "dm_p_latest_vintage": p_lv})
    return rows
