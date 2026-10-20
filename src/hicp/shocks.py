"""Shock engine: first-round (and optional second-round) pass-through to euro area* headline YoY.

Assumptions (also shown in the dashboard's assumptions panel):

A1. A scenario is one or more legs. A leg is a shock to the consumer price LEVEL of its components in
    its countries (or euro area-wide), relative to the baseline: L(m) = profile(m) · ln(1 + size/100),
    m = months since the leg's start month; zero before. Legs hitting the same (country, component) cell
    add in logs (they compound on the price level), so nothing is overwritten.
A2. Weights are the effective weights at the origin (Sep 2026), held constant. They are each
    (country, component) cell's share of the euro area* headline basket at Sep 2026 prices:
        W_c,i = country share in EA (country weight × relative price drift since Dec)
                × component share within the country (national effective weight).
    The drift of the weights after the origin and the Jan 2027 weight update are ignored
    (second-order for shocks of this size).
A3. Headline level ratio, shocked / baseline:   R_t = 1 + Σ_c,i W_c,i · (e^{L_c,i,t} − 1) + core term
    YoY impact (pp):                            ΔYoY_t = (1 + π_t/100) · (R_t / R_{t−12} − 1) · 100
    Before the start R = 1, so a permanent shock lifts YoY for 12 months and then drops out (base effect).
A4. Second round (optional, "estimated, uncertain"): the energy price-level deviation of the
    scenario (e, % of the EA energy basket) passes into core prices through the estimated distributed
    lag of core m/m on energy m/m (passthrough.py, chosen regime). The core LEVEL deviation is
        c_t = Σ_{j≤t} Δe_j · C_{min(t−j, K)},   C_k = Σ_{l≤k} γ_l (cumulative impulse response),
    and enters R with the core share (NEIG + services effective weight). An approximate 95% band
    replaces C by its pointwise CI bounds (this treats the bound as common to all horizons).
A5. No behavioural or monetary-policy response, no change to the other components' baselines.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from hicp.chainlink import dec, effective_weights
from hicp.clean import CleanData
from hicp.config import Settings
from hicp.schemas import Leg, Profile, Scenario, ShockBasis, ShockResult

ENERGY = ["FUEL", "ELC_GAS"]
CORE = ["IGD_NNRG", "SERV"]

ASSUMPTIONS = [
    "A1 Each shock leg moves the consumer price level vs baseline along its own profile from its own start month; "
    "legs on the same country and component compound (their log effects add).",
    "A2 Weights: each country × component share of the euro area* basket at origin prices, held constant "
    "(no weight drift, no Jan 2027 reweighting).",
    "A3 YoY impact = (1 + baseline YoY) × (R_t / R_t−12 − 1): a permanent shock lifts YoY for 12 months, then drops out.",
    "A4 Second round (optional, estimated, uncertain): energy → core via a 12-month distributed lag, "
    "regime-specific, with 95% bands; energy treated as exogenous.",
    "A5 No policy or demand response; other components stay at baseline.",
]


def profile_fraction(p: Profile, m: int) -> float:
    """Fraction of the full level shock in month m ≥ 0 after the start."""
    if m < 0:
        return 0.0
    if p.kind == "permanent":
        return 1.0
    if p.kind == "decaying":
        return 0.5 ** (m / p.half_life_months)
    if p.kind == "temporary":
        return 1.0 if m < p.months else 0.0
    if p.kind == "ramp":
        return min(1.0, (m + 1) / p.months)
    fr = p.fractions
    return fr[m] if m < len(fr) else fr[-1]


def _months_since(start: str, month: str) -> int:
    y0, m0 = map(int, start.split("-"))
    y1, m1 = map(int, month.split("-"))
    return (y1 - y0) * 12 + (m1 - m0)


def _cell_shocks(legs: list[Leg], basis: ShockBasis) -> list[tuple[str, str, list[float]]]:
    """Per touched (country, component) cell: the shock's log price-level deviation L(t) for every month.

    Legs that hit the same cell add in logs, i.e. compound on the price level: +10% then +10% = +21%.
    Nothing is overwritten and the order of legs does not matter."""
    cells: dict[tuple[str, str], list[float]] = {}
    for leg in legs:
        lvl = math.log1p(leg.size_pct / 100)
        path = [profile_fraction(leg.profile, _months_since(leg.start, m)) * lvl for m in basis.months]
        for c in leg.countries or basis.countries:
            for i in leg.components:
                cur = cells.setdefault((c, i), [0.0] * len(basis.months))
                for t, v in enumerate(path):
                    cur[t] += v
    return [(c, i, L) for (c, i), L in cells.items()]


def _first_round(legs: list[Leg], basis: ShockBasis) -> tuple[list[float], list[float]]:
    """Headline level effect Σ W·(e^L − 1) and the energy-basket deviation (%) for every month."""
    n = len(basis.months)
    first, energy = [0.0] * n, [0.0] * n
    w_energy = sum(basis.ea_effective_weights[i] for i in basis.energy_components)
    for c, i, L in _cell_shocks(legs, basis):
        w = basis.weight_matrix[c][i]
        for t in range(n):
            x = w * math.expm1(L[t])
            first[t] += x
            if i in basis.energy_components:
                energy[t] += x
    return first, [100 * x / w_energy if w_energy else 0.0 for x in energy]


def simulate(sc: Scenario, basis: ShockBasis) -> ShockResult:
    reg = basis.second_round[sc.second_round_regime]
    first, e_dev = _first_round(sc.legs, basis)

    def core_level(cum: list[float]) -> list[float]:
        out = []
        for t in range(len(e_dev)):
            c = 0.0
            for j in range(t + 1):
                de = e_dev[j] - (e_dev[j - 1] if j > 0 else 0.0)
                c += de * cum[min(t - j, len(cum) - 1)]
            out.append(basis.core_share * c / 100)
        return out

    zero = [0.0] * len(e_dev)
    second = core_level(reg["cumulative"]) if sc.second_round else zero
    second_lo = core_level(reg["ci_low"]) if sc.second_round else zero
    second_hi = core_level(reg["ci_high"]) if sc.second_round else zero

    def dyoy(parts: list[float], t: int) -> float:
        r_t = 1 + parts[t]
        r_12 = 1 + (parts[t - 12] if t >= 12 else 0.0)
        return 100 * basis.growth_factor[t] * (r_t / r_12 - 1)

    total = [first[t] + second[t] for t in range(len(first))]
    d_tot = [dyoy(total, t) for t in range(len(total))]
    d_first = [dyoy(first, t) for t in range(len(first))]
    d_second = [a - b for a, b in zip(d_tot, d_first)]
    band = [[dyoy([first[t] + v[t] for t in range(len(first))], t) for t in range(len(first))]
            for v in (second_lo, second_hi)]
    per_leg = []
    for leg in sc.legs:  # each leg on its own (first round only), for the by-leg table
        f_leg, _ = _first_round([leg], basis)
        per_leg.append([dyoy(f_leg, t) for t in range(len(f_leg))])
    shocked = [None if b is None else b + d for b, d in zip(basis.baseline_yoy, d_tot)]
    k = int(np.argmax(np.abs(d_tot)))
    return ShockResult(scenario=sc, months=basis.months, delta_yoy_pp=d_tot, delta_first_round_pp=d_first,
                       delta_second_round_pp=d_second, delta_total_low_pp=band[0], delta_total_high_pp=band[1],
                       baseline_yoy=basis.baseline_yoy, shocked_yoy=shocked,
                       peak_pp=d_tot[k], peak_month=basis.months[k], leg_first_round_pp=per_leg)


# --------------------------------------------------------------------------- reverse stress test
SOLVER_ITERATIONS = 80          # fixed, so the JS mirror performs exactly the same operations
SIZE_LOW, SIZE_HIGH = -49.9, 199.9  # the Scenario schema's supported range for a level shock, %


def required_point(threshold: float, errors: list[float], p: float) -> float:
    """The point forecast at which P(outcome > threshold) equals p, from the empirical error sample:
    p* = threshold − quantile_{1−p}(errors). Mirrors ``requiredPoint`` in dashboard/shock_engine.js."""
    return float(threshold - np.quantile(np.asarray(errors, dtype=float), 1 - p))


def solve_size(sc: Scenario, basis: ShockBasis, leg_idx: int, month: str, target_yoy: float) -> dict:
    """Size (% on the price level) of leg ``leg_idx`` that makes the shocked headline y/y in ``month``
    equal ``target_yoy``, other legs unchanged.

    The y/y impact is strictly increasing in the size of a leg that has weight and has started by
    ``month``, so bisection over the supported range finds it. If the target lies outside what the
    range can reach (or the leg has no effect in that month), ``feasible`` is False and the reachable
    interval is returned instead. Same algorithm and iteration count as the browser's ``solveSize``."""
    t = basis.months.index(month)
    if basis.baseline_yoy[t] is None:
        raise ValueError(f"no baseline forecast for {month}")

    def at(size: float) -> float:
        legs = [lg.model_copy(update={"size_pct": size}) if k == leg_idx else lg for k, lg in enumerate(sc.legs)]
        return simulate(sc.model_copy(update={"legs": legs}), basis).shocked_yoy[t]

    y_lo, y_hi = at(SIZE_LOW), at(SIZE_HIGH)
    out = {"month": month, "target_yoy": target_yoy, "reach_low": y_lo, "reach_high": y_hi}
    if y_hi - y_lo < 1e-9:
        return out | {"feasible": False, "reason": "no_effect", "size_pct": None}
    if not (y_lo <= target_yoy <= y_hi):
        return out | {"feasible": False, "reason": "out_of_range", "size_pct": None}
    lo, hi = SIZE_LOW, SIZE_HIGH
    for _ in range(SOLVER_ITERATIONS):
        mid = (lo + hi) / 2
        if at(mid) < target_yoy:
            lo = mid
        else:
            hi = mid
    size = (lo + hi) / 2
    return out | {"feasible": True, "reason": None, "size_pct": size, "achieved": at(size)}


