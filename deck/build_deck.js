/* EuroPulse deck: five slides, every number read from deck/deck_data.json (made by deck/deck_data.py from the
 * pipeline outputs). Build:
 *   python deck/deck_data.py && NODE_PATH=<dir with pptxgenjs> node deck/build_deck.js
 * Structure follows the brief (section 14): answer first; method and validation; forecast accuracy; shock
 * pass-through; dashboard and next steps. Charts are native PowerPoint charts, so they stay editable. */
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.APPLY_THEME);

const ROOT = path.resolve(__dirname, "..");
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "deck_data.json"), "utf8"));
const LOGO = path.join(ROOT, "docs", "europulse_logo.png");
const SHOT_OVERVIEW = path.join(__dirname, "shot_overview.png");

// ---------------------------------------------------------------- formatting (numbers only from D)
const MINUS = "−";
const fmt = (x, d = 1) => (x < 0 ? MINUS : "") + Math.abs(x).toFixed(d);
const sgn = (x, d = 2) => (Number(x.toFixed(d)) > 0 ? "+" : Number(x.toFixed(d)) < 0 ? MINUS : "") + Math.abs(x).toFixed(d);
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const mlabel = (ym) => `${MON[Number(ym.slice(5, 7)) - 1]} ${ym.slice(2, 4)}`;
const mlong = (ym) => `${MON[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;
const F = D.forecast, B = D.backtest, S = D.shock;
const h3 = B.by_h[2];

// ---------------------------------------------------------------- theme
const THEME = {
  name: "EuroPulse",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0F1B2D", lt1: "FFFFFF", dk2: "14284B", lt2: "EEF3FA",
    accent1: "2A78D6", accent2: "E39B2D", accent3: "5B6B82", accent4: "9DC0EC", accent5: "2E9E6B", accent6: "C2453D",
    hlink: "2A78D6", folHlink: "5B6B82",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.author = "Baris Tekdemir";
pres.title = "EuroPulse: euro area HICP forecast and shock simulation";
pres.subject = `Euro area* headline HICP, ${mlong(D.target)} forecast`;
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333;
const FOOT = `EuroPulse · Source: Eurostat HICP (prc_hicp_minr, prc_hicp_iw, prc_hicp_cw, prc_hicp_ctr), own calculations · data to ${mlong(D.origin)} · run ${D.run_at} (${D.code_version})`;

function footer(dark) {
  return [
    { image: { path: LOGO, x: 0.55, y: 6.93, w: 0.3, h: 0.3 } },
    { text: { text: FOOT, options: { x: 0.95, y: 6.9, w: 10.6, h: 0.36, fontSize: 10, color: dark ? C.background2 : C.accent3, valign: "middle", margin: 0 } } },
  ];
}
pres.defineSlideMaster({
  title: "EP_DARK", background: { color: C.text2 },
  objects: footer(true),
  slideNumber: { x: 12.3, y: 6.9, w: 0.5, h: 0.36, fontSize: 10, color: C.background2, align: "right" },
  placeholders: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 0.45, w: 12.1, h: 0.4, fontSize: 14, color: C.accent4, bold: true, margin: 0 }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.85, w: 12.1, h: 0.95, fontSize: 36, bold: true, color: C.background1, fontFace: THEME.headFontFace, margin: 0, valign: "top" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "EP_LIGHT", background: { color: C.background1 },
  objects: footer(false),
  slideNumber: { x: 12.3, y: 6.9, w: 0.5, h: 0.36, fontSize: 10, color: C.accent3, align: "right" },
  placeholders: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 0.45, w: 12.1, h: 0.4, fontSize: 14, color: C.accent1, bold: true, margin: 0 }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.85, w: 12.1, h: 0.95, fontSize: 34, bold: true, color: C.text2, fontFace: THEME.headFontFace, margin: 0, valign: "top" }, text: "" } },
  ],
});

// ---------------------------------------------------------------- helpers
// Kicker and title fill the layout's placeholders and also carry their geometry and style: LibreOffice (and some
// viewers) do not inherit placeholder positions, and the slide must read the same everywhere.
function heading(slide, kicker, title, dark) {
  slide.addText(kicker, { placeholder: "kicker", x: 0.6, y: 0.45, w: 12.1, h: 0.4, fontSize: 14, bold: true, margin: 0,
    color: dark ? C.accent4 : C.accent1, fontFace: THEME.bodyFontFace, valign: "top" });
  slide.addText(title, { placeholder: "title", x: 0.6, y: 0.85, w: 12.1, h: 0.95, fontSize: dark ? 36 : 34, bold: true, margin: 0,
    color: dark ? C.background1 : C.text2, fontFace: THEME.headFontFace, valign: "top" });
}
const text = (slide, t, o) => slide.addText(t, Object.assign({ isTextBox: true, margin: 0, fontSize: 14, color: C.text1, valign: "top" }, o));
const card = (slide, x, y, w, h, fill, name) => slide.addShape(pres.shapes.ROUNDED_RECTANGLE,
  { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: name });
function stat(slide, x, y, w, big, label, o = {}) {
  text(slide, big, { x, y, w, h: 0.75, fontSize: o.size || 40, bold: true, color: o.color || C.accent1, fontFace: THEME.headFontFace, objectName: "stat " + label });
  text(slide, label, { x, y: y + (o.size ? o.size / 50 : 0.8), w, h: 0.6, fontSize: 13, color: o.label || C.accent3, objectName: "stat label " + label });
}
// a numbered step: number in an accent circle, header, one line under it
function step(slide, n, x, y, w, head, body) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.46, h: 0.46, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `step ${n} badge` });
  text(slide, String(n), { x, y, w: 0.46, h: 0.46, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle" });
  text(slide, head, { x: x + 0.6, y: y - 0.02, w: w - 0.6, h: 0.32, fontSize: 16, bold: true, color: C.text2 });
  text(slide, body, { x: x + 0.6, y: y + 0.32, w: w - 0.6, h: 0.62, fontSize: 13, color: C.accent3 });
}
const chartText = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", legendFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", titleFontFace: "+mn-lt" };

// ================================================================= 1. answer first
pres.addSection({ title: "Answer" });
{
  const s = pres.addSlide({ masterName: "EP_DARK", sectionTitle: "Answer" });
  heading(s, `Euro area* headline HICP · ${mlong(D.target)} forecast (h = 3 from the ${mlong(D.origin)} release)`, `Inflation is seen holding at ${fmt(F.point, 1)}% into December`, true);

  text(s, `${fmt(F.point, 1)}%`, { x: 0.6, y: 2.0, w: 3.6, h: 1.2, fontSize: 72, bold: true, color: C.background1, fontFace: THEME.headFontFace, objectName: "headline number" });
  text(s, `point forecast ${fmt(F.point, 2)}% · ECB target ${fmt(F.ecb_target, 0)}%`, { x: 0.6, y: 3.2, w: 4.6, h: 0.35, fontSize: 14, color: C.accent4 });
  text(s, `68% band ${fmt(F.q16, 1)}–${fmt(F.q84, 1)}% · 90% band ${fmt(F.q05, 1)}–${fmt(F.q95, 1)}%`, { x: 0.6, y: 3.55, w: 4.6, h: 0.35, fontSize: 14, color: C.accent4 });

  const rows = [
    [`${sgn(F.base_effect_pp)} pp`, "base effect: last year's monthly changes leaving the window, known today"],
    [`${sgn(F.momentum_pp)} pp`, "cumulative momentum: new monthly changes to December, forecast"],
    [`${fmt(F.contrib_serv, 2)} / ${fmt(F.contrib_fuel, 2)}`, `pp from services and fuels, the largest contributors (fuel prices ${sgn(F.fuel_yoy, 1)}% y/y)`],
    [`${fmt(F.p_above_4, 0)}%`, "probability that December prints above 4%, from the model's own past errors"],
  ];
  rows.forEach(([v, l], i) => {
    const y = 4.15 + i * 0.62;
    text(s, v, { x: 0.6, y, w: 1.55, h: 0.5, fontSize: 20, bold: true, color: C.accent2, objectName: "driver value " + i });
    text(s, l, { x: 2.2, y: y + 0.04, w: 3.3, h: 0.55, fontSize: 13, color: C.background2, objectName: "driver label " + i });
  });

  // history (24 months) + forecast path with its 68% / 90% bands
  card(s, 5.85, 1.95, 6.88, 4.75, C.background1, "chart card");
  const hist = F.history, path_ = F.path, n = hist.length + path_.length;
  const labels = [...hist.map((h) => mlabel(h.date)), ...path_.map((p) => mlabel(p.date))];
  const pad = (arr, at) => { const a = Array(n).fill(null); arr.forEach((v, i) => { a[at + i] = v; }); return a; };
  const last = hist.length - 1, la = hist[last].yoy;
  const band = (q) => pad([la, ...path_.map((p) => p[q])], last);
  s.addChart(pres.charts.LINE, [
    { name: "Actual", labels, values: pad(hist.map((h) => h.yoy), 0) },
    { name: "Forecast", labels, values: pad([la, ...path_.map((p) => p.point)], last) },
    { name: "68% band", labels, values: band("q84") }, { name: "68% band low", labels, values: band("q16") },
    { name: "90% band", labels, values: band("q95") }, { name: "90% band low", labels, values: band("q05") },
  ], Object.assign({
    x: 6.0, y: 2.05, w: 6.6, h: 4.1, objectName: "headline forecast chart",
    chartColors: [HEX.dk1, HEX.accent1, HEX.accent4, HEX.accent4, "C9DCF4", "C9DCF4"],
    lineSize: 2, lineDataSymbol: "none", displayBlanksAs: "gap",
    lineDash: ["solid", "solid", "dash", "dash", "sysDot", "sysDot"],
    showTitle: true, title: "Headline HICP, % y/y: last 24 months and the forecast fan", titleFontSize: 13, titleColor: HEX.dk2,
    showLegend: false,
    catAxisLabelColor: HEX.accent3, valAxisLabelColor: HEX.accent3, catAxisLabelFontSize: 10, valAxisLabelFontSize: 11,
    catAxisLabelFrequency: 3, valAxisLabelFormatCode: "0.0", valAxisMinVal: 1, valAxisMaxVal: 5.5,
    valGridLine: { color: "E3E8EF", size: 0.5 }, catGridLine: { style: "none" },
  }, chartText));

  text(s, [
    { text: "Actual", options: { bold: true, color: HEX.dk1 } }, { text: "   " },
    { text: "Forecast", options: { bold: true, color: HEX.accent1 } }, { text: "   dashed: 68% band   dotted: 90% band", options: { color: HEX.accent3 } },
  ], { x: 6.25, y: 6.18, w: 6.3, h: 0.35, fontSize: 12, objectName: "chart key" });

  s.addNotes(`Lead with the answer. Euro area* headline HICP is forecast at ${fmt(F.point, 2)}% y/y for ${mlong(D.target)}, three months after the ${mlong(D.origin)} print of ${fmt(F.last_actual, 2)}%. The 68% band is ${fmt(F.q16, 1)} to ${fmt(F.q84, 1)}% and the 90% band ${fmt(F.q05, 1)} to ${fmt(F.q95, 1)}%; both come from the model's own out-of-sample errors, not from model assumptions, which is why the fan is skewed up (the model under-predicted in 2021-22).
