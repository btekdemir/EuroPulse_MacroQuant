"""Round 4 (pre-registered in docs/DECISIONS.md D57, commit 6f20491): bottom-up variants.

The bottom-up machinery is unchanged (``backtest.bottom_up``: weights known at the origin, chain-link); only some
components' monthly forecasts are replaced:
  B1  services and non-energy industrial goods: last year's same-month m/m ("no change in y/y" for that component)
  B2  every component except fuels: last year's same-month m/m (fuels keep the pump-price model)
  B3  every component except fuels: 0.5 x current model + 0.5 x last year's same-month m/m (fixed weight)
Last year's same-month change of a target month T is y[T-12], published by the origin for h <= 12.
"""

from __future__ import annotations

import pandas as pd

from hicp import backtest as bt
from hicp.round2 import holm

H = 3
CORE = ["IGD_NNRG", "SERV"]
VARIANTS = {"B1_core_nochange": ("nochange", CORE), "B2_allbutfuel_nochange": ("nochange", None),
            "B3_allbutfuel_shrink": ("shrink", None)}
SAMPLES = {"full": ("1900-01", "2100-12"), "2010-2019": ("2010-01", "2019-12"), "2020-on": ("2020-01", "2100-12")}


def variant_components(inp: bt.Inputs, res: bt.BacktestResult, kind: str, comps: list[str]) -> pd.DataFrame:
    """The selected models' component forecasts, with ``comps`` replaced as ``kind`` says."""
    sel = pd.concat([res.comp_fc[(res.comp_fc.coicop == c) & (res.comp_fc.model == m)] for c, m in res.choice.items()])
    # y[T-12] read at its own date: T itself may lie beyond the published data (the latest origin's targets)
    ly = sel.apply(lambda r: inp.y.at[r.target - pd.DateOffset(years=1), r.coicop] if r.coicop in comps else None, axis=1)
    out = sel.copy()
    mask = out.coicop.isin(comps)
    if kind == "nochange":
        out.loc[mask, "fc"] = ly[mask].astype(float)
    else:
        out.loc[mask, "fc"] = 0.5 * out.loc[mask, "fc"] + 0.5 * ly[mask].astype(float)
    return out.assign(model="VARIANT")


