"""Walk-forward backtest: expanding window, information set as known at each origin (D9).

An *origin* t is a month whose full HICP release is out. At that point the forecaster knows:
index data up to t; item weights of year(t) (published with January data); and Weekly Oil
Bulletin prices for Mondays up to (release date of t − 3 days). Forecasts are made for t+1..t+3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from hicp import forecast as fc
from hicp.clean import CleanData
from hicp.config import Settings
from hicp.external import pump_monthly_known

log = logging.getLogger(__name__)
H = 3

SM = fc.ModelSpec("SM", ar=0)
AR1 = fc.ModelSpec("AR1", ar=1)


def candidate_specs(component: str) -> list[fc.ModelSpec]:
    """The ladder of D9: SM -> AR1 -> richer models."""
    rich = [fc.ModelSpec("ARP", ar="aic", easter=component == "SERV")]
    if component == "FUEL":
        rich.append(fc.ModelSpec("PUMP", ar=0, pump=True))
    return [SM, AR1, *rich]


def log_changes(index: pd.DataFrame, start: str) -> pd.DataFrame:
    y = 100 * np.log(index).diff()
    return y[y.index >= pd.Timestamp(start)]


@dataclass
class Inputs:
    index: pd.DataFrame      # EA I25 wide (components + headline)
    y: pd.DataFrame          # 100·Δln, from the estimation start
    weights: pd.DataFrame    # EA item weights wide
    pump_w: pd.Series | None
    settings: Settings


def make_inputs(d: CleanData, s: Settings, pump_w: pd.Series | None) -> Inputs:
    ix = d.index_wide(s.ea)
    return Inputs(index=ix, y=log_changes(ix[[s.headline] + s.components], s.raw["chainlink_start"]),
                  weights=d.weights_wide(s.ea), pump_w=pump_w, settings=s)


def pump_feature(inp: Inputs, origin: pd.Timestamp) -> pd.Series:
    """100·Δln of monthly-average pump prices as known at the origin (history + t+1..t+H)."""
    ext = inp.settings.raw["external"]
    hist = inp.pump_w[inp.pump_w.index <= origin + pd.offsets.MonthEnd(0)].resample("MS").mean()
    fut = pump_monthly_known(inp.pump_w, origin, H, ext["release_day"], ext["bulletin_lag_days"])
    lvl = pd.concat([hist[hist.index <= origin], fut[fut.index > origin]])
    return (100 * np.log(lvl).diff()).rename("pump")


def forecast_component(inp: Inputs, comp: str, spec: fc.ModelSpec, origin: pd.Timestamp,
                       pump: pd.Series | None) -> pd.Series:
    y = inp.y[comp].loc[:origin]
    f = fc.fit(y, spec, pump)
    return fc.predict(f, y, H, pump)


def run_components(inp: Inputs, origins: list[pd.Timestamp], specs: dict[str, list[fc.ModelSpec]]) -> pd.DataFrame:
    rows = []
    for k, t in enumerate(origins):
        pump = pump_feature(inp, t) if inp.pump_w is not None else None
        for comp, ss in specs.items():
            for spec in ss:
                if spec.pump and (pump is None or pump.loc[:t].dropna().size < 60):
                    continue
                path = forecast_component(inp, comp, spec, t, pump)
                for h, (target, v) in enumerate(path.items(), start=1):
                    rows.append((t, comp, spec.name, h, target, v))
        if k % 50 == 0:
            log.info("  backtest origin %s (%d/%d)", f"{t:%Y-%m}", k + 1, len(origins))
    out = pd.DataFrame(rows, columns=["origin", "coicop", "model", "h", "target", "fc"])
    actual = inp.y.stack().rename("actual")
    actual.index.names = ["target", "coicop"]
    return out.join(actual, on=["target", "coicop"])


def cumulative_errors(comp_fc: pd.DataFrame, h: int = H) -> pd.DataFrame:
    """Cumulative log change over t+1..t+h per origin/component/model: forecast vs actual."""
    c = comp_fc[comp_fc.h <= h].groupby(["origin", "coicop", "model"])[["fc", "actual"]].agg(["sum", "count"])
    c = c[(c[("fc", "count")] == h) & (c[("actual", "count")] == h)]
    return pd.DataFrame({"fc": c[("fc", "sum")], "actual": c[("actual", "sum")]}).reset_index()


# --------------------------------------------------------------------------- headline
def bottom_up(inp: Inputs, comp_fc: pd.DataFrame, choice: dict[str, str]) -> pd.DataFrame:
    """Headline YoY forecasts from the chosen component models, for every origin."""
    s = inp.settings
    head = inp.index[s.headline]
    rows = []
    sel = pd.concat([comp_fc[(comp_fc.coicop == c) & (comp_fc.model == m)] for c, m in choice.items()])
    for t, g in sel.groupby("origin"):
        wide = g.pivot(index="target", columns="coicop", values="fc")[s.components]
        w = inp.weights.loc[t.year]
        path = fc.headline_path(inp.index[s.components], wide, w, head, t)
        yy = fc.yoy_path(path, head)
        for h, (target, v) in enumerate(yy.items(), start=1):
            rows.append((t, h, target, v))
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc"])


def direct_headline(inp: Inputs, origins: list[pd.Timestamp], spec: fc.ModelSpec) -> pd.DataFrame:
    s = inp.settings
    head = inp.index[s.headline]
    rows = []
    for t in origins:
        mom = forecast_component(inp, s.headline, spec, t, None)
        path = head.loc[t] * np.exp(mom.cumsum() / 100)
        for h, (target, v) in enumerate(fc.yoy_path(path, head).items(), start=1):
            rows.append((t, h, target, v))
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc"])


def seasonal_rw(inp: Inputs, origins: list[pd.Timestamp]) -> pd.DataFrame:
    """Headline m/m in t+h = m/m in the same month a year earlier.

    Not scored separately: it is algebraically identical to the random walk on YoY, because
    H_t · (H_{t+h-12} / H_{t-12}) / H_{t+h-12} = H_t / H_{t-12}. The identity is pinned by a test.
    """
    s = inp.settings
    head = inp.index[s.headline]
    y = inp.y[s.headline]
    rows = []
    for t in origins:
        targets = [t + pd.DateOffset(months=h) for h in range(1, H + 1)]
        mom = pd.Series([y[d - pd.DateOffset(years=1)] for d in targets], index=targets)
        path = head.loc[t] * np.exp(mom.cumsum() / 100)
        for h, (target, v) in enumerate(fc.yoy_path(path, head).items(), start=1):
            rows.append((t, h, target, v))
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc"])


def random_walk(inp: Inputs, origins: list[pd.Timestamp]) -> pd.DataFrame:
    head = inp.index[inp.settings.headline]
    yy = 100 * (head / head.shift(12) - 1)
    rows = [(t, h, t + pd.DateOffset(months=h), float(yy[t])) for t in origins for h in range(1, H + 1)]
    return pd.DataFrame(rows, columns=["origin", "h", "target", "fc"])


def attach_actual_yoy(df: pd.DataFrame, inp: Inputs) -> pd.DataFrame:
    head = inp.index[inp.settings.headline]
    yy = 100 * (head / head.shift(12) - 1)
    return df.assign(actual=df.target.map(yy), last=df.origin.map(yy))


# --------------------------------------------------------------------------- tests and metrics
def diebold_mariano(e_model: np.ndarray, e_bench: np.ndarray, h: int) -> tuple[float, float]:
    """DM test on squared-error loss, d = e_model² − e_bench² (negative mean = model better).

    Newey-West (Bartlett) long-run variance with h−1 lags; Harvey-Leybourne-Newbold (1997)
    small-sample correction; two-sided p-value from Student t with n−1 df.
    """
    d = np.asarray(e_model) ** 2 - np.asarray(e_bench) ** 2
    n = len(d)
    dbar = d.mean()
    dc = d - dbar
    lrv = dc @ dc / n
    for k in range(1, h):
        lrv += 2 * (1 - k / h) * (dc[k:] @ dc[:-k]) / n
    if lrv <= 0:
        return float("nan"), float("nan")
    dm = dbar / np.sqrt(lrv / n)
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    stat = dm * hln
    p = 2 * stats.t.sf(abs(stat), df=n - 1)
    return float(stat), float(p)


def headline_metrics(df: pd.DataFrame, rw: pd.DataFrame) -> dict:
    """Metrics for one model at one horizon on a common set of origins with the random walk."""
    m = df.merge(rw[["origin", "h", "fc"]].rename(columns={"fc": "rw"}), on=["origin", "h"]).dropna(subset=["actual"])
    e = m.actual - m.fc
    e_rw = m.actual - m.rw
    h = int(m.h.iloc[0])
    stat, p = diebold_mariano(e.to_numpy(), e_rw.to_numpy(), h) if len(m) > 10 else (np.nan, np.nan)
    moved = np.sign(m.actual - m["last"]) != 0
    direction = float((np.sign(m.fc - m["last"]) == np.sign(m.actual - m["last"]))[moved].mean())
    rmse, rmse_rw = float(np.sqrt((e ** 2).mean())), float(np.sqrt((e_rw ** 2).mean()))
    return {"n": int(len(m)), "rmse": rmse, "mae": float(e.abs().mean()), "rmse_rw": rmse_rw,
            "rmse_ratio_vs_rw": rmse / rmse_rw, "dm_stat": stat, "dm_p": p,
            "bias": float((m.fc - m.actual).mean()), "direction_accuracy": direction}


def select_models(cum: pd.DataFrame, components: list[str], sel_start: str, sel_end: str) -> pd.DataFrame:
    """Apply the pre-committed ladder (D9) on the selection sample of origins."""
    c = cum[(cum.origin >= pd.Timestamp(sel_start)) & (cum.origin <= pd.Timestamp(sel_end))]
    log_rows = []
    for comp in components:
        g = c[c.coicop == comp]
        err = {m: (gm.set_index("origin").actual - gm.set_index("origin").fc) for m, gm in g.groupby("model")}
        common = sorted(set.intersection(*(set(e.index) for e in err.values())))
        err = {m: e.loc[common].to_numpy() for m, e in err.items()}
        mse = {m: float((e ** 2).mean()) for m, e in err.items()}
        current = "SM"
        ladder = [["AR1"], [m for m in err if m not in ("SM", "AR1")]]
        for rung in ladder:
            passed = []
            for cand in rung:
                stat, p = diebold_mariano(err[cand], err[current], H)
                ok = mse[cand] < mse[current] and p < 0.05
                log_rows.append({"coicop": comp, "candidate": cand, "vs": current, "mse_candidate": mse[cand],
                                 "mse_current": mse[current], "dm_stat": stat, "dm_p": p, "accepted": ok,
                                 "n": len(common)})
                if ok:
                    passed.append(cand)
            if passed:
                current = min(passed, key=mse.get)
        log_rows.append({"coicop": comp, "candidate": "SELECTED", "vs": current, "mse_candidate": mse[current],
                         "mse_current": np.nan, "dm_stat": np.nan, "dm_p": np.nan, "accepted": True, "n": len(common)})
    return pd.DataFrame(log_rows)


# --------------------------------------------------------------------------- full run
SUBPERIODS = {"2010-2019": ("2010-01", "2019-12"), "2020-2023": ("2020-01", "2023-12"),
              "2024-now": ("2024-01", "2100-12")}


@dataclass
class BacktestResult:
    comp_fc: pd.DataFrame        # every component forecast, all models
    selection: pd.DataFrame      # the D9 ladder log
    choice: dict[str, str]       # component -> selected model name
    headline: pd.DataFrame       # headline YoY forecasts: model, origin, h, target, fc, actual, last
    metrics: pd.DataFrame        # model x h x sample


def _with_window(spec: fc.ModelSpec, window: int) -> fc.ModelSpec:
    return fc.ModelSpec(spec.name + f"_R{window}", ar=spec.ar, easter=spec.easter, pump=spec.pump, window=window)


def run_backtest(inp: Inputs, first_origin: str, sel_start: str, sel_end: str, rolling: int = 120) -> BacktestResult:
    s = inp.settings
    last = inp.index.index.max()
    origins = list(pd.date_range(first_origin, last, freq="MS"))
    specs = {c: candidate_specs(c) for c in s.components}
    comp = run_components(inp, origins, specs)
    cum = cumulative_errors(comp)
    selection = select_models(cum, s.components, sel_start, sel_end)
    choice = dict(selection[selection.candidate == "SELECTED"][["coicop", "vs"]].to_numpy())

    # D9 step 5: a rolling window replaces the expanding one only under the same DM rule.
    by_name = {c: {sp.name: sp for sp in specs[c]} for c in s.components}
    roll_specs = {c: [_with_window(by_name[c][m], rolling)] for c, m in choice.items()}
    roll = run_components(inp, origins, roll_specs)
    comp = pd.concat([comp, roll], ignore_index=True)
    cum = cumulative_errors(comp)
    sel_rows = []
    for c, m in choice.items():
        rname = f"{m}_R{rolling}"
        g = cum[(cum.coicop == c) & cum.model.isin([m, rname])
                & (cum.origin >= pd.Timestamp(sel_start)) & (cum.origin <= pd.Timestamp(sel_end))]
        w = g.assign(e=g.actual - g.fc).pivot(index="origin", columns="model", values="e").dropna()
        stat, p = diebold_mariano(w[rname].to_numpy(), w[m].to_numpy(), H)
        mse_r, mse_e = float((w[rname] ** 2).mean()), float((w[m] ** 2).mean())
        ok = mse_r < mse_e and p < 0.05
        sel_rows.append({"coicop": c, "candidate": rname, "vs": m, "mse_candidate": mse_r, "mse_current": mse_e,
                         "dm_stat": stat, "dm_p": p, "accepted": ok, "n": len(w)})
        if ok:
            choice[c] = rname
    selection = pd.concat([selection[selection.candidate != "SELECTED"], pd.DataFrame(sel_rows),
                           pd.DataFrame([{"coicop": c, "candidate": "SELECTED", "vs": m, "accepted": True}
                                         for c, m in choice.items()])], ignore_index=True)

    # Headline: bottom-up (selected), all-SM bottom-up, and the four benchmarks.
    rw = random_walk(inp, origins)
    models = {
        "bottom_up": bottom_up(inp, comp, choice),
        "bottom_up_SM": bottom_up(inp, comp, {c: "SM" for c in s.components}),
        "direct_AR": direct_headline(inp, origins, fc.ModelSpec("ARP", ar="aic")),
        "direct_SM": direct_headline(inp, origins, SM),
        "RW": rw,
    }
    head = pd.concat([attach_actual_yoy(df, inp).assign(model=name) for name, df in models.items()], ignore_index=True)
    rw_a = attach_actual_yoy(rw, inp)
    rows = []
    samples = {"full": (first_origin, "2100-12"), "selection": (sel_start, sel_end),
               "holdout": (f"{int(sel_end[:4]) + 1}-01", "2100-12"), **SUBPERIODS}
    for name in models:
        if name == "RW":
            continue
        for h in range(1, H + 1):
            for sname, (a, b) in samples.items():
                m = head[(head.model == name) & (head.h == h) & (head.origin >= pd.Timestamp(a)) & (head.origin <= pd.Timestamp(b))]
                r = rw_a[(rw_a.h == h) & (rw_a.origin >= pd.Timestamp(a)) & (rw_a.origin <= pd.Timestamp(b))]
                if m.actual.notna().sum() > 10:
                    rows.append({"model": name, "h": h, "sample": sname, **headline_metrics(m, r)})
    metrics = pd.DataFrame(rows)
    # Bottom-up vs direct: the comparison the literature speaks to (Hubrich 2005; ECB WP 2501).
    vs = []
    for h in range(1, H + 1):
        for sname, (a, b) in samples.items():
            w = head[(head.h == h) & head.model.isin(["bottom_up", "direct_AR"]) & (head.origin >= pd.Timestamp(a))
                     & (head.origin <= pd.Timestamp(b))].dropna(subset=["actual"])
            e = w.assign(e=w.actual - w.fc).pivot(index="origin", columns="model", values="e").dropna()
            if len(e) > 10:
                vs.append({"model": "bottom_up", "h": h, "sample": sname,
                           "dm_p_vs_direct_AR": diebold_mariano(e.bottom_up.to_numpy(), e.direct_AR.to_numpy(), h)[1]})
    metrics = metrics.merge(pd.DataFrame(vs), on=["model", "h", "sample"], how="left")
    return BacktestResult(comp_fc=comp, selection=selection, choice=choice, headline=head, metrics=metrics)
