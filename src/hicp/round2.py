"""Round 2 (pre-registered in docs/DECISIONS.md D27): can any candidate beat the random walk at h = 3?

Implements exactly the three candidates and the decision rule written down before this code ran:
C1 producer-price-led electricity & gas (gated by the D9 component rule), C2 equal-weight combination of
bottom-up and direct AR, C3 intercept correction with the last three known one-month errors. Holm over the
family {current bottom-up, C1, C2, C3} at 5%, DM vs random walk, h = 3, all origins.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hicp import backtest as bt
from hicp import forecast as fc

ALPHA = 0.05
H3 = 3
PPI_SPEC = fc.ModelSpec("PPI", ar=0, ppi_lags=6)


def spec_by_name(name: str, comp: str) -> fc.ModelSpec:
    base = {sp.name: sp for sp in bt.candidate_specs(comp)}
    if "_R" in name:
        n, w = name.split("_R")
        return bt._with_window(base[n], int(w))
    return base[name]


def holm(pvals: dict[str, float | None], alpha: float = ALPHA) -> list[dict]:
    """Holm step-down. None (a candidate gated out) counts as p = 1 and is never rejected."""
    items = sorted(((1.0 if p is None else p), k) for k, p in pvals.items())
    m, out, still = len(items), [], True
    for i, (p, k) in enumerate(items):
        thr = alpha / (m - i)
        rej = still and p <= thr
        still = rej
        out.append({"name": k, "p": None if pvals[k] is None else p, "threshold": thr, "rejected": rej})
    return out


def _rows(df: pd.DataFrame, name: str) -> pd.DataFrame:
    return df[["origin", "h", "target", "fc"]].assign(model=name)


def intercept_corrected(inp: bt.Inputs, res: bt.BacktestResult) -> pd.DataFrame:
    """C3: bottom-up + mean of the last three one-month-ahead errors known at the origin.

    Implementation note (not anticipated in D27): errors exist only from the first backtest origin on
    (pre-2010 bottom-up forecasts cannot be made: the fuel model needs 60 months of bulletin data). So the
    first three origins (2010-01..03) use the 0, 1 or 2 errors already known, and 2010-01 has no correction."""
    bu = bt.attach_actual_yoy(res.headline[res.headline.model == "bottom_up"][["origin", "h", "target", "fc"]], inp)
    h1 = bu[bu.h == 1].set_index("target")
    err1 = (h1.actual - h1.fc)  # one-month error, indexed by the month it was about
    rows = []
    for t, g in bu.groupby("origin"):
        known = err1[(err1.index <= t)].dropna().sort_index().iloc[-3:]  # targets t-2, t-1, t
        corr = float(known.mean()) if len(known) else 0.0
        for r in g.itertuples():
            rows.append((t, r.h, r.target, r.fc + corr))
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc"])


def run_round2(inp: bt.Inputs, res: bt.BacktestResult, sel_start: str, sel_end: str) -> dict:
    origins = sorted(res.headline.origin.unique())
    rw = res.headline[res.headline.model == "RW"]

    # ---- C1 component stage (D9 rule vs the current ELC_GAS model)
    c1_fc = bt.run_components(inp, list(origins), {"ELC_GAS": [PPI_SPEC]})
    cur = res.choice["ELC_GAS"]
    both = pd.concat([res.comp_fc[(res.comp_fc.coicop == "ELC_GAS") & (res.comp_fc.model == cur)], c1_fc])
    cum = bt.cumulative_errors(both)
    g = cum[(cum.origin >= pd.Timestamp(sel_start)) & (cum.origin <= pd.Timestamp(sel_end))]
    w = g.assign(e=g.actual - g.fc).pivot(index="origin", columns="model", values="e").dropna()
    stat, p_gate = bt.diebold_mariano(w["PPI"].to_numpy(), w[cur].to_numpy(), bt.H)
    mse_ppi, mse_cur = float((w["PPI"] ** 2).mean()), float((w[cur] ** 2).mean())
    gate_ok = mse_ppi < mse_cur and p_gate < ALPHA
    gate = {"component": "ELC_GAS", "candidate": "PPI", "vs": cur, "n": int(len(w)), "mse_candidate": mse_ppi,
            "mse_current": mse_cur, "dm_stat": stat, "dm_p": p_gate, "passed": bool(gate_ok)}

    # full-sample component diagnostic (reported, not used for the gate)
    wf = cum.assign(e=cum.actual - cum.fc).pivot(index="origin", columns="model", values="e").dropna()
    gate["full_sample_mse_ratio"] = float((wf["PPI"] ** 2).mean() / (wf[cur] ** 2).mean())

    cands: dict[str, pd.DataFrame] = {"bottom_up": res.headline[res.headline.model == "bottom_up"]}
    comp_all = pd.concat([res.comp_fc, c1_fc])
    c1 = bt.bottom_up(inp, comp_all, res.choice | {"ELC_GAS": "PPI"})  # computed either way, for reporting
    cands["C1_ppi"] = c1
    dar = res.headline[res.headline.model == "direct_AR"]
    m = cands["bottom_up"].merge(dar, on=["origin", "h", "target"], suffixes=("_bu", "_ar"))
    cands["C2_combo"] = m.assign(fc=(m.fc_bu + m.fc_ar) / 2)[["origin", "h", "target", "fc"]]
    cands["C3_ic"] = intercept_corrected(inp, res)

    head = pd.concat([bt.attach_actual_yoy(_rows(df, k), inp) for k, df in cands.items()], ignore_index=True)
    rw_a = bt.attach_actual_yoy(rw, inp)
    bu_a = head[head.model == "bottom_up"]
    samples = {"full": ("1900-01", "2100-12"), "2010-2019": ("2010-01", "2019-12"), "2020-on": ("2020-01", "2100-12")}
    rows = []
    for k in cands:
        for h in (1, 2, 3):
            for sname, (a, b) in samples.items():
                sel = lambda d: d[(d.h == h) & (d.origin >= pd.Timestamp(a)) & (d.origin <= pd.Timestamp(b))]  # noqa: E731
                mk, r = sel(head[head.model == k]), sel(rw_a)
                if mk.actual.notna().sum() < 10:
                    continue
                met = bt.headline_metrics(mk, r)
                ref = sel(bu_a).merge(mk[["origin", "h", "fc"]], on=["origin", "h"], suffixes=("_bu", "")).dropna(subset=["actual"])
                p_bu = (bt.diebold_mariano((ref.actual - ref.fc).to_numpy(), (ref.actual - ref.fc_bu).to_numpy(), h)[1]
                        if k != "bottom_up" else None)
                rows.append({"model": k, "h": h, "sample": sname, **met, "dm_p_vs_bottom_up": p_bu})
    metrics = pd.DataFrame(rows)
    full3 = metrics[(metrics.h == H3) & (metrics["sample"] == "full")].set_index("model")
    pvals = {k: (None if (k == "C1_ppi" and not gate_ok) else float(full3.at[k, "dm_p"])) for k in cands}
    decision = holm(pvals)
    passed = [d["name"] for d in decision if d["rejected"] and d["name"] != "bottom_up"]
    adopted = min(passed, key=lambda k: full3.at[k, "rmse"]) if passed else None
    return {"gate": gate, "metrics": metrics, "holm": decision, "adopted": adopted,
            "bottom_up_passes": any(d["rejected"] for d in decision if d["name"] == "bottom_up"), "headline": head}