def run_round4(inp: bt.Inputs, res: bt.BacktestResult) -> dict:
    s = inp.settings
    rw = bt.attach_actual_yoy(res.headline[res.headline.model == "RW"][["origin", "h", "target", "fc"]], inp)
    bu = bt.attach_actual_yoy(res.headline[res.headline.model == "bottom_up"][["origin", "h", "target", "fc"]], inp)
    heads = {}
    for name, (kind, comps) in VARIANTS.items():
        comps = comps or [c for c in s.components if c != "FUEL"]
        vc = variant_components(inp, res, kind, comps)
        heads[name] = bt.attach_actual_yoy(bt.bottom_up(inp, vc, {c: "VARIANT" for c in s.components}), inp).assign(model=name)
    # Checks of the measurement itself (added after the first run, before adoption; they do not enter the decision):
    # B0 replaces nothing and must reproduce the published bottom-up forecasts; under "no change" a replaced
    # component's forecast y/y must equal its y/y at the origin.
    b0 = bt.attach_actual_yoy(bt.bottom_up(inp, variant_components(inp, res, "nochange", []), {c: "VARIANT" for c in s.components}), inp)
    m0 = b0.merge(bu[["origin", "h", "fc"]], on=["origin", "h"], suffixes=("", "_bu"))
    checks = {"b0_vs_bottom_up_max_gap_pp": float((m0.fc - m0.fc_bu).abs().max()), "b0_rows": int(len(m0))}
    vc = variant_components(inp, res, "nochange", CORE)
    gaps = []
    for c in CORE:
        lvl = inp.index[c]
        for (t, g) in vc[vc.coicop == c].groupby("origin"):
            g = g.sort_values("target")
            cum = g.fc.cumsum().to_numpy() / 100
            for (_, r), cm in zip(g.iterrows(), cum):
                yoy_fc = 100 * (lvl[t] * pow(2.718281828459045, cm) / lvl[r.target - pd.DateOffset(years=1)] - 1)
                yoy_t = 100 * (lvl[t] / lvl[t - pd.DateOffset(years=1)] - 1)
                gaps.append(abs(yoy_fc - yoy_t))
    checks["nochange_component_yoy_max_gap_pp"] = float(max(gaps))
    rows = []
    for k, df in heads.items():
        for h in range(1, H + 1):
            for sname, (a, b) in SAMPLES.items():
                sel = lambda d: d[(d.h == h) & (d.origin >= pd.Timestamp(a)) & (d.origin <= pd.Timestamp(b))]  # noqa: E731
                mk = sel(df)
                if mk.actual.notna().sum() < 10:
                    continue
                met = bt.headline_metrics(mk, sel(rw))
                ref = sel(bu).merge(mk[["origin", "h", "fc"]], on=["origin", "h"], suffixes=("_bu", "")).dropna(subset=["actual"])
                p_bu = bt.diebold_mariano((ref.actual - ref.fc).to_numpy(), (ref.actual - ref.fc_bu).to_numpy(), h)[1]
                mse_bu = float(((ref.actual - ref.fc_bu) ** 2).mean())
                rows.append({"model": k, "h": h, "sample": sname, **{x: met[x] for x in ("n", "rmse", "mae", "rmse_rw", "rmse_ratio_vs_rw", "dm_p", "bias")},
                             "dm_p_vs_bottom_up": p_bu, "rmse_bottom_up": mse_bu ** 0.5})
    metrics = pd.DataFrame(rows)
    full3 = metrics[(metrics.h == H) & (metrics["sample"] == "full")].set_index("model")
    decision = holm({k: float(full3.at[k, "dm_p"]) for k in VARIANTS})
    passed = [d["name"] for d in decision if d["rejected"] and full3.at[d["name"], "rmse_ratio_vs_rw"] < 1]
    best = min(passed, key=lambda k: full3.at[k, "rmse"]) if passed else None
    adopted = best if best and full3.at[best, "rmse"] < full3.at[best, "rmse_bottom_up"] else None
    origin = max(df.origin.max() for df in heads.values())
    latest = {k: [{"target": f"{r.target:%Y-%m}", "h": int(r.h), "fc": float(r.fc)} for r in df[df.origin == origin].sort_values("h").itertuples()]
              for k, df in heads.items()}
    return {"metrics": metrics, "holm": decision, "best_passing": best, "adopted": adopted, "latest": latest, "checks": checks,
            "origin": f"{origin:%Y-%m}", "headline": pd.concat(heads.values(), ignore_index=True)}


# --------------------------------------------------------------------------- adoption (D57's rule)
NC = "NC"  # "no change in y/y" for a component: its next monthly changes repeat last year's same-month changes


def adopt(inp: bt.Inputs, res: bt.BacktestResult, variant: str, first_origin: str, sel_start: str, sel_end: str) -> bt.BacktestResult:
    """The backtest result with ``variant`` as the published bottom-up model: its components become model NC in
    the choice, the bottom-up headline rows and metrics are recomputed with the same code, and the selection log
    records the switch. Everything downstream (fan, calibration, real time, forecast, decomposition, shock basis,
    ledger) then uses it unchanged."""
    s = inp.settings
    kind, comps = VARIANTS[variant]
    comps = comps or [c for c in s.components if c != "FUEL"]
    if kind != "nochange":
        raise ValueError("only no-change variants are adoptable as a model choice")
    vc = variant_components(inp, res, "nochange", comps)
    nc = vc[vc.coicop.isin(comps)].assign(model=NC)
    comp = pd.concat([res.comp_fc, nc], ignore_index=True)
    old = dict(res.choice)
    choice = old | {c: NC for c in comps}
    bu = bt.attach_actual_yoy(bt.bottom_up(inp, comp, choice), inp).assign(model="bottom_up")
    head = pd.concat([res.headline[res.headline.model != "bottom_up"], bu], ignore_index=True)
    names = list(dict.fromkeys(res.headline.model))
    metrics = bt.headline_metrics_table(inp, head, names, first_origin, sel_start, sel_end)
    steps = pd.DataFrame([{"coicop": c, "candidate": f"{NC} (D57 round 4)", "vs": old[c], "accepted": True} for c in comps])
    sel = res.selection.copy()
    sel.loc[(sel.candidate == "SELECTED") & sel.coicop.isin(comps), "vs"] = NC
    selection = pd.concat([sel[sel.candidate != "SELECTED"], steps, sel[sel.candidate == "SELECTED"]], ignore_index=True)
    return bt.BacktestResult(comp_fc=comp, selection=selection, choice=choice, headline=head, metrics=metrics)
