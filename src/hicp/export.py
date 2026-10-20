"""Assemble the dashboard's data layer. Every file goes through its pydantic schema (write_json)."""

from __future__ import annotations

import math

import pandas as pd

from hicp.chainlink import exact_contributions, yoy
from hicp.clean import CleanData
from hicp.config import ROOT, Settings
from hicp.schemas import CountryView, TrackPoint, write_json
from hicp.shocks import simulate


def _none(v: float) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def country_view(d: CleanData, s: Settings, years: int = 6) -> CountryView:
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