def brent_equivalent(fuel_pct: float, basis: ShockBasis) -> float:
    """Inverse of nl_scenario.fuel_from_brent: the Brent change (%) that moves fuel prices by ``fuel_pct``."""
    eps = float(basis.fuel_brent_elasticity["total"])
    return 100 * math.expm1(math.log1p(fuel_pct / 100) / eps)


# --------------------------------------------------------------------------- basis
def weight_matrix(d: CleanData, s: Settings, origin: pd.Timestamp) -> dict[str, dict[str, float]]:
    comps = s.components
    cw = d.country_weights_wide().loc[origin.year]
    tot = d.country_index(s.headline)
    drift = tot.loc[origin] / tot.loc[dec(origin.year - 1)]
    share = (cw * drift).dropna()
    share = share / share.sum()
    out = {}
    for c in s.countries:
        weff = effective_weights(d.index_wide(c), d.weights_wide(c), comps).loc[origin].fillna(0.0)
        out[c] = {i: float(share.get(c, 0.0) * weff[i]) for i in comps}
    return out


def build_basis(d: CleanData, s: Settings, outlook: dict, pt: dict, presets: list[Scenario]) -> ShockBasis:
    origin = pd.Timestamp(outlook["origin"] + "-01")
    months = [f"{m:%Y-%m}" for m in pd.date_range(origin + pd.DateOffset(months=1), dec(origin.year + 1), freq="MS")]
    base = {p["date"]: p["point"] for p in outlook["points"]}
    baseline = [base.get(m) for m in months]
    last = [b for b in baseline if b is not None][-1]
    growth = [1 + (b if b is not None else last) / 100 for b in baseline]
    W = weight_matrix(d, s, origin)
    ea = outlook["effective_weights"]
    check = max(abs(sum(W[c][i] for c in s.countries) - ea[i]) for i in s.components)
    return ShockBasis(
        origin=outlook["origin"], months=months, components=s.components, countries=s.countries,
        weight_matrix=W, ea_effective_weights=ea, baseline_yoy=baseline, growth_factor=growth,
        core_share=float(sum(ea[i] for i in CORE)), energy_components=ENERGY,
        second_round=pt["second_round"], fuel_brent_elasticity=pt["fuel_brent"], break_test=pt["break_test"],
        aggregation_check_max_abs=float(check), presets=presets, assumptions=ASSUMPTIONS)