Why it barely moves: the base effect takes off ${fmt(-F.base_effect_pp, 2)} pp, because last year's October to December monthly changes drop out of the window, and new momentum adds ${fmt(F.momentum_pp, 2)} pp. The two almost cancel.
What carries the level: services ${fmt(F.contrib_serv, 2)} pp and fuels ${fmt(F.contrib_fuel, 2)} pp, with fuel prices up ${fmt(F.fuel_yoy, 1)}% y/y.
Risk framing: a ${fmt(F.p_above_4, 0)}% chance that December prints above 4%.`);
}

// ================================================================= 2. method and validation
pres.addSection({ title: "Method" });
{
  const s = pres.addSlide({ masterName: "EP_LIGHT", sectionTitle: "Method" });
  heading(s, "Method and validation", "Every number is checked before it is shown", false);
  const st = [
    ["Eurostat API, no manual files", "HICP index 2025 = 100 by COICOP ver.2 component and country, item and country weights, official contributions."],
    [`${D.validation.n_gates} validation gates`, `${D.validation.n_pass} pass, ${D.validation.warn.length} warning (${D.validation.warn.join(", ") || "none"}), ${D.validation.fail.length} failures. A failed critical gate stops the run.`],
    ["Rebuild Eurostat's headline", `Chain-linked Laspeyres, December link: ${D.recon.n_months} months within ${fmt(D.recon.yoy_max_pp, 3)} pp; contributions within ${fmt(D.recon.contrib_max_pp, 3)} pp.`],
    ["Bottom-up forecast", "Six components, each with its own model, aggregated with the weights known at the forecast date."],
    ["Pre-registered tests", `Rules written and committed before results: ${D.rounds.n} model rounds, Diebold-Mariano with Holm correction.`],
    ["Structured outputs", "Schema-validated JSON for every result, a hash-chained forecast ledger, one offline dashboard."],
  ];
  st.forEach(([h, b], i) => step(s, i + 1, 0.6 + (i % 2) * 4.15, 2.05 + Math.floor(i / 2) * 1.35, 3.95, h, b));

  card(s, 9.05, 2.0, 3.68, 4.55, C.background2, "proof card");
  stat(s, 9.35, 2.2, 3.1, `${D.validation.n_pass + D.validation.warn.length}/${D.validation.n_gates}`, "data checks without a failure");
  stat(s, 9.35, 3.65, 3.1, `${fmt(D.recon.yoy_max_pp, 3)} pp`, "largest error rebuilding Eurostat's headline");
  stat(s, 9.35, 5.1, 3.1, `${D.n_python_tests}`, "automated tests (maths, data contracts, engine parity)");

  s.addNotes(`For validation and structured outputs. Nothing is downloaded by hand: the pipeline pulls Eurostat's HICP index, item and country weights and the official contributions through the API, and records the vintage of every pull.
