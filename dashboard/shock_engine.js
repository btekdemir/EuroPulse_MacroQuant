/* In-browser shock engine. A line-for-line mirror of hicp.shocks.simulate (Python).
 * tests/test_shock_engine_parity.py runs both on the same scenarios and requires equality to 1e-12.
 * No DOM access here: pure functions of (scenario, basis). */
(function (root) {
  "use strict";

  function profileFraction(p, m) {
    if (m < 0) return 0;
    switch (p.kind) {
      case "permanent": return 1;
      case "decaying": return Math.pow(0.5, m / p.half_life_months);
      case "temporary": return m < p.months ? 1 : 0;
      case "ramp": return Math.min(1, (m + 1) / p.months);
      default: { const fr = p.fractions; return m < fr.length ? fr[m] : fr[fr.length - 1]; }
    }
  }

  function monthsSince(start, month) {
    const [y0, m0] = start.split("-").map(Number);
    const [y1, m1] = month.split("-").map(Number);
    return (y1 - y0) * 12 + (m1 - m0);
  }

  // Per touched (country, component) cell: log price-level deviation L(t). Legs on the same cell add in logs.
  function cellShocks(legs, basis) {
    const cells = new Map();
    for (const leg of legs) {
      const lvl = Math.log1p(leg.size_pct / 100);
      const path = basis.months.map((m) => profileFraction(leg.profile, monthsSince(leg.start, m)) * lvl);
      const countries = leg.countries && leg.countries.length ? leg.countries : basis.countries;
      for (const c of countries) for (const i of leg.components) {
        const key = c + "|" + i;
        if (!cells.has(key)) cells.set(key, { c, i, L: basis.months.map(() => 0) });
        const cur = cells.get(key).L;
        for (let t = 0; t < path.length; t++) cur[t] += path[t];
      }
    }
    return [...cells.values()];
  }

  function firstRound(legs, basis) {
    const n = basis.months.length;
    const first = new Array(n).fill(0), energy = new Array(n).fill(0);
    let wEnergy = 0;
    for (const i of basis.energy_components) wEnergy += basis.ea_effective_weights[i];
    for (const { c, i, L } of cellShocks(legs, basis)) {
      const w = basis.weight_matrix[c][i];
      const isEnergy = basis.energy_components.includes(i);
      for (let t = 0; t < n; t++) {
        const x = w * Math.expm1(L[t]);
        first[t] += x;
        if (isEnergy) energy[t] += x;
      }
    }
    return [first, energy.map((x) => (wEnergy ? 100 * x / wEnergy : 0))];
  }

  function simulate(sc, basis) {
    const reg = basis.second_round[sc.second_round_regime || "post2020"];
    const [first, eDev] = firstRound(sc.legs, basis);
    const coreLevel = (cum) => eDev.map((_, t) => {
      let c = 0;
      for (let j = 0; j <= t; j++) {
        const de = eDev[j] - (j > 0 ? eDev[j - 1] : 0);
        c += de * cum[Math.min(t - j, cum.length - 1)];
      }
      return basis.core_share * c / 100;
    });
    const zero = eDev.map(() => 0);
    const second = sc.second_round ? coreLevel(reg.cumulative) : zero;
    const secondLo = sc.second_round ? coreLevel(reg.ci_low) : zero;
    const secondHi = sc.second_round ? coreLevel(reg.ci_high) : zero;

    const dyoy = (parts, t) => {
      const rT = 1 + parts[t];
      const r12 = 1 + (t >= 12 ? parts[t - 12] : 0);
      return 100 * basis.growth_factor[t] * (rT / r12 - 1);
    };
    const total = first.map((v, t) => v + second[t]);
    const dTot = total.map((_, t) => dyoy(total, t));
    const dFirst = first.map((_, t) => dyoy(first, t));
    const dSecond = dTot.map((v, t) => v - dFirst[t]);
    const band = [secondLo, secondHi].map((v) => {
      const p = first.map((f, t) => f + v[t]);
      return p.map((_, t) => dyoy(p, t));
    });
    const perLeg = sc.legs.map((leg) => {
      const [f] = firstRound([leg], basis);
      return f.map((_, t) => dyoy(f, t));
    });
    const shocked = basis.baseline_yoy.map((b, t) => (b === null ? null : b + dTot[t]));
    let k = 0;
    for (let t = 1; t < dTot.length; t++) if (Math.abs(dTot[t]) > Math.abs(dTot[k])) k = t;
    return {
      months: basis.months, delta_yoy_pp: dTot, delta_first_round_pp: dFirst, delta_second_round_pp: dSecond,
      delta_total_low_pp: band[0], delta_total_high_pp: band[1], baseline_yoy: basis.baseline_yoy,
      shocked_yoy: shocked, peak_pp: dTot[k], peak_month: basis.months[k], leg_first_round_pp: perLeg,
    };
  }

  // P(outcome > threshold) from the empirical error sample: share of past errors e with point + e > threshold.
  // Mirrors hicp.outlook.prob_above.
  function probAbove(point, errors, threshold) {
    let n = 0;
    for (const e of errors) if (point + e > threshold) n++;
    return errors.length ? n / errors.length : NaN;
  }

  // ---- reverse stress test. Mirrors hicp.shocks.solve_size / required_point (same bisection, same iterations).
  const SOLVER_ITERATIONS = 80, SIZE_LOW = -49.9, SIZE_HIGH = 199.9;

  // Linear-interpolation quantile, identical to numpy.quantile's default.
  function quantile(values, q) {
    const v = [...values].sort((a, b) => a - b);
    const pos = (v.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return v[lo] + (v[hi] - v[lo]) * (pos - lo);
  }
  function requiredPoint(threshold, errors, p) { return threshold - quantile(errors, 1 - p); }

  function solveSize(sc, basis, legIdx, month, targetYoy) {
    const t = basis.months.indexOf(month);
    const at = (size) => {
      const legs = sc.legs.map((lg, k) => (k === legIdx ? Object.assign({}, lg, { size_pct: size }) : lg));
      return simulate(Object.assign({}, sc, { legs }), basis).shocked_yoy[t];
    };
    const yLo = at(SIZE_LOW), yHi = at(SIZE_HIGH);
    const out = { month, target_yoy: targetYoy, reach_low: yLo, reach_high: yHi };
    if (yHi - yLo < 1e-9) return Object.assign(out, { feasible: false, reason: "no_effect", size_pct: null });
    if (!(yLo <= targetYoy && targetYoy <= yHi)) return Object.assign(out, { feasible: false, reason: "out_of_range", size_pct: null });
    let lo = SIZE_LOW, hi = SIZE_HIGH;
    for (let i = 0; i < SOLVER_ITERATIONS; i++) {
      const mid = (lo + hi) / 2;
      if (at(mid) < targetYoy) lo = mid; else hi = mid;
    }
    const size = (lo + hi) / 2;
    return Object.assign(out, { feasible: true, reason: null, size_pct: size, achieved: at(size) });
  }

  function brentEquivalent(fuelPct, basis) {
    const eps = basis.fuel_brent_elasticity.total;
    return 100 * Math.expm1(Math.log1p(fuelPct / 100) / eps);
  }

  // ---- month explanations and the October-print scenario (pure; mirrored in tests against Python)
  const addMonths = (ym, k) => {
    const [y, m] = ym.split("-").map(Number), n = y * 12 + (m - 1) + k;
    return `${Math.floor(n / 12)}-${String((n % 12) + 1).padStart(2, "0")}`;
  };
  const yoyAt = (idx, ym) => 100 * (idx[ym] / idx[addMonths(ym, -12)] - 1);

  // Change in y/y from month t-1 to t, split exactly into momentum (this month's m/m) and base effect
  // (the m/m a year earlier leaving the window). Same algebra as hicp.chainlink.base_momentum with h = 1.
  function explainMonth(idx, ym) {
    const prev = addMonths(ym, -1);
    const need = [ym, prev, addMonths(ym, -12), addMonths(ym, -13)];
    if (need.some((k) => !(k in idx))) return null;
    const mom = Math.log(idx[ym] / idx[prev]);
    const base = Math.log(idx[addMonths(ym, -12)] / idx[addMonths(ym, -13)]);
    const y0 = yoyAt(idx, prev), y1 = yoyAt(idx, ym), dlog = mom - base;
    const scale = Math.abs(dlog) > 1e-12 ? (y1 - y0) / dlog : 100;
    return { month: ym, yoy_prev: y0, yoy: y1, delta_pp: y1 - y0, momentum_pp: scale * mom, base_effect_pp: -scale * base,
             mom_pct: 100 * (idx[ym] / idx[prev] - 1) };
  }

  // If month `first` prints `printYoy` instead of the forecast, keep the forecast's later m/m changes
  // (the surprise persists in the price level) and recompute later y/y. Mechanical, not a re-estimate.
  function conditionalPath(idx, first, printYoy, months) {
    const k = (idx[addMonths(first, -12)] * (1 + printYoy / 100)) / idx[first];
    const out = {};
    for (const m of months) out[m] = 100 * ((idx[m] * k) / idx[addMonths(m, -12)] - 1);
    return out;
  }

  const api = { simulate, profileFraction, monthsSince, probAbove, solveSize, requiredPoint, quantile, brentEquivalent,
                explainMonth, conditionalPath, addMonths };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ShockEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
