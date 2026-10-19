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

  function simulate(sc, basis) {
    const comps = sc.components;
    const countries = sc.countries && sc.countries.length ? sc.countries : basis.countries;
    const lvl = Math.log1p(sc.size_pct / 100);
    let W = 0, wShockEnergy = 0;
    for (const c of countries) for (const i of comps) {
      W += basis.weight_matrix[c][i];
      if (basis.energy_components.includes(i)) wShockEnergy += basis.weight_matrix[c][i];
    }
    let wEnergy = 0;
    for (const i of basis.energy_components) wEnergy += basis.ea_effective_weights[i];
    const reg = basis.second_round[sc.second_round_regime || "post2020"];

    const first = [], eDev = [];
    for (const month of basis.months) {
      const f = profileFraction(sc.profile, monthsSince(sc.start, month));
      const x = Math.expm1(f * lvl);
      first.push(W * x);
      eDev.push(wEnergy ? 100 * wShockEnergy * x / wEnergy : 0);
    }
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
    const shocked = basis.baseline_yoy.map((b, t) => (b === null ? null : b + dTot[t]));
    let k = 0;
    for (let t = 1; t < dTot.length; t++) if (Math.abs(dTot[t]) > Math.abs(dTot[k])) k = t;
    return {
      months: basis.months, delta_yoy_pp: dTot, delta_first_round_pp: dFirst, delta_second_round_pp: dSecond,
      delta_total_low_pp: band[0], delta_total_high_pp: band[1], baseline_yoy: basis.baseline_yoy,
      shocked_yoy: shocked, peak_pp: dTot[k], peak_month: basis.months[k],
    };
  }

  const api = { simulate, profileFraction, monthsSince };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ShockEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