Before any model runs, ${D.validation.n_gates} gates check the data; ${D.validation.n_pass} pass and ${D.validation.warn.join(", ")} is a documented warning, not a failure.
The strongest check is the reconciliation: we rebuild Eurostat's headline from the six components with annual chain-linked Laspeyres weights and a December link. Over ${D.recon.n_months} months the largest gap is ${fmt(D.recon.yoy_max_pp, 3)} pp, and the contributions match Eurostat's within ${fmt(D.recon.contrib_max_pp, 3)} pp. If our arithmetic is right there, the forecast's contributions can be trusted.
Every model rule was written and committed before results existed, and every output is schema-validated JSON. ${D.n_python_tests} automated tests cover the maths and the data contracts.`);
}

// ================================================================= 3. forecast accuracy
pres.addSection({ title: "Accuracy" });
{
  const s = pres.addSlide({ masterName: "EP_LIGHT", sectionTitle: "Accuracy" });
  heading(s, `Forecast accuracy · out of sample, ${B.first_origin.slice(0, 4)}–${B.last_origin.slice(0, 4)}`, `${fmt(100 * (1 - h3.ratio), 0)}% smaller three-month errors than a random walk`, false);

  s.addChart(pres.charts.BAR, [
    { name: "EuroPulse bottom-up", labels: B.by_h.map((r) => `${r.h} month${r.h > 1 ? "s" : ""} ahead`), values: B.by_h.map((r) => r.rmse) },
    { name: "Random walk", labels: B.by_h.map((r) => `${r.h} month${r.h > 1 ? "s" : ""} ahead`), values: B.by_h.map((r) => r.rmse_rw) },
  ], Object.assign({
    x: 0.6, y: 2.0, w: 6.3, h: 4.6, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, objectName: "rmse chart",
    chartColors: [HEX.accent1, HEX.accent3], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    dataLabelFontSize: 12, dataLabelColor: HEX.dk1,
    showTitle: true, title: "Root-mean-squared error of headline y/y, pp", titleFontSize: 13, titleColor: HEX.dk2,
    showLegend: true, legendPos: "b", legendFontSize: 12, legendColor: HEX.accent3,
    catAxisLabelColor: HEX.accent3, valAxisLabelColor: HEX.accent3, catAxisLabelFontSize: 12, valAxisLabelFontSize: 11,
    valAxisLabelFormatCode: "0.0", valGridLine: { color: "E3E8EF", size: 0.5 }, catGridLine: { style: "none" },
  }, chartText));

  stat(s, 7.3, 2.0, 2.6, fmt(h3.ratio, 2), "error ratio vs random walk, 3 months");
  stat(s, 10.1, 2.0, 2.6, fmt(h3.dm_p, 3), `Diebold-Mariano p (${B.n_origins_h3} origins)`);
  text(s, [
    { text: "Same gain in calm and in crisis: ", options: { bold: true, color: C.text2 } },
    { text: `ratio ${fmt(B.ratio_h3["2010-2019"], 2)} in 2010–19, ${fmt(B.ratio_h3["2020-2023"], 2)} in 2020–23, ${fmt(B.ratio_h3["2024-now"], 2)} since 2024.` },
  ], { x: 7.3, y: 3.6, w: 5.4, h: 0.7, fontSize: 14, color: C.accent3 });

  card(s, 7.3, 4.4, 5.43, 2.2, C.background2, "limits card");
  text(s, "Honest limits", { x: 7.55, y: 4.55, w: 5.0, h: 0.35, fontSize: 16, bold: true, color: C.accent6 });
  text(s, [
    { text: `In 2020–23 only ${fmt(B.in68_crisis_h3, 0)}% of outcomes fell inside the 68% band (${fmt(B.in68_calm_h3, 0)}% in 2010–19), and the model under-predicted by ${fmt(-B.bias_crisis_h3, 2)} pp on average.`, options: { breakLine: true } },
    { text: `June 2022: forecast ${fmt(B.june2022.fc, 1)}% from ${mlong(B.june2022.origin)}, outcome ${fmt(B.june2022.actual, 1)}% (random walk ${fmt(B.june2022.rw, 1)}%).`, options: { breakLine: true } },
    { text: `Model frozen after ${D.rounds.n} pre-registered rounds; the ledger now scores it out of sample.` },
  ], { x: 7.55, y: 4.95, w: 5.0, h: 1.6, fontSize: 13, color: C.text1, paraSpaceAfter: 4 });

  s.addNotes(`The benchmark that matters at short horizons is the random walk, "y/y stays where it is", which most inflation models fail to beat. Out of sample over ${B.n_origins_h3} forecast origins, our three-month error is ${fmt(h3.rmse, 2)} pp against ${fmt(h3.rmse_rw, 2)} pp, a ratio of ${fmt(h3.ratio, 2)}. The Diebold-Mariano test (HLN correction, Newey-West) gives p = ${fmt(h3.dm_p, 3)}.
