"""Assemble the dashboard's data layer. Every file goes through its pydantic schema (write_json)."""

from __future__ import annotations

import math

import pandas as pd

from hicp.chainlink import exact_contributions, yoy
from hicp.clean import CleanData
from hicp.config import ROOT, Settings
from hicp.schemas import CountryView, ReconciliationView, TrackPoint, write_json
from hicp.shocks import simulate


def _none(v: float) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def country_view(d: CleanData, s: Settings, years: int = 16) -> CountryView:  # from 2010 (D61)
    ix = d.country_index(s.headline)[s.countries]
    ea = d.index_wide(s.ea)[s.headline]
    cw = d.country_weights_wide()
    frame = ix.join(ea.rename("EA"))
    contrib = exact_contributions(frame, cw, s.countries, "EA")
    last = ea.index.max()
    window = contrib.index[contrib.index >= last - pd.DateOffset(years=years)]
    ea_y = yoy(ea)
    cy = yoy(ix)
    gap = (contrib.loc[window].sum(axis=1) - ea_y.loc[window]).abs().max()
    profiles = {}
    for c in s.countries:
        ixc, wc = d.index_wide(c), d.weights_wide(c)
        con = exact_contributions(ixc, wc, s.components, s.headline).reindex(window)
        cy_c = yoy(ixc[s.headline]).reindex(window)
        tot = ixc[s.headline]
        profiles[c] = {
            "contributions": {k: [_none(con.at[t, k]) for t in window] for k in s.components},
            "max_abs_gap_pp": float((con.sum(axis=1) - cy_c).abs().max()),
            "index": {f"{t:%Y-%m}": float(v) for t, v in tot.loc[last - pd.DateOffset(years=8):last].dropna().items()},
        }
    return CountryView(
        profiles=profiles,
        dates=[f"{t:%Y-%m}" for t in window],
        contributions={c: [_none(contrib.at[t, c]) for t in window] for c in s.countries},
        yoy={c: [_none(cy.at[t, c]) for t in window] for c in s.countries},
        ea_yoy=[float(ea_y[t]) for t in window],
        weights_latest={c: float(cw.at[last.year, c]) for c in s.countries if pd.notna(cw.at[last.year, c])},
        weights_year=int(last.year), max_abs_gap_pp=float(gap))


def track(headline: pd.DataFrame) -> list[TrackPoint]:
    h = headline[headline.model.isin(["bottom_up", "RW", "direct_AR"])]
    return [TrackPoint(model=r.model, origin=f"{r.origin:%Y-%m}", h=int(r.h), target=f"{r.target:%Y-%m}",
                       fc=float(r.fc), actual=_none(r.actual)) for r in h.itertuples()]


def write_shock_outputs(basis, out_dir) -> list:
    write_json(basis, out_dir / "shock_basis.json")
    results = []
    scen_dir = ROOT / "config" / "scenarios"
    for k, sc in enumerate(basis.presets, start=1):
        write_json(sc, scen_dir / f"preset_{k}.json")
        results.append(simulate(sc, basis))
    return results


def reconciliation_view(d: CleanData, s: Settings) -> ReconciliationView:
    """The V4 and V5 checks as monthly series, for the dashboard's reconciliation chart (D52)."""
    from hicp.validate import reconcile_headline
    r = reconcile_headline(d, s).dropna(subset=["yoy_rebuilt", "yoy_published_index"])
    ix = d.index_wide(s.ea)
    ours = exact_contributions(ix, d.weights_wide(s.ea), s.components, s.headline)
    ours["NRG"], ours["FOOD"] = ours["FUEL"] + ours["ELC_GAS"], ours["FOOD_P"] + ours["FOOD_NP"]
    off = d.contributions.pivot(index="date", columns="coicop", values="value")
    cols = [c for c in s.components + ["NRG", "FOOD"] if c in off.columns]
    common = ours.index.intersection(off.index)
    err = (ours.loc[common, cols] - off.loc[common, cols]).abs().max(axis=1).reindex(r.index)
    last = common.max()
    gap = (r.yoy_rebuilt - r.yoy_published_index).abs()
    match = (r.yoy_rebuilt.round(1) == r.yoy_published_rounded).loc[r.yoy_published_rounded.notna()]
    return ReconciliationView(
        dates=[f"{t:%Y-%m}" for t in r.index],
        yoy_published=[_none(v) for v in r.yoy_published_index], yoy_rebuilt=[_none(v) for v in r.yoy_rebuilt],
        yoy_official_1dp=[_none(v) for v in r.yoy_published_rounded], contrib_max_abs_err_pp=[_none(v) for v in err],
        latest_month=f"{last:%Y-%m}",
        latest_contributions={c: (float(ours.at[last, c]), float(off.at[last, c])) for c in cols},
        stats={"n_months": float(len(gap)), "yoy_max_abs_err_pp": float(gap.max()), "yoy_mean_abs_err_pp": float(gap.mean()),
               "match_official_1dp_share": float(match.mean()),
               "contrib_max_abs_err_pp": float(err.max()), "contrib_mean_abs_err_pp": float(err.mean())})
