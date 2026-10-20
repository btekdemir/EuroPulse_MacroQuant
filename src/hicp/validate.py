"""Validation gates V1–V9. Each returns a ``GateResult`` (pass / warn / fail + numbers).

Run on every pipeline run. A failed *critical* gate stops the forecast step (``run.py``).
Design rule: gates flag, they never modify data.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from hicp.chainlink import chain_link, exact_contributions, yoy
from hicp.clean import CleanData
from hicp.config import Settings
from hicp.schemas import GateResult, Status, ValidationReport

MAX_DETAILS = 25
ALLOWED_STATUS = {"d", "b", "e", "p", "u", "c", "n", "s", "f", "z"}  # Eurostat flag codes


def _gate(gate: str, name: str, critical: bool, status: Status, message: str,
          metrics: dict | None = None, details: list | None = None) -> GateResult:
    clean = {k: (None if isinstance(v, float) and not np.isfinite(v) else
                 (float(v) if isinstance(v, (np.floating,)) else int(v) if isinstance(v, np.integer) else v))
             for k, v in (metrics or {}).items()}
    return GateResult(gate=gate, name=name, status=status, critical=critical, message=message,
                      metrics=clean, details=(details or [])[:MAX_DETAILS])


def _worst(*statuses: Status) -> Status:
    order = [Status.PASS, Status.WARN, Status.FAIL]
    return max(statuses, key=order.index)


# --------------------------------------------------------------------------- V1
def v1_schema(d: CleanData, s: Settings) -> GateResult:
    problems: list[dict] = []
    expected_cols = {
        "index": {"date", "geo", "coicop", "unit", "value", "status"},
        "item_weights": {"year", "geo", "coicop", "weight"},
        "country_weights": {"year", "geo", "weight"},
        "contributions": {"date", "coicop", "value"},
        "first_release": {"date", "release", "value"},
        "ppi": {"date", "value", "status"},
        "first_release_legacy": {"date", "release", "value"},
    }
    for t, cols in expected_cols.items():
        df = getattr(d, t)
        if set(df.columns) != cols:
            problems.append({"table": t, "issue": f"columns {sorted(df.columns)}"})
        for c in cols & {"value", "weight"}:
            if not pd.api.types.is_float_dtype(df[c]):
                problems.append({"table": t, "issue": f"{c} dtype {df[c].dtype}"})
        if "date" in cols and not pd.api.types.is_datetime64_any_dtype(df["date"]):
            problems.append({"table": t, "issue": "date is not datetime"})
    ea = d.index[d.index.geo == s.ea]
    need = [s.headline] + s.components + s.raw["aggregates"]
    for unit in s.raw["units"]:
        missing = sorted(set(need) - set(ea[ea.unit == unit].coicop))
        if missing:
            problems.append({"table": "index", "issue": f"EA {unit} missing {missing}"})
    critical_count = len(problems)
    ctry = d.index[(d.index.geo != s.ea) & (d.index.unit == "I25")]
    for g in s.countries:
        missing = sorted(set([s.headline] + s.components) - set(ctry[ctry.geo == g].coicop))
        if missing:
            problems.append({"table": "index", "issue": f"{g} I25 missing {missing}"})
    bad_flags = sorted(set(d.index.status.dropna().unique()) - ALLOWED_STATUS)
    if bad_flags:
        problems.append({"table": "index", "issue": f"unknown status flags {bad_flags}"})
    if (d.item_weights.weight < 0).any() or (d.country_weights.weight < 0).any():
        problems.append({"table": "weights", "issue": "negative weights"})
        critical_count += 1
    non_pos_idx = int((d.index[d.index.unit == "I25"].value <= 0).sum())
    if non_pos_idx:
        problems.append({"table": "index", "issue": f"{non_pos_idx} non-positive index values"})
        critical_count += 1
    status = Status.FAIL if critical_count else (Status.WARN if problems else Status.PASS)
    flags = d.index[d.index.geo == s.ea].status.value_counts().to_dict()
    return _gate("V1", "Schema: columns, dtypes, units, codes", True, status,
                 "all tables match the expected schema" if not problems else f"{len(problems)} schema issues",
                 {"n_index_rows": len(d.index), "n_countries": d.index.geo.nunique() - 1,
                  "ea_flag_d": int(flags.get("d", 0)), "ea_flag_b": int(flags.get("b", 0))}, problems)


# --------------------------------------------------------------------------- V2
def v2_continuity(d: CleanData, s: Settings) -> GateResult:
    idx = d.index[d.index.unit == "I25"]
    dups = int(d.index.duplicated(["date", "geo", "coicop", "unit"]).sum())
    gaps, ends = [], {}
    for (g, c), grp in idx.groupby(["geo", "coicop"]):
        full = pd.date_range(grp.date.min(), grp.date.max(), freq="MS")
        n_gap = len(full) - grp.date.nunique()
        if n_gap:
            gaps.append({"geo": g, "coicop": c, "missing_months": n_gap})
        ends[(g, c)] = grp.date.max()
    last = max(ends.values())
    lagging = [{"geo": g, "coicop": c, "last": v.strftime("%Y-%m")} for (g, c), v in ends.items() if v < last]
    ea_problem = dups or any(x["geo"] == s.ea for x in gaps + lagging)
    status = Status.FAIL if ea_problem else (Status.WARN if gaps or lagging else Status.PASS)
    return _gate("V2", "Continuity: no gaps, no duplicates, common last period", True, status,
                 f"last period {last:%Y-%m}; {len(gaps)} series with gaps, {len(lagging)} lagging, {dups} duplicate keys",
                 {"last_period": f"{last:%Y-%m}", "duplicates": dups, "series_with_gaps": len(gaps),
                  "series_lagging": len(lagging), "n_series": len(ends)}, gaps + lagging)


# --------------------------------------------------------------------------- V3
def v3_weights(d: CleanData, s: Settings) -> GateResult:
    tol = s.val["weight_sum_tolerance_per_mille"]
    start = pd.Timestamp(s.raw["chainlink_start"]).year
    rows, worst_ea = [], 0.0
    for geo in [s.ea] + s.countries:
        w = d.weights_wide(geo)
        w = w[w.index >= start].reindex(columns=s.components + ["NRG", "FOOD"])
        w = w.dropna(subset=s.components)
        checks = {"components_sum_1000": w[s.components].sum(axis=1) - 1000,
                  "NRG_eq_FUEL_plus_ELC_GAS": w["NRG"] - w["FUEL"] - w["ELC_GAS"],
                  "FOOD_eq_P_plus_NP": w["FOOD"] - w["FOOD_P"] - w["FOOD_NP"]}
        for name, gap in checks.items():
            gap = gap.dropna()
            if geo == s.ea:
                worst_ea = max(worst_ea, float(gap.abs().max()))
            for yr, v in gap[gap.abs() > tol].items():
                rows.append({"geo": geo, "check": name, "year": int(yr), "gap_per_mille": round(float(v), 3)})
    cw = d.country_weights_wide()
    cw_gap = cw.sum(axis=1) - 1000
    for yr, v in cw_gap[cw_gap.abs() > tol].items():
        rows.append({"geo": "ALL", "check": "country_weights_sum_1000", "year": int(yr), "gap_per_mille": round(float(v), 3)})
    ea_fail = any(r["geo"] in (s.ea, "ALL") for r in rows)
    status = Status.FAIL if ea_fail else (Status.WARN if rows else Status.PASS)
    return _gate("V3", "Weights: components and countries sum to 1000 per mille", True, status,
                 f"EA max gap {worst_ea:.3f} per mille; country weights max gap {cw_gap.abs().max():.3f}",
                 {"ea_max_gap_per_mille": worst_ea, "country_weights_max_gap_per_mille": float(cw_gap.abs().max()),
                  "n_flags": len(rows), "years_checked_from": start}, rows)


# --------------------------------------------------------------------------- V4
def reconcile_headline(d: CleanData, s: Settings) -> pd.DataFrame:
    """Published vs rebuilt (from the six components) euro area* headline: index and YoY."""
    ix = d.index_wide(s.ea)
    rebuilt = chain_link(ix, d.weights_wide(s.ea), s.components, s.raw["chainlink_start"], ix[s.headline])
    pub = ix[s.headline].loc[rebuilt.index]
    full_rebuilt = pd.concat([ix[s.headline][ix.index < rebuilt.index[0]], rebuilt])
    out = pd.DataFrame({"published": pub, "rebuilt": rebuilt,
                        "yoy_published_index": yoy(ix[s.headline]).loc[rebuilt.index],
                        "yoy_rebuilt": yoy(full_rebuilt).loc[rebuilt.index]})
    rch = d.index_wide(s.ea, "RCH_A")[s.headline]
    out["yoy_published_rounded"] = rch.reindex(out.index)
    return out


def v4_reconciliation(d: CleanData, s: Settings) -> GateResult:
    r = reconcile_headline(d, s)
    e_idx = (r.rebuilt - r.published).abs()
    e_yoy = (r.yoy_rebuilt - r.yoy_published_index).dropna().abs()
    match_1dp = float((r.yoy_rebuilt.round(1) == r.yoy_published_rounded).loc[e_yoy.index].mean())
    ok = e_idx.max() <= s.val["reconciliation_index_tol"] and e_yoy.max() <= s.val["reconciliation_yoy_tol_pp"]
    worst = e_yoy.sort_values(ascending=False).head(5)
    return _gate("V4", "Reconciliation: headline rebuilt from 6 components vs published", True,
                 Status.PASS if ok else Status.FAIL,
                 f"index max |err| {e_idx.max():.3f} pts, YoY max |err| {e_yoy.max():.3f}pp over {len(e_yoy)} months",
                 {"n_months": len(e_yoy), "index_max_abs_err": float(e_idx.max()), "index_mean_abs_err": float(e_idx.mean()),
                  "yoy_max_abs_err_pp": float(e_yoy.max()), "yoy_mean_abs_err_pp": float(e_yoy.mean()),
                  "yoy_match_published_1dp_share": match_1dp,
                  "from": f"{r.index[0]:%Y-%m}", "to": f"{r.index[-1]:%Y-%m}"},
                 [{"date": f"{t:%Y-%m}", "yoy_abs_err_pp": round(float(v), 4)} for t, v in worst.items()])


# --------------------------------------------------------------------------- V5
def v5_contributions(d: CleanData, s: Settings) -> GateResult:
    ix = d.index_wide(s.ea)
    ours = exact_contributions(ix, d.weights_wide(s.ea), s.components, s.headline)
    off = d.contributions.pivot(index="date", columns="coicop", values="value")
    common_cols = [c for c in s.components if c in off.columns]
    if not common_cols:
        return _gate("V5", "Contributions vs official prc_hicp_ctr", False, Status.WARN,
                     "no common component codes in prc_hicp_ctr")
    ours_agg = ours.copy()
    ours_agg["NRG"] = ours["FUEL"] + ours["ELC_GAS"]
    ours_agg["FOOD"] = ours["FOOD_P"] + ours["FOOD_NP"]
    cols = [c for c in s.components + ["NRG", "FOOD"] if c in off.columns]
    common = ours_agg.index.intersection(off.index)
    err = (ours_agg.loc[common, cols] - off.loc[common, cols]).abs()
    by_col = err.max()
    stacked = err.stack()
    worst = stacked.sort_values(ascending=False).head(5)
    ok = float(stacked.max()) <= s.val["contributions_tol_pp"]
    return _gate("V5", "Contributions: exact chain-linked formula vs official prc_hicp_ctr", True,
                 Status.PASS if ok else Status.FAIL,
                 f"max |err| {stacked.max():.3f}pp, mean {stacked.mean():.4f}pp over {len(stacked)} observations",
                 {"n_obs": int(len(stacked)), "max_abs_err_pp": float(stacked.max()), "mean_abs_err_pp": float(stacked.mean()),
                  **{f"max_abs_err_{c}": float(v) for c, v in by_col.items()},
                  "from": f"{common.min():%Y-%m}", "to": f"{common.max():%Y-%m}"},
                 [{"date": f"{t:%Y-%m}", "coicop": c, "abs_err_pp": round(float(v), 4)} for (t, c), v in worst.items()])


# --------------------------------------------------------------------------- V6
def rebuild_from_countries(d: CleanData, s: Settings, start: str = "2002-01") -> pd.DataFrame:
    ix = d.country_index(s.headline)
    ea = d.index_wide(s.ea)[s.headline]
    rebuilt = chain_link(ix, d.country_weights_wide(), s.countries, start, ea)
    full = pd.concat([ea[ea.index < rebuilt.index[0]], rebuilt])
    return pd.DataFrame({"published": ea.loc[rebuilt.index], "rebuilt": rebuilt,
                         "yoy_published": yoy(ea).loc[rebuilt.index], "yoy_rebuilt": yoy(full).loc[rebuilt.index]})


def v6_countries(d: CleanData, s: Settings) -> GateResult:
    r = rebuild_from_countries(d, s)
    e = (r.yoy_rebuilt - r.yoy_published).dropna().abs()
    e_idx = (r.rebuilt - r.published).abs()
    ok = e.max() <= s.val["countries_yoy_tol_pp"]
    worst = e.sort_values(ascending=False).head(5)
    return _gate("V6", "Countries → euro area*: 21 national indices × country weights vs published EA", False,
                 Status.PASS if ok else Status.WARN,
                 f"YoY max |err| {e.max():.3f}pp, mean {e.mean():.4f}pp; index max |err| {e_idx.max():.3f} pts",
                 {"n_months": len(e), "yoy_max_abs_err_pp": float(e.max()), "yoy_mean_abs_err_pp": float(e.mean()),
                  "index_max_abs_err": float(e_idx.max())},
                 [{"date": f"{t:%Y-%m}", "yoy_abs_err_pp": round(float(v), 4)} for t, v in worst.items()])


# --------------------------------------------------------------------------- V7
def v7_composition(d: CleanData, s: Settings) -> GateResult:
    """(a) the countries carrying a weight each year are exactly the members that year;
    (b) at each enlargement January, rebuilding with the changing composition tracks the
    published EA m/m, and a fixed composition (pre-enlargement members only) would not."""
    acc = s.raw["accession_year"]
    cw = d.country_weights_wide()
    rows = []
    for yr in cw.index:
        if yr < 1999:
            continue
        have = set(cw.columns[cw.loc[yr].notna() & (cw.loc[yr] > 0)])
        expected = {g for g, a in acc.items() if a <= yr}
        if have != expected:
            rows.append({"year": int(yr), "missing": sorted(expected - have), "unexpected": sorted(have - expected)})
    ix = d.country_index(s.headline)
    ea = d.index_wide(s.ea)[s.headline]
    enlarge = sorted({a for a in acc.values() if a > 2001})
    years = []
    for yr in enlarge:
        dc = pd.Timestamp(f"{yr - 1}-12-01")
        months = ea.index[ea.index.year == yr]
        if dc not in ea.index or yr not in cw.index or not len(months):
            continue
        pub = 100 * (ea[months] / ea[dc] - 1)  # cumulative change since the link month

        def cum(members: list[str]) -> pd.Series:
            w = cw.loc[yr, members] / cw.loc[yr, members].sum()
            return 100 * ((ix.loc[months, members] / ix.loc[dc, members]) * w).sum(axis=1) - 100

        changing = [g for g in s.countries if acc[g] <= yr]
        fixed = [g for g in s.countries if acc[g] < yr]
        e_ch, e_fx = (cum(changing) - pub).abs().max(), (cum(fixed) - pub).abs().max()
        years.append({"year": yr, "new": [g for g in s.countries if acc[g] == yr],
                      "new_weight_per_mille": round(float(cw.loc[yr, [g for g in s.countries if acc[g] == yr]].sum()), 2),
                      "max_err_changing_pp": round(float(e_ch), 4), "max_err_fixed_pp": round(float(e_fx), 4)})
    max_changing = max(y["max_err_changing_pp"] for y in years)
    max_fixed = max(y["max_err_fixed_pp"] for y in years)
    status = Status.FAIL if rows else (Status.PASS if max_changing <= 0.05 else Status.WARN)
    # Honest reading: new members are 0.3-2.5% of the basket, so the composition effect within an
    # enlargement year is small; the membership check is the binding part of this gate.
    return _gate("V7", "Composition: members by year; changing vs fixed composition in enlargement years", False, status,
                 f"membership matches accession dates in all years: {not rows}; in enlargement years the "
                 f"changing composition tracks published EA within {max_changing:.3f}pp (fixed: {max_fixed:.3f}pp)",
                 {"membership_mismatch_years": len(rows), "enlargements_checked": len(years),
                  "max_err_changing_pp": max_changing, "max_err_fixed_pp": max_fixed},
                 rows + years)


# --------------------------------------------------------------------------- V8
def v8_outliers(d: CleanData, s: Settings) -> GateResult:
    """Robust z-score of m/m log changes after removing each calendar month's median
    (HICP is not seasonally adjusted: January/July sales would otherwise flag every year)."""
    ix = d.index_wide(s.ea)[[s.headline] + s.components]
    mom = 100 * np.log(ix).diff()
    mom = mom[mom.index >= pd.Timestamp(s.raw["chainlink_start"])]
    resid = mom - mom.groupby(mom.index.month).transform("median")
    mad = (resid - resid.median()).abs().median() * 1.4826
    z = resid / mad
    flags = z.stack()
    flags = flags[flags.abs() > s.val["outlier_robust_z"]].sort_values(key=abs, ascending=False)
    det = [{"date": f"{t:%Y-%m}", "coicop": c, "robust_z": round(float(v), 1),
            "mom_pct": round(float(mom.at[t, c]), 2)} for (t, c), v in flags.items()]
    return _gate("V8", "Outliers: robust z on seasonally-demeaned m/m (flagged, not dropped)", False,
                 Status.WARN if det else Status.PASS,
                 f"{len(det)} month-component observations beyond |z| > {s.val['outlier_robust_z']}",
                 {"n_flags": len(det), "threshold": s.val["outlier_robust_z"],
                  **{f"n_flags_{c}": int((flags.index.get_level_values(1) == c).sum()) for c in mom.columns}}, det)


# --------------------------------------------------------------------------- V9
def v9_freshness(d: CleanData, s: Settings, vintages: dict[str, str], today: date | None = None) -> GateResult:
    today = today or datetime.now(timezone.utc).date()
    last = d.index[d.index.geo == s.ea].date.max()
    period_end = (last + pd.offsets.MonthEnd(0)).date()
    age = (today - period_end).days
    status = (Status.FAIL if age > s.val["freshness_fail_days"] else
              Status.WARN if age > s.val["freshness_warn_days"] else Status.PASS)
    fls = d.first_release[d.first_release.release == "FLS"].date.max()
    flash_ahead = bool(pd.notna(fls) and fls > last)
    return _gate("V9", "Freshness: last period vs today", True, status,
                 f"last period {last:%Y-%m}, {age} days after its month-end; "
                 f"flash beyond last final release: {flash_ahead}",
                 {"last_period": f"{last:%Y-%m}", "days_since_period_end": age, "today": today.isoformat(),
                  "flash_ahead_of_final": str(flash_ahead), "last_flash": f"{fls:%Y-%m}" if pd.notna(fls) else None,
                  **{f"updated_{k}": v for k, v in vintages.items()}})


# --------------------------------------------------------------------------- runner
GATES: list[Callable[[CleanData, Settings], GateResult]] = [
    v1_schema, v2_continuity, v3_weights, v4_reconciliation, v5_contributions, v6_countries,
    v7_composition, v8_outliers,
]


def run_all(d: CleanData, s: Settings, vintages: dict[str, str]) -> ValidationReport:
    results = []
    for g in GATES:
        try:
            results.append(g(d, s))
        except Exception as exc:  # a crashing gate is a failed gate, not a crashed pipeline
            code = g.__name__.split("_")[0].upper()
            results.append(_gate(code, g.__name__, True, Status.FAIL, f"gate raised {type(exc).__name__}: {exc}"))
    results.append(v9_freshness(d, s, vintages))
    last = d.index[d.index.geo == s.ea].date.max()
    return ValidationReport(run_at=datetime.now(timezone.utc), last_period=f"{last:%Y-%m}", gates=results)