# --------------------------------------------------------------------------- presets
def make_presets(d: CleanData, s: Settings, pt: dict, origin: pd.Timestamp) -> list[Scenario]:
    fb = pt["fuel_brent"]
    eps, cum = fb["total"], fb["cumulative"]
    brent = 30.0
    fuel_size = 100 * math.expm1(eps * math.log1p(brent / 100))
    fr_share = float(d.weights_wide("FR").at[origin.year, "CP0451"] / d.weights_wide("FR").at[origin.year, "ELC_GAS"])
    tariff = 10.0
    ix = d.index_wide(s.ea)["ELC_GAS"]
    rise_2122 = 100 * (ix.loc["2021-06-01":"2022-12-01"].max() / ix.loc["2021-06-01"] - 1)
    nxt = f"{origin + pd.DateOffset(months=2):%Y-%m}"
    return [
        Scenario(
            name="Oil supply shock (Brent +30%)", components=["FUEL"], size_pct=round(fuel_size, 3),
            profile=Profile(kind="custom", fractions=[round(c / eps, 4) for c in cum]), start=nxt,
            rationale=(f"A supply disruption (e.g. Strait of Hormuz) lifts Brent in EUR by {brent:.0f}% and it stays there. "
                       f"Fuel consumer prices respond with the estimated elasticity {eps:.2f} (HAC s.e. {fb['total_se']:.2f}, "
                       f"{fb['start']}–{fb['end']}): +{fuel_size:.1f}% on the fuel price level, "
                       f"{100 * cum[0] / eps:.0f}% of it in the first month. Elasticity < 1 because excise duty is per litre."),
            mapping=f"FUEL level = (1.30)^{eps:.3f} − 1, lag profile from the estimated distributed lag",
            sources=["FRED DCOILBRENTEU", "ECB EXR USD/EUR", "Eurostat prc_hicp_minr FUEL", "hicp/passthrough.py"]),
        Scenario(
            name="European gas price spike", components=["ELC_GAS"], size_pct=20.0,
            profile=Profile(kind="ramp", months=6), start=nxt,
            rationale=(f"Wholesale gas (TTF) spikes. Retail gas and electricity follow slowly and partially because of "
                       f"regulated tariffs, fixed-term contracts and price caps, so the shock ramps in over 6 months. "
                       f"Size +20% on the retail level, about a quarter of the 2021–22 episode, when euro area "
                       f"electricity, gas and heat prices rose {rise_2122:.0f}% from Jun 2021 to their peak (Eurostat)."),
            mapping="Judgemental: retail ELC_GAS +20% over 6 months (no TTF series in the pipeline)",
            sources=["Eurostat prc_hicp_minr ELC_GAS 2021-2022", "ECB Economic Bulletin boxes on retail energy pass-through"]),
        Scenario(
            name="France regulated electricity tariff +10%", components=["ELC_GAS"], countries=["FR"],
            size_pct=round(tariff * fr_share, 3), profile=Profile(kind="permanent"), start=f"{origin.year + 1}-02",
            rationale=(f"Illustrative +{tariff:.0f}% change in France's regulated electricity tariff (TRVE), which is "
                       f"typically revised on 1 February. Electricity is {100 * fr_share:.1f}% of France's ELC_GAS "
                       f"weight in {origin.year} (Eurostat CP0451 / ELC_GAS), so ELC_GAS in France rises "
                       f"{tariff * fr_share:.2f}%. Assumes the change applies to all households."),
            mapping=f"FR ELC_GAS level = {tariff:.0f}% × electricity share {fr_share:.3f}",
            sources=["Eurostat prc_hicp_iw FR CP0451, ELC_GAS", "Eurostat prc_hicp_cw (FR country weight)"]),
    ]