The gain is the same before and after 2020, which makes it less likely to be a crisis accident.
Be upfront about the limits: in 2020-23 only ${fmt(B.in68_crisis_h3, 0)}% of outcomes fell inside the 68% band and the model under-predicted by ${fmt(-B.bias_crisis_h3, 2)} pp on average. In June 2022 it said ${fmt(B.june2022.fc, 1)}% and inflation was ${fmt(B.june2022.actual, 1)}%.
On model choice: there were ${D.rounds.n} rounds, each with its rule fixed and committed first. The adopted variant passed narrowly (p ${fmt(D.rounds.adopted_p, 3)} against a Holm threshold of ${fmt(D.rounds.adopted_threshold, 4)}). The model is now frozen, and the hash-chained ledger is the clean out-of-sample test from here.`);
}

// ================================================================= 4. shock pass-through
pres.addSection({ title: "Shocks" });
{
  const s = pres.addSlide({ masterName: "EP_LIGHT", sectionTitle: "Shocks" });
  heading(s, "Shock pass-through · preset scenario", `A gas price spike would add up to ${sgn(S.peak_pp, 2)} pp to headline`, false);

  const labels = S.months.map(mlabel);
  s.addChart(pres.charts.BAR, [{ name: "Impact on headline y/y, pp", labels, values: S.total_pp }], Object.assign({
    x: 0.6, y: 2.0, w: 7.4, h: 4.6, barDir: "col", barGapWidthPct: 35, objectName: "shock impact chart",
    chartColors: [HEX.accent2], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    dataLabelFontSize: 10, dataLabelColor: HEX.accent3,
    showTitle: true, title: "Impact on euro area* headline inflation, pp of y/y, by month", titleFontSize: 13, titleColor: HEX.dk2,
    showLegend: false, catAxisLabelColor: HEX.accent3, valAxisLabelColor: HEX.accent3, catAxisLabelFontSize: 10, valAxisLabelFontSize: 11,
    valAxisLabelFormatCode: "0.0", valGridLine: { color: "E3E8EF", size: 0.5 }, catGridLine: { style: "none" },
  }, chartText));

  card(s, 8.35, 2.0, 4.38, 1.4, C.background2, "scenario card");
  text(s, "The scenario", { x: 8.6, y: 2.12, w: 4.0, h: 0.32, fontSize: 16, bold: true, color: C.text2 });
  text(s, `Retail electricity & gas ${sgn(S.size_pct, 0)}% across the euro area*, phased in over ${S.ramp_months} months from ${mlong(S.start)}: about a quarter of the 2021–22 rise.`,
    { x: 8.6, y: 2.5, w: 4.0, h: 0.85, fontSize: 13, color: C.text1 });
  stat(s, 8.35, 3.6, 2.1, `${sgn(S.peak_pp, 2)} pp`, `largest impact, ${mlong(S.peak_month)}`, { size: 30 });
  stat(s, 10.6, 3.6, 2.13, `${fmt(S.dec_shocked, 1)}%`, `December instead of ${fmt(F.point, 1)}% (${sgn(S.dec_pp, 2)} pp)`, { size: 30, color: C.accent2 });

  text(s, "Assumptions, always shown", { x: 8.35, y: 4.95, w: 4.38, h: 0.32, fontSize: 14, bold: true, color: C.text2 });
  const A = ["Price-level shock per country × component, on its own profile", "Weights at origin prices, held constant",
    "A permanent shock lifts y/y for 12 months, then drops out", "Second round optional: estimated, regime-dependent lag",
    "No policy or demand response"];
  text(s, A.map((a, i) => ({ text: a, options: { bullet: true, breakLine: i < A.length - 1 } })),
    { x: 8.35, y: 5.3, w: 4.38, h: 1.45, fontSize: 12, color: C.accent3, paraSpaceAfter: 2 });

  s.addNotes(`One preset, with its assumptions on screen. Wholesale gas spikes; retail gas and electricity follow slowly because of regulated tariffs and fixed contracts, so the shock is +${fmt(S.size_pct, 0)}% on the retail level, phased in over ${S.ramp_months} months from ${mlong(S.start)}, about a quarter of the 2021-22 episode.
The engine moves each country and component's price level and re-aggregates with the euro area weights, so the pass-through is exact arithmetic rather than a regression: the impact builds to ${sgn(S.peak_pp, 2)} pp in ${mlong(S.peak_month)}, and December would print ${fmt(S.dec_shocked, 1)}% instead of ${fmt(F.point, 1)}%. Because it is a level shock, it lifts y/y for a year and then drops out as a base effect.
The assumptions (A1 to A5) are always visible next to the result. Second-round effects into core are optional, estimated with a regime-dependent distributed lag, and shown separately because they are uncertain.
For oil, the Brent preset goes through an estimated pass-through to fuel prices of ${fmt(S.brent_elasticity, 2)} (s.e. ${fmt(S.brent_elasticity_se, 2)}); +30% Brent peaks at ${sgn(S.oil_peak_pp, 2)} pp. The simulator also solves backwards: what size of shock takes December to a target.`);
}

// ================================================================= 5. dashboard, innovation, next steps
pres.addSection({ title: "Dashboard" });
{
  const s = pres.addSlide({ masterName: "EP_DARK", sectionTitle: "Dashboard" });
  heading(s, "Dashboard and next steps · EuroPulse, live and offline", "One page to ask, simulate and check", true);

  card(s, 0.6, 2.0, 6.05, 3.95, C.background1, "screenshot frame");
  s.addImage({ path: SHOT_OVERVIEW, x: 0.7, y: 2.1, w: 5.85, h: 3.656, objectName: "dashboard screenshot", altText: "EuroPulse dashboard, Overview page" });
  text(s, "hicpinflationshocksimulator.vercel.app · also one offline HTML file", { x: 0.6, y: 6.05, w: 6.05, h: 0.35, fontSize: 12, color: C.accent4 });

  const cards = [
    ["Ask it anything", "A chatbot answers in EN, FR or Turkish; every number is checked against the page, and it builds and runs scenarios itself."],
    ["Words become shocks", "Describe a shock in a sentence: the language model only fills a validated schema; the engine computes, the reader confirms."],
    ["Solve it backwards", "Reverse stress test: the shock size that takes December to a target or probability."],
    ["Forecasts that keep score", "Pre-registered model rounds and a hash-chained ledger scored as Eurostat publishes."],
  ];
  cards.forEach(([h, b], i) => {
    const x = 6.95 + (i % 2) * 2.94, y = 2.0 + Math.floor(i / 2) * 1.98;
    card(s, x, y, 2.78, 1.82, "1E3A66", "innovation card " + (i + 1));
    text(s, h, { x: x + 0.18, y: y + 0.12, w: 2.45, h: 0.3, fontSize: 15, bold: true, color: C.accent2 });
    text(s, b, { x: x + 0.18, y: y + 0.48, w: 2.45, h: 1.28, fontSize: 12, color: C.background2 });
  });
  text(s, [
    { text: "Next: ", options: { bold: true, color: C.accent2 } },
    { text: "weekly fuel prices, pre-tax energy, country-level gas and electricity, true real-time vintages. Outputs are schema-validated JSON, ready to feed Power BI or a research platform." },
  ], { x: 6.95, y: 6.02, w: 5.78, h: 0.62, fontSize: 12, color: C.background2 });

  s.addNotes(`Everything on the previous slides is in one dashboard, EuroPulse: live on the web and also a single offline HTML file, in English and French, with a guided tour per page.
What is new: a chatbot that answers questions about the page in English, French or Turkish, where every number in the answer is checked against the figure it cites, and that can run a scenario itself, for example "what if gas rises 30% in Germany from November?". Describing a shock in a sentence works the same way: the language model only fills a validated schema, the engine computes, and the reader confirms before anything runs.
The simulator also works backwards: what shock size takes December to a target. And the forecast keeps score: every published forecast goes into a hash-chained ledger and is scored when Eurostat publishes.
Next steps: weekly fuel prices, pre-tax energy prices, country-level gas and electricity, and true real-time vintages. Every output is schema-validated JSON, so the same results can feed Power BI or a research platform without re-computing anything.`);
}

(async () => {
  const out = path.join(__dirname, "deck.pptx");
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("written", out);
})();
