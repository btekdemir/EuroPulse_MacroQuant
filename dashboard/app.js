/* Euro area inflation dashboard. Reads only the embedded, schema-validated pipeline outputs. */
(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("dashboard-data").textContent);
  const NL_EX = D.nl_examples || [];
  const L = D.ledger, RN = D.research_note;
  const F = D.forecast, B = D.backtest, V = D.validation, M = D.manifest, S = D.basis, C = D.countries;
  const COMPS = S.components;
  const SLOT = { FUEL: "--s1", ELC_GAS: "--s2", FOOD_P: "--s3", FOOD_NP: "--s4", IGD_NNRG: "--s5", SERV: "--s6" };

  const store = {
    get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };
  let lang = store.get("hicp.lang", "en");
  let theme = store.get("hicp.theme", "auto");
  let activeTab = "overview";
  let trackH = 3;

  // ------------------------------------------------------------------ helpers
  const t = (key, vars) => {
    let s = (D.i18n[lang] && D.i18n[lang][key]) || D.i18n.en[key] || key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v);
    return s;
  };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const nf = (d) => new Intl.NumberFormat(lang === "fr" ? "fr-FR" : "en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmt = (x, d = 1) => (x === null || x === undefined || Number.isNaN(x) ? "–" : nf(d).format(x));
  const pct = (x, d = 1) => fmt(x, d) + (lang === "fr" ? "\u00a0%" : "%");
  const sgn = (x, d = 2) => (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), d);
  const monthLabel = (ym) => {
    const [y, m] = ym.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString(lang === "fr" ? "fr-FR" : "en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
  };
  const toDate = (ym) => ym + "-01";
  const comp = (c) => t("c_" + c);
  const geo = (g) => t("g_" + g);
  const el = (id) => document.getElementById(id);
  const node = (tag, props = {}, text) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") n.className = v; else if (k === "style" || k.includes("-")) n.setAttribute(k, v); else n[k] = v;
    }
    if (text !== undefined) n.textContent = text;
    return n;
  };

  function table(container, headers, rows, numericCols = []) {
    const tb = node("table"), thead = node("thead"), tr = node("tr");
    headers.forEach((h, i) => tr.appendChild(node("th", { class: numericCols.includes(i) ? "num" : "" }, h)));
    thead.appendChild(tr); tb.appendChild(thead);
    const body = node("tbody");
    for (const r of rows) {
      const row = node("tr");
      r.forEach((cell, i) => {
        const td = node("td", { class: numericCols.includes(i) ? "num" : "" });
        if (cell instanceof Node) td.appendChild(cell); else td.textContent = cell;
        row.appendChild(td);
      });
      body.appendChild(row);
    }
    tb.appendChild(body);
    container.replaceChildren(tb);
  }

  function baseLayout(extra = {}) {
    const ink = css("--text-secondary"), grid = css("--grid"), axis = css("--axis");
    const ax = { gridcolor: grid, linecolor: axis, zerolinecolor: axis, tickfont: { color: ink, size: 11 },
      title: { font: { color: ink, size: 12 } }, automargin: true };
    return Object.assign({
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: css("--text-primary"), size: 12 },
      margin: { l: 48, r: 16, t: 8, b: 36 }, hovermode: "x unified",
      hoverlabel: { bgcolor: css("--surface-1"), bordercolor: css("--axis"), font: { color: css("--text-primary") } },
      legend: { orientation: "h", y: -0.16, font: { color: ink, size: 11.5 } },
      xaxis: Object.assign({}, ax), yaxis: Object.assign({ ticksuffix: "" }, ax),
      separators: lang === "fr" ? ", " : ".,",
    }, extra);
  }
  const CFG = { displayModeBar: false, responsive: true };
  const plot = (id, data, layout) => Plotly.react(el(id), data, layout, CFG);

  // ------------------------------------------------------------------ static text
  function applyText() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
    document.querySelectorAll("[data-src]").forEach((n) => { n.textContent = `${t("source")}: ${t(n.dataset.src)}`; });
    document.querySelectorAll(".toggle-table").forEach((b) => {
      b.textContent = el(b.dataset.table).hidden ? t("table_show") : t("table_hide");
    });
    document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    document.querySelectorAll("[data-theme-btn]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeBtn === theme)));
    const idx = (M.vintages.find((v) => v.name === "index_ea") || {}).updated || "";
    el("footer").textContent = t("footer", { vintage: idx.slice(0, 10), commit: M.code_version, run: M.run_at.slice(0, 16).replace("T", " ") + " UTC" });
  }

  // ------------------------------------------------------------------ probabilities (shared threshold)
  let thr = 4.0;
  const ERR3 = F.error_samples["3"];
  const probOf = (point, x) => ShockEngine.probAbove(point, ERR3, x);
  function bindThreshold() {
    document.querySelectorAll("input.thr").forEach((inp) => inp.addEventListener("input", () => {
      const v = Number(inp.value);
      if (!Number.isFinite(v)) return;
      thr = v;
      document.querySelectorAll("input.thr").forEach((o) => { if (o !== inp) o.value = inp.value; });
      renderProb(); if (activeTab === "shocks") renderShock();
    }));
  }
  function renderProb() {
    const dec = monthLabel(last.date);
    el("t-prob").textContent = t("prob_title", { date: dec });
    el("prob-sentence").textContent = t("prob_sentence", { date: dec, thr: fmt(thr, 1), p: fmt(100 * probOf(last.point, thr), 0) });
    el("n-prob").textContent = t("prob_note", { n: ERR3.length });
    table(el("tbl-prob"), [t("prob_col_thr"), t("prob_col_p")],
      [2, 3, 3.5, 4, 4.5, 5].map((x) => [fmt(x, 1) + "%", fmt(100 * probOf(last.point, x), 0) + "%"]), [1]);
  }

  // ------------------------------------------------------------------ research note (numbers verified)
  function renderNote() {
    const card = el("note-card");
    if (!RN) { card.hidden = true; return; }
    const n = RN.notes.find((x) => x.lang === lang);
    card.hidden = false;
    el("note-title").textContent = n ? `${t("note_heading")}: ${n.title}` : t("note_heading");
    const status = el("note-status"), body = el("note-body"), chk = el("note-check"), tog = el("note-toggle");
    if (!n) { status.textContent = t("note_missing"); body.replaceChildren(); chk.replaceChildren(); tog.hidden = true; return; }
    const bits = [n.verified ? t("note_ok", { n: n.numbers.length }) : t("note_rejected"),
      t("note_generated", { model: RN.model, date: RN.generated_at.slice(0, 10), k: RN.facts.length })];
    if (RN.stale) bits.push(t("note_stale"));
    status.textContent = bits.join(" ");
    body.replaceChildren(...(n.verified ? n.body.split(/\n{2,}/).map((p) => node("p", { style: "margin:0 0 8px" }, p)) : []));
    tog.hidden = !n.numbers.length;
    tog.textContent = chk.hidden ? t("note_show") : t("note_hide");
    table(chk, [t("note_col_num"), t("note_col_fact"), t("note_col_val"), t("note_col_ok")],
      n.numbers.map((x) => [x.token, x.fact_label || x.fact_id || "–", x.fact_value === null ? "–" : fmt(x.fact_value, 3), x.ok ? "✓" : "✗"]), [2]);
  }

  // ------------------------------------------------------------------ overview
  const P = F.points, last = P[P.length - 1];
  function renderOverview() {
    const dec = monthLabel(last.date), origin = monthLabel(F.origin);
    const kpi = (id, label, value, sub) => {
      const c = el(id); c.replaceChildren(node("div", { class: "label" }, label), node("div", { class: "value" }, value), node("div", { class: "sub" }, sub));
    };
    const q = last.quantiles;
    kpi("kpi-dec", t("kpi_dec", { date: dec }), pct(last.point),
      t("kpi_band", { lo: fmt(q.q16), hi: fmt(q.q84), lo90: fmt(q.q05), hi90: fmt(q.q95) }));
    kpi("kpi-last", t("kpi_last", { date: origin }), sgn(last.point - F.last_actual_yoy, 2) + " " + t("pp"), `${origin}: ${pct(F.last_actual_yoy)}`);
    kpi("kpi-ecb", t("kpi_ecb"), sgn(last.point - F.ecb_target, 1) + " " + t("pp"), `${pct(last.point)} − ${pct(F.ecb_target)}`);
    kpi("kpi-base", t("kpi_locked", { date: dec }), sgn(last.base_effect_pp) + " " + t("pp"),
      `${t("kpi_locked_note")} · ${t("kpi_momentum", { date: dec })} ${sgn(last.momentum_pp)} ${t("pp")} (${t("kpi_momentum_note")})`);
    el("answer").textContent = t("answer_text", {
      dec: fmt(last.point), date: dec, origin, last: fmt(F.last_actual_yoy), base: sgn(last.base_effect_pp),
      mom: sgn(last.momentum_pp), serv: fmt(last.contributions.SERV, 1), fuel: fmt(last.contributions.FUEL, 1),
    });
    el("t-headline").textContent = t("ch_headline");
    renderProb();
    renderNote();

    const hx = F.history.map((h) => toDate(h.date)), hy = F.history.map((h) => h.yoy);
    const fx = [toDate(F.origin), ...P.map((p) => toDate(p.date))];
    const qs = (k) => [F.last_actual_yoy, ...P.map((p) => p.quantiles[k])];
    const fc = [F.last_actual_yoy, ...P.map((p) => p.point)];
    const acc = css("--accent");
    // The fan and the forecast line are anchored at the last published value (origin) so they join the
    // history, but the anchor is not a forecast: it is hidden from the tooltip, which lists Oct-Dec only.
    const hoverX = fx.slice(1);
    const band = (lo, hi, color, name) => [
      { x: fx, y: qs(lo), mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
      { x: fx, y: qs(hi), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: css(color), name, hoverinfo: "skip" },
      { x: hoverX, y: qs(hi).slice(1), customdata: qs(lo).slice(1), mode: "markers", marker: { size: 1, opacity: 0 },
        showlegend: false, hovertemplate: `${name}: %{customdata:.1f}–%{y:.1f}%<extra></extra>` },
    ];
    plot("p-headline", [
      ...band("q05", "q95", "--band90", t("s_band90")),
      ...band("q16", "q84", "--band68", t("s_band68")),
      { x: hx, y: hy, mode: "lines", name: t("s_actual"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%" },
      { x: fx, y: fc, mode: "lines", line: { color: acc, width: 2, dash: "dot" }, hoverinfo: "skip", showlegend: false },
      { x: hoverX, y: fc.slice(1), mode: "lines+markers", name: t("s_forecast"), line: { color: acc, width: 2, dash: "dot" },
        marker: { size: 8, color: acc, line: { color: css("--surface-1"), width: 2 } }, hovertemplate: "%{y:.2f}%" },
      { x: [hx[0], fx[fx.length - 1]], y: [F.ecb_target, F.ecb_target], mode: "lines", name: t("s_target"),
        line: { color: css("--neutral"), width: 1, dash: "dash" }, hoverinfo: "skip" },
    ], baseLayout({
      yaxis: Object.assign(baseLayout().yaxis, { ticksuffix: "%" }),
      xaxis: Object.assign(baseLayout().xaxis, { range: [`${Number(F.origin.slice(0, 4)) - 3}-01-01`, `${last.date}-20`] }),
      margin: { l: 48, r: 56, t: 8, b: 36 },
      annotations: [{ x: fx[fx.length - 1], y: last.point, text: `<b>${fmt(last.point)}%</b>`, xanchor: "left", xshift: 8,
        showarrow: false, font: { color: css("--text-primary"), size: 13 } }],
    }));
    table(el("tbl-headline"), [t("month"), t("s_forecast"), "q05", "q16", "q84", "q95", t("s_base"), t("s_mom")],
      P.map((p) => [monthLabel(p.date), fmt(p.point, 2), fmt(p.quantiles.q05, 2), fmt(p.quantiles.q16, 2), fmt(p.quantiles.q84, 2),
        fmt(p.quantiles.q95, 2), sgn(p.base_effect_pp), sgn(p.momentum_pp)]), [1, 2, 3, 4, 5, 6, 7]);
  }

  // ------------------------------------------------------------------ drivers
  function renderDrivers() {
    const hist = F.history.slice(-36);
    const xs = [...hist.map((h) => toDate(h.date)), ...P.map((p) => toDate(p.date))];
    const nH = hist.length;
    const traces = COMPS.map((c) => ({
      type: "bar", name: comp(c), x: xs, y: [...hist.map((h) => h.contributions[c]), ...P.map((p) => p.contributions[c])],
      marker: { color: css(SLOT[c]), opacity: xs.map((_, i) => (i < nH ? 1 : 0.5)), line: { color: css("--surface-1"), width: 1 } },
      hovertemplate: "%{y:.2f} " + t("pp"),
    }));
    traces.push({ type: "scatter", mode: "lines", name: t("s_actual") + " / " + t("s_forecast") + " (% y/y)", x: xs,
      y: [...hist.map((h) => h.yoy), ...P.map((p) => p.point)], line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%" });
    plot("p-contrib", traces, baseLayout({ barmode: "relative", bargap: 0.25,
      shapes: [{ type: "rect", xref: "x", yref: "paper", x0: F.origin + "-16", x1: last.date + "-16", y0: 0, y1: 1,
        fillcolor: css("--surface-2"), line: { width: 0 }, layer: "below" }] }));
    table(el("tbl-contrib"), [t("month"), ...COMPS.map(comp), "% y/y"],
      [...hist.slice(-12).map((h) => [monthLabel(h.date), ...COMPS.map((c) => fmt(h.contributions[c], 2)), fmt(h.yoy, 2)]),
        ...P.map((p) => [monthLabel(p.date) + " (f)", ...COMPS.map((c) => fmt(p.contributions[c], 2)), fmt(p.point, 2)])],
      [1, 2, 3, 4, 5, 6, 7]);

    el("t-basemom").textContent = t("ch_basemom", { origin: monthLabel(F.origin) });
    const bx = P.map((p) => monthLabel(p.date));
    plot("p-basemom", [
      { type: "bar", name: t("s_base"), x: bx, y: P.map((p) => p.base_effect_pp), marker: { color: css("--axis") }, hovertemplate: "%{y:+.2f} " + t("pp") },
      { type: "bar", name: t("s_mom"), x: bx, y: P.map((p) => p.momentum_pp), marker: { color: css("--text-secondary") }, hovertemplate: "%{y:+.2f} " + t("pp") },
      { type: "scatter", mode: "markers", name: t("s_change"), x: bx, y: P.map((p) => p.base_effect_pp + p.momentum_pp),
        marker: { symbol: "diamond", size: 11, color: css("--accent"), line: { color: css("--surface-1"), width: 2 } }, hovertemplate: "%{y:+.2f} " + t("pp") },
    ], baseLayout({ barmode: "relative", bargap: 0.45, hovermode: "x unified" }));
    table(el("tbl-basemom"), [t("month"), t("s_base"), t("s_mom"), t("s_change")],
      P.map((p) => [monthLabel(p.date), sgn(p.base_effect_pp), sgn(p.momentum_pp), sgn(p.base_effect_pp + p.momentum_pp)]), [1, 2, 3]);

    el("t-weights").textContent = t("ch_weights", { origin: monthLabel(F.origin) });
    const wy = COMPS.map(comp);
    plot("p-weights", [
      { type: "bar", orientation: "h", name: t("s_official"), y: wy, x: COMPS.map((c) => 100 * F.official_weights[c]),
        marker: { color: css("--axis") }, hovertemplate: "%{x:.1f}%" },
      { type: "bar", orientation: "h", name: t("s_effective"), y: wy, x: COMPS.map((c) => 100 * F.effective_weights[c]),
        marker: { color: css("--text-secondary") }, hovertemplate: "%{x:.1f}%" },
    ], baseLayout({ barmode: "group", bargap: 0.3, hovermode: "y unified", margin: { l: 10, r: 16, t: 8, b: 36 },
      yaxis: Object.assign(baseLayout().yaxis, { autorange: "reversed" }), xaxis: Object.assign(baseLayout().xaxis, { ticksuffix: "%" }) }));
    table(el("tbl-weights"), ["", t("s_official"), t("s_effective")],
      COMPS.map((c) => [comp(c), fmt(100 * F.official_weights[c], 2) + "%", fmt(100 * F.effective_weights[c], 2) + "%"]), [1, 2]);
  }

  // ------------------------------------------------------------------ countries
  function renderCountries() {
    const n = C.dates.length - 1, date = C.dates[n];
    el("t-cbar").textContent = t("ch_country_bar", { date: monthLabel(date) });
    el("n-cbar").textContent = t("ch_country_bar_note", { gap: fmt(C.max_abs_gap_pp, 2) });
    const order = Object.keys(C.contributions).sort((a, b) => (C.contributions[b][n] || 0) - (C.contributions[a][n] || 0));
    plot("p-cbar", [{ type: "bar", orientation: "h", y: order.map(geo), x: order.map((g) => C.contributions[g][n]),
      marker: { color: css("--text-secondary") }, customdata: order.map((g) => C.yoy[g][n]),
      hovertemplate: "%{y}: %{x:.2f} " + t("pp") + " (y/y %{customdata:.1f}%)<extra></extra>" }],
    baseLayout({ hovermode: "closest", margin: { l: 10, r: 16, t: 8, b: 30 }, yaxis: Object.assign(baseLayout().yaxis, { autorange: "reversed" }) }));

    const geos = Object.keys(C.yoy).sort((a, b) => geo(a).localeCompare(geo(b), lang));
    const cols = window.innerWidth < 700 ? 3 : 5, rows = Math.ceil(geos.length / cols);
    const xs = C.dates.map(toDate);
    let lo = Infinity, hi = -Infinity;
    for (const g of geos) for (const v of C.yoy[g]) if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const data = [], ann = [];
    const lay = baseLayout({ grid: { rows, columns: cols, pattern: "independent", xgap: 0.08, ygap: 0.35 }, showlegend: false,
      hovermode: "x", margin: { l: 30, r: 8, t: 18, b: 20 } });
    geos.forEach((g, k) => {
      const ax = k === 0 ? "" : String(k + 1);
      data.push({ x: xs, y: C.ea_yoy, xaxis: "x" + ax, yaxis: "y" + ax, mode: "lines", line: { color: css("--axis"), width: 1.5 }, name: geo("EA"), hovertemplate: "%{y:.1f}%" });
      data.push({ x: xs, y: C.yoy[g], xaxis: "x" + ax, yaxis: "y" + ax, mode: "lines", line: { color: css("--text-primary"), width: 1.5 }, name: geo(g), hovertemplate: "%{y:.1f}%" });
      const base = baseLayout();
      lay["xaxis" + ax] = Object.assign({}, base.xaxis, { showticklabels: false, showgrid: false });
      lay["yaxis" + ax] = Object.assign({}, base.yaxis, { range: [Math.floor(lo), Math.ceil(hi)], tickfont: { size: 9, color: css("--text-muted") }, nticks: 3 });
      ann.push({ text: `${geo(g)} <span style="color:${css("--text-muted")}">${fmt(C.yoy[g][n])}%</span>`, xref: `x${ax} domain`, yref: `y${ax} domain`,
        x: 0, y: 1.18, xanchor: "left", showarrow: false, font: { size: 11, color: css("--text-primary") } });
    });
    lay.annotations = ann;
    el("p-csm").style.height = (rows * 120 + 40) + "px";
    plot("p-csm", data, lay);
  }

  // ------------------------------------------------------------------ shock simulator
  const PROFILES = ["permanent", "decaying", "temporary", "ramp", "custom"];
  const LEG_SLOT = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"];  // the six validated chart colours: max six shocks
  const MAX_LEGS = LEG_SLOT.length;
  let scenario = JSON.parse(JSON.stringify(S.presets[0]));
  let presetIdx = 0;
  let activeLeg = 0;

  const activeShock = () => scenario.legs[activeLeg];
  const newLeg = () => ({ components: ["ELC_GAS"], countries: [], size_pct: 10, profile: { kind: "permanent" }, start: S.months[0] });
  const legLabel = (lg) => `${lg.components.map(comp).join(" + ") || "?"} · ${lg.countries.length ? lg.countries.join("/") : geo("EA")} · ${sgn(lg.size_pct, 1)}%`;

  function buildForm() {
    const comps = el("f-comps"); comps.replaceChildren();
    COMPS.forEach((c) => {
      const lab = node("label"), cb = node("input", { type: "checkbox", value: c });
      cb.addEventListener("change", fromForm);
      lab.append(cb, node("span", { class: "swatch", style: `background:var(${SLOT[c]})` }), node("span", { "data-comp": c }));
      comps.appendChild(lab);
    });
    const cs = el("f-countries"); cs.replaceChildren();
    S.countries.forEach((g) => {
      const lab = node("label"), cb = node("input", { type: "checkbox", value: g });
      cb.addEventListener("change", () => { el("f-allea").checked = !cs.querySelector("input:checked"); fromForm(); });
      lab.append(cb, node("span", {}, g));
      cs.appendChild(lab);
    });
    el("f-allea").addEventListener("change", () => { if (el("f-allea").checked) cs.querySelectorAll("input").forEach((i) => { i.checked = false; }); fromForm(); });
    ["f-size", "f-start", "f-profile", "f-param", "f-second", "f-regime"].forEach((id) => el(id).addEventListener("input", fromForm));
    el("leg-add").addEventListener("click", () => {
      if (scenario.legs.length >= MAX_LEGS) return;
      scenario.legs.push(newLeg()); activeLeg = scenario.legs.length - 1; markCustom(); refreshAll();
    });
    el("leg-del").addEventListener("click", () => {
      if (scenario.legs.length <= 1) return;
      scenario.legs.splice(activeLeg, 1); activeLeg = Math.min(activeLeg, scenario.legs.length - 1); markCustom(); refreshAll();
    });
    ["rev-mode", "rev-month", "rev-y", "rev-p"].forEach((id) => el(id).addEventListener("input", renderReverse));
    el("rev-apply").addEventListener("click", () => {
      if (revSolved === null) return;
      activeShock().size_pct = Math.round(revSolved * 1000) / 1000; markCustom(); refreshAll();
    });
    el("nl-go").addEventListener("click", nlInterpret);
    el("nl-run").addEventListener("click", nlRun);
    el("nl-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); nlInterpret(); } });
    el("sim-export").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json" });
      const a = node("a", { href: URL.createObjectURL(blob), download: "scenario.json" });
      document.body.appendChild(a); a.click(); a.remove();
    });
  }

  function refreshAll() { labelForm(); toForm(); renderLegs(); renderShock(); }

  function renderLegs() {
    const strip = el("leg-strip"); strip.replaceChildren();
    scenario.legs.forEach((lg, k) => {
      const b = node("button", { type: "button" });
      b.append(node("span", { class: "swatch", style: `background:var(${LEG_SLOT[k]})` }), document.createTextNode(`${k + 1}. ${legLabel(lg)}`));
      b.setAttribute("aria-pressed", String(k === activeLeg));
      b.addEventListener("click", () => { activeLeg = k; labelForm(); toForm(); renderLegs(); });
      strip.appendChild(b);
    });
    el("leg-add").disabled = scenario.legs.length >= MAX_LEGS;
    el("leg-del").disabled = scenario.legs.length <= 1;
    el("leg-edit").textContent = scenario.legs.length > 1 ? t("sim_editing", { n: activeLeg + 1 }) : "";
  }

  function labelForm() {
    const lg = activeShock();
    el("f-comps").querySelectorAll("[data-comp]").forEach((s) => { s.textContent = comp(s.dataset.comp); });
    el("f-countries").querySelectorAll("label").forEach((l) => { l.title = geo(l.querySelector("input").value); });
    const st = el("f-start");
    st.replaceChildren(...S.months.map((m) => node("option", { value: m }, monthLabel(m)))); st.value = lg.start;
    const pr = el("f-profile");
    pr.replaceChildren(...PROFILES.filter((p) => p !== "custom" || lg.profile.fractions).map((p) => node("option", { value: p }, t("prof_" + p))));
    pr.value = lg.profile.kind;
    const rg = el("f-regime"), rc = rg.value || scenario.second_round_regime;
    rg.replaceChildren(...["post2020", "pre2020"].map((r) => {
      const s = S.second_round[r];
      return node("option", { value: r }, `${t("regime_" + r)} (${s.start}–${s.end}, 12m: ${fmt(s.total, 3)})`);
    }));
    rg.value = scenario.second_round_regime || rc;
    const presets = el("presets"); presets.replaceChildren();
    S.presets.forEach((p, i) => {
      const b = node("button", { type: "button" }, t("preset_" + i));
      b.setAttribute("aria-pressed", String(i === presetIdx));
      b.addEventListener("click", () => { presetIdx = i; scenario = JSON.parse(JSON.stringify(p)); activeLeg = 0; refreshAll(); });
      presets.appendChild(b);
    });
  }

  function toForm() {
    const lg = activeShock();
    el("f-comps").querySelectorAll("input").forEach((i) => { i.checked = lg.components.includes(i.value); });
    el("f-countries").querySelectorAll("input").forEach((i) => { i.checked = lg.countries.includes(i.value); });
    el("f-allea").checked = lg.countries.length === 0;
    el("f-size").value = lg.size_pct;
    el("f-start").value = lg.start;
    el("f-profile").value = lg.profile.kind;
    el("f-param").value = lg.profile.half_life_months || lg.profile.months || 6;
    el("f-second").checked = scenario.second_round;
    el("f-regime").value = scenario.second_round_regime;
    paramVisibility();
  }

  // ------------------------------------------------------------------ reverse stress test
  let revSolved = null;
  const gasRise2122 = (() => {  // judgemental yardstick quoted in preset 2's rationale: +75% retail energy, Jun 2021 -> Oct 2022
    const m = /(\d+)% from Jun 2021/.exec((S.presets[1] || {}).rationale || ""); return m ? Number(m[1]) : null;
  })();
  function renderReverse() {
    const mode = el("rev-mode"), month = el("rev-month");
    if (!mode.options.length) {
      mode.replaceChildren(node("option", { value: "yoy" }, ""), node("option", { value: "prob" }, ""));
      month.replaceChildren(...S.months.filter((m, i) => S.baseline_yoy[i] !== null).map((m) => node("option", { value: m }, "")));
      month.value = last.date;
    }
    mode.options[0].textContent = t("rev_mode_yoy"); mode.options[1].textContent = t("rev_mode_prob");
    [...month.options].forEach((o) => { o.textContent = monthLabel(o.value); });
    el("w-rev-y").hidden = mode.value !== "yoy"; el("w-rev-p").hidden = mode.value !== "prob";
    const lg = activeShock(), m = month.value;
    let target, goal;
    if (mode.value === "yoy") { target = Number(el("rev-y").value); goal = t("rev_goal_yoy", { month: monthLabel(m), y: fmt(target, 1) }); }
    else {
      const q = Math.min(0.99, Math.max(0.01, Number(el("rev-p").value) / 100));
      target = ShockEngine.requiredPoint(thr, ERR3, q);
      goal = t("rev_goal_prob", { month: monthLabel(m), thr: fmt(thr, 1), p: fmt(100 * q, 0) });
    }
    const out = el("rev-out"), apply = el("rev-apply");
    revSolved = null; apply.hidden = true;
    if (!Number.isFinite(target) || lg.components.length === 0) { out.textContent = ""; return; }
    const r = ShockEngine.solveSize(scenario, S, activeLeg, m, target);
    const baseNote = t("rev_baseline_note", { b: fmt(S.baseline_yoy[S.months.indexOf(m)], 2) });
    if (!r.feasible) {
      out.textContent = r.reason === "no_effect" ? t("rev_none", { month: monthLabel(m) })
        : t("rev_range", { lo: fmt(-49.9, 0), hi: fmt(199.9, 0), month: monthLabel(m), ylo: fmt(r.reach_low, 2), yhi: fmt(r.reach_high, 2) }) + baseNote;
      return;
    }
    let extra = "";
    if (lg.profile.kind === "custom" && lg.components.length === 1 && lg.components[0] === "FUEL") extra += t("rev_brent", { b: sgn(ShockEngine.brentEquivalent(r.size_pct, S), 0) });
    if (gasRise2122 && lg.components.every((c) => c === "ELC_GAS")) extra += t("rev_scale", { x: fmt(Math.abs(r.size_pct) / gasRise2122, 2) });
    const inPlace = ShockEngine.profileFraction(lg.profile, ShockEngine.monthsSince(lg.start, m));
    if (inPlace < 0.995) extra += t("rev_partial", { month: monthLabel(m), f: fmt(100 * inPlace, 0) });
    out.textContent = t("rev_ok", { goal, n: activeLeg + 1, what: legLabel(lg).split(" · ").slice(0, 2).join(" · "), size: sgn(r.size_pct, 1), extra }) + baseNote
      + (mode.value === "prob" ? " " + t("rev_prob_point", { pt: fmt(target, 2) }) : "");
    revSolved = r.size_pct; apply.hidden = false;
  }

  // ------------------------------------------------------------------ natural-language box
  let nlPending = null;
  // Live calls need a server that answers /api/scenario (the Vercel site, or deploy/serve_local.py).
  // Opened from a file or any server without that route, the box falls back to the recorded examples.
  const liveOk = () => /^https?:$/.test(location.protocol);

  function showInterpretation(res, srcLabel) {
    nlPending = res;
    el("nl-lines").replaceChildren(...res.interpretation.map((l) => node("li", {}, l)));
    el("nl-src").textContent = srcLabel;
    el("nl-confirm").hidden = false;
  }

  function renderNL() {
    el("nl-text").placeholder = t("nl_placeholder");
    const ex = el("nl-examples"); ex.replaceChildren();
    NL_EX.forEach((e) => {
      const b = node("button", { type: "button", title: e.text }, e.text.length > 46 ? e.text.slice(0, 44) + "…" : e.text);
      b.addEventListener("click", () => {
        el("nl-text").value = e.text;
        showInterpretation({ scenario: e.scenario, interpretation: e.interpretation }, t("nl_recorded", { model: e.model }));
      });
      ex.appendChild(b);
    });
    if (!liveOk()) el("nl-status").textContent = t("nl_live_off");
    else if (el("nl-status").textContent === t("nl_live_off")) el("nl-status").textContent = "";
  }

  async function nlInterpret() {
    const text = el("nl-text").value.trim();
    if (!text) return;
    if (!liveOk()) { el("nl-status").textContent = t("nl_live_off"); return; }
    el("nl-status").textContent = t("nl_busy"); el("nl-go").disabled = true; el("nl-confirm").hidden = true;
    try {
      const r = await fetch("/api/scenario", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      let body = {}; try { body = await r.json(); } catch (e) { /* non-JSON error page */ }
      if (!r.ok || !body.scenario) {
        el("nl-status").textContent = [404, 405, 501].includes(r.status) ? t("nl_live_off") : (body.error || `${t("nl_failed")} (${r.status})`);
        return;
      }
      el("nl-status").textContent = "";
      showInterpretation(body, t("nl_live", { model: body.model }));
    } catch (e) { el("nl-status").textContent = t("nl_failed"); } finally { el("nl-go").disabled = false; }
  }

  function nlRun() {
    if (!nlPending) return;
    scenario = JSON.parse(JSON.stringify(nlPending.scenario));
    presetIdx = -1; activeLeg = 0;
    refreshAll();
    el("sim-export").scrollIntoView({ block: "nearest" });
  }

  function paramVisibility() {
    const k = el("f-profile").value;
    el("w-param").hidden = !["decaying", "temporary", "ramp"].includes(k);
    el("l-param").textContent = k === "decaying" ? t("sim_halflife") : t("sim_months");
  }

  // Once the user edits anything, the preset's written rationale no longer describes the scenario.
  function markCustom() {
    if (presetIdx >= 0 && JSON.stringify(scenario.legs) === JSON.stringify(S.presets[presetIdx].legs)) return;
    presetIdx = -1;
    Object.assign(scenario, { name: "Custom scenario", sources: ["Dashboard simulator"], mapping: null,
      rationale: "User-defined scenario built in the dashboard (no external mapping). Edit this text before sharing." });
    el("presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
  }

  function fromForm() {
    paramVisibility();
    const lg = activeShock();
    const k = el("f-profile").value, v = Math.max(1, Number(el("f-param").value) || 1);
    const profile = { kind: k };
    if (k === "decaying") profile.half_life_months = v;
    if (k === "temporary" || k === "ramp") profile.months = Math.min(24, Math.round(v));
    if (k === "custom") profile.fractions = lg.profile.fractions || (S.presets.map((p) => p.legs[0].profile.fractions).find(Boolean));
    Object.assign(lg, {
      components: [...el("f-comps").querySelectorAll("input:checked")].map((i) => i.value),
      countries: [...el("f-countries").querySelectorAll("input:checked")].map((i) => i.value),
      size_pct: Number(el("f-size").value) || 0, profile, start: el("f-start").value,
    });
    scenario.second_round = el("f-second").checked;
    scenario.second_round_regime = el("f-regime").value;
    markCustom();
    renderLegs();
    renderShock();
  }

  function renderShock() {
    const none = scenario.legs.some((lg) => lg.components.length === 0);
    el("sim-warn").hidden = !none;
    const r = none ? null : ShockEngine.simulate(scenario, S);
    const kpi = (id, label, value, sub) => el(id).replaceChildren(node("div", { class: "label" }, label), node("div", { class: "value" }, value), node("div", { class: "sub" }, sub || ""));
    const decIdx = S.months.indexOf(last.date);
    if (!r) { ["k-peak", "k-dec", "k-shocked", "k-prob"].forEach((id) => kpi(id, "", "–")); Plotly.purge(el("p-shock")); Plotly.purge(el("p-shockpath")); return; }
    kpi("k-peak", t("sim_peak"), sgn(r.peak_pp) + " " + t("pp"), monthLabel(r.peak_month));
    kpi("k-dec", t("sim_dec", { date: monthLabel(last.date) }), sgn(r.delta_yoy_pp[decIdx]) + " " + t("pp"),
      scenario.second_round ? `${t("s_first")} ${sgn(r.delta_first_round_pp[decIdx])} · ${t("s_second")} ${sgn(r.delta_second_round_pp[decIdx])}`
        : scenario.legs.length > 1 ? t("sim_n_shocks", { n: scenario.legs.length }) : t("s_first"));
    kpi("k-shocked", t("sim_shocked", { date: monthLabel(last.date) }), pct(r.shocked_yoy[decIdx]), `${t("s_baseline")}: ${pct(last.point)}`);
    kpi("k-prob", t("k_prob", { date: monthLabel(last.date), thr: fmt(thr, 1) }), fmt(100 * probOf(r.shocked_yoy[decIdx], thr), 0) + "%",
      `${t("k_prob_sub", { b: fmt(100 * probOf(last.point, thr), 0) })} · ${t("prob_shock_note")}`);

    const xs = r.months.map(toDate);
    const multi = scenario.legs.length > 1;
    const tr = multi
      ? scenario.legs.map((lg, k) => ({ type: "bar", name: `${k + 1}. ${legLabel(lg)}`, x: xs, y: r.leg_first_round_pp[k],
        marker: { color: css(LEG_SLOT[k]), line: { color: css("--surface-1"), width: 1 } }, hovertemplate: "%{y:+.3f} " + t("pp") }))
      : [{ type: "bar", name: t("s_first"), x: xs, y: r.delta_first_round_pp, marker: { color: css("--accent") }, hovertemplate: "%{y:+.3f} " + t("pp") }];
    if (scenario.second_round) {
      tr.push({ type: "bar", name: t("s_second"), x: xs, y: r.delta_second_round_pp, marker: { color: css("--text-muted") }, hovertemplate: "%{y:+.3f} " + t("pp") });
      tr.push({ x: xs, y: r.delta_total_low_pp, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false });
      tr.push({ x: xs, y: r.delta_total_high_pp, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: css("--band68"), name: t("s_band2"), hoverinfo: "skip" });
    }
    if (multi || scenario.second_round) {
      tr.push({ x: xs, y: r.delta_yoy_pp, mode: "lines+markers", name: t("s_total"), line: { color: css("--text-primary"), width: 2 }, marker: { size: 6 }, hovertemplate: "%{y:+.3f} " + t("pp") });
    }
    plot("p-shock", tr, baseLayout({ barmode: "relative", bargap: 0.3 }));

    const hist = F.history.slice(-12);
    const bx = [toDate(F.origin), ...P.map((p) => toDate(p.date))];
    const by = [F.last_actual_yoy, ...P.map((p) => p.point)];
    const sy = [F.last_actual_yoy, ...P.map((p) => r.shocked_yoy[S.months.indexOf(p.date)])];
    plot("p-shockpath", [
      { x: hist.map((h) => toDate(h.date)), y: hist.map((h) => h.yoy), mode: "lines", name: t("s_actual"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%" },
      { x: bx, y: by, mode: "lines+markers", name: t("s_baseline"), line: { color: css("--neutral"), width: 2, dash: "dot" }, marker: { size: 8 }, hovertemplate: "%{y:.2f}%" },
      { x: bx, y: sy, mode: "lines+markers", name: t("s_shocked"), line: { color: css("--accent"), width: 2 }, marker: { size: 8, line: { color: css("--surface-1"), width: 2 } }, hovertemplate: "%{y:.2f}%" },
    ], baseLayout({ yaxis: Object.assign(baseLayout().yaxis, { ticksuffix: "%" }) }));

    const rat = el("sim-rationale"); rat.replaceChildren();
    const nm = presetIdx >= 0 ? t("preset_" + presetIdx) : t("sim_custom");
    rat.append(node("b", {}, `${nm} — ${t("sim_rationale")}: `), document.createTextNode(scenario.rationale));
    if (scenario.mapping) rat.append(node("br"), node("b", {}, t("sim_mapping") + ": "), document.createTextNode(scenario.mapping));
    rat.append(node("br"), node("b", {}, t("sim_sources") + ": "), document.createTextNode(scenario.sources.join("; ")));
    if (lang !== "en") rat.append(node("br"), node("i", {}, t("rationale_lang_note")));
    el("sim-assume").replaceChildren(...S.assumptions.map((a) => node("li", {}, a)));
    el("legs-block").hidden = !multi;
    if (multi) {
      table(el("tbl-legs"), [t("leg_shock"), t("leg_alone_peak"), t("leg_alone_dec", { date: monthLabel(last.date) })],
        scenario.legs.map((lg, k) => {
          const arr = r.leg_first_round_pp[k];
          const pk = arr.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a), 0);
          return [`${k + 1}. ${legLabel(lg)}`, sgn(pk, 3), sgn(arr[decIdx], 3)];
        }), [1, 2]);
    }
    renderReverse();
    table(el("tbl-shock"), [t("month"), t("impact"), t("first_round"), t("second_round")],
      r.months.map((m, i) => [monthLabel(m), sgn(r.delta_yoy_pp[i], 3), sgn(r.delta_first_round_pp[i], 3), sgn(r.delta_second_round_pp[i], 3)]), [1, 2, 3]);
  }

  // ------------------------------------------------------------------ model & validation
  const SAMPLES = ["full", "selection", "holdout", "2010-2019", "2020-2023", "2024-now"];
  const MODELS = ["bottom_up", "direct_AR", "bottom_up_SM", "direct_SM"];
  function renderModel() {
    const sel = el("bt-sample"), cur = sel.value || "full";
    sel.replaceChildren(...SAMPLES.map((s) => node("option", { value: s }, t("sample_" + s)))); sel.value = cur;
    const rows = [];
    for (const m of MODELS) for (let h = 1; h <= 3; h++) {
      const r = B.metrics.find((x) => x.model === m && x.h === h && x.sample === sel.value);
      if (!r) continue;
      const p = (v) => { const s = v === null ? "–" : fmt(v, 3); return v !== null && v < 0.05 ? node("b", { class: "sig" }, s) : s; };
      rows.push([t("m_" + m), String(h), String(r.n), fmt(r.rmse, 2), fmt(r.rmse_rw, 2), fmt(r.rmse_ratio_vs_rw, 2), p(r.dm_p),
        m === "bottom_up" ? p(r.dm_p_vs_direct_AR) : "", sgn(r.bias), fmt(100 * r.direction_accuracy, 0) + "%"]);
    }
    table(el("tbl-bt"), [t("bt_model"), t("bt_h"), "n", t("bt_rmse"), "RMSE RW", t("bt_ratio"), t("bt_dm"), t("bt_dm_direct"), t("bt_bias"), t("bt_dir")], rows, [1, 2, 3, 4, 5, 6, 7, 8, 9]);

    el("t-track").textContent = t("ch_track", { h: trackH });
    el("n-track").textContent = t("ch_track_note", { h: trackH });
    const seg = el("track-h"); seg.replaceChildren();
    [1, 2, 3].forEach((h) => {
      const b = node("button", { type: "button" }, "h = " + h); b.setAttribute("aria-pressed", String(h === trackH));
      b.addEventListener("click", () => { trackH = h; renderModel(); }); seg.appendChild(b);
    });
    const tk = (m) => B.track.filter((x) => x.model === m && x.h === trackH && x.actual !== null);
    const bu = tk("bottom_up"), rw = tk("RW");
    plot("p-track", [
      { x: bu.map((x) => toDate(x.target)), y: bu.map((x) => x.actual), mode: "lines", name: t("s_actual"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%" },
      { x: rw.map((x) => toDate(x.target)), y: rw.map((x) => x.fc), mode: "lines", name: t("m_RW"), line: { color: css("--axis"), width: 1.5 }, hovertemplate: "%{y:.2f}%" },
      { x: bu.map((x) => toDate(x.target)), y: bu.map((x) => x.fc), mode: "lines", name: t("m_bottom_up"), line: { color: css("--accent"), width: 2 }, hovertemplate: "%{y:.2f}%" },
    ], baseLayout({ yaxis: Object.assign(baseLayout().yaxis, { ticksuffix: "%" }) }));

    renderBreak();
    renderLedger();
    table(el("tbl-cov"), [t("cov_sample"), "h", "n", t("cov_in68"), t("cov_in90")],
      F.fan_coverage.filter((c) => c.h === 3).map((c) => [t("sample_" + c.sample), String(c.h), String(c.n), fmt(100 * c.in68, 0) + "%", fmt(100 * c.in90, 0) + "%"]), [1, 2, 3, 4]);
    table(el("tbl-sel"), [t("sel_component"), t("sel_candidate"), t("sel_vs"), t("sel_p"), t("sel_accepted")],
      B.selection_log.map((s) => {
        const sel = s.candidate === "SELECTED";
        return [comp(s.coicop), sel ? node("b", {}, t("sel_selected") + ": " + s.vs) : s.candidate, sel ? "" : s.vs,
          s.dm_p === null || s.dm_p === undefined ? "" : fmt(s.dm_p, 3), sel ? "" : (s.accepted ? t("yes") : t("no"))];
      }), [3]);

    table(el("tbl-val"), [t("val_gate"), t("val_check"), t("val_status"), t("val_result")],
      V.gates.map((g) => {
        const st = node("span", { class: "status st-" + g.status });
        st.append(node("span", { class: "dot", "aria-hidden": "true" }), document.createTextNode(t("st_" + g.status)));
        return [g.gate + (g.critical ? ` (${t("critical")})` : ""), g.name, st, g.message];
      }));
    table(el("tbl-vin"), [t("vin_source"), t("vin_dataset"), t("vin_updated")],
      M.vintages.map((v) => [v.name, v.dataset, v.updated]));
  }

  function renderLedger() {
    el("n-led").textContent = L.verified ? t("led_status_ok", { n: L.n_entries, h: (L.head_hash || "").slice(0, 10) })
      : t("led_status_bad", { p: L.problems.join("; ") });
    if (!L.rows.length) { el("tbl-led").replaceChildren(node("p", { class: "note" }, t("led_empty"))); return; }
    table(el("tbl-led"), [t("led_recorded"), t("led_origin"), t("led_target"), "h", t("led_forecast"), t("led_band"), t("led_rw"),
      t("led_status"), t("led_observed"), t("led_error"), t("led_rw_error")],
    L.rows.map((r) => {
      const st = node("span", { class: "status st-" + (r.status === "final" ? "pass" : r.status === "flash" ? "warn" : "") });
      st.append(node("span", { class: "dot", "aria-hidden": "true" }), document.createTextNode(t("led_" + r.status)));
      return [r.recorded_at.slice(0, 16).replace("T", " ") + " UTC", monthLabel(r.origin), monthLabel(r.target), String(r.h), fmt(r.point, 2),
        `${fmt(r.q16, 2)}–${fmt(r.q84, 2)}`, fmt(r.random_walk, 2), st, r.observed === null ? "–" : fmt(r.observed, 2),
        r.error === null ? "–" : sgn(r.error, 2), r.random_walk_error === null ? "–" : sgn(r.random_walk_error, 2)];
    }), [3, 4, 5, 6, 8, 9, 10]);
  }

  function renderBreak() {
    const bt = S.break_test, c = bt.chow, sw = bt.sup_wald;
    el("n-brk").textContent = t("brk_summary", {
      date: monthLabel(c.break), diff: sgn(c.diff_cumulative, 3), se: fmt(c.diff_se, 3), p: fmt(c.p_cumulative, 3),
      pj: fmt(c.p_joint, 2), sup: fmt(sw.stat, 1), crit: fmt(sw.critical_values["5%"], 2), argmax: monthLabel(sw.argmax),
    });
    const xs = sw.path.map((q) => toDate(q.date));
    plot("p-brk", [
      { x: xs, y: sw.path.map((q) => q.wald), mode: "lines", name: t("brk_wald"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.1f}" },
      { x: [xs[0], xs[xs.length - 1]], y: [sw.critical_values["5%"], sw.critical_values["5%"]], mode: "lines", name: t("brk_crit"),
        line: { color: css("--critical"), width: 1, dash: "dash" }, hoverinfo: "skip" },
      { x: [toDate(c.break)], y: [sw.wald_at_known], mode: "markers", name: t("brk_known", { date: monthLabel(c.break) }),
        marker: { size: 10, color: css("--accent"), line: { color: css("--surface-1"), width: 2 } }, hovertemplate: "%{y:.1f}<extra></extra>" },
    ], baseLayout());
    table(el("tbl-brk-sub"), [t("brk_period"), "n", t("brk_cum"), t("brk_se")],
      bt.subsamples.map((x) => [`${monthLabel(x.start)} – ${monthLabel(x.end)}` + (x.label.includes("excl") ? ` (${t("brk_excl_peak")})` : ""),
        String(x.n), fmt(x.cumulative, 3), fmt(x.se, 3)]), [1, 2, 3]);
    table(el("tbl-brk-sens"), [t("brk_break"), t("brk_pre"), t("brk_post"), t("brk_diff"), "p"],
      bt.sensitivity.map((x) => [monthLabel(x.break), fmt(x.pre_cumulative, 3), fmt(x.post_cumulative, 3), sgn(x.diff, 3), fmt(x.p_cumulative, 3)]), [1, 2, 3, 4]);
  }

  // ------------------------------------------------------------------ wiring
  function renderTab(tab) {
    if (tab === "overview") renderOverview();
    if (tab === "drivers") renderDrivers();
    if (tab === "countries") renderCountries();
    if (tab === "shocks") { refreshAll(); renderNL(); }
    if (tab === "model") renderModel();
  }
  function renderAll() { applyText(); renderTab(activeTab); }

  function setTheme(th) {
    theme = th; store.set("hicp.theme", th);
    if (th === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", th);
    renderAll();
  }

  document.querySelectorAll("[role=tab]").forEach((b) => b.addEventListener("click", () => {
    activeTab = b.dataset.tab;
    document.querySelectorAll("[role=tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    document.querySelectorAll("[role=tabpanel]").forEach((p) => p.classList.toggle("active", p.id === "tab-" + activeTab));
    renderTab(activeTab);
  }));
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => { lang = b.dataset.lang; store.set("hicp.lang", lang); renderAll(); }));
  document.querySelectorAll("[data-theme-btn]").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeBtn)));
  document.querySelectorAll(".toggle-table").forEach((b) => b.addEventListener("click", () => {
    const tb = el(b.dataset.table); tb.hidden = !tb.hidden; b.textContent = tb.hidden ? t("table_show") : t("table_hide");
  }));
  el("bt-sample").addEventListener("change", renderModel);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (theme === "auto") renderAll(); });

  el("note-toggle").addEventListener("click", () => { const c = el("note-check"); c.hidden = !c.hidden; renderNote(); });
  bindThreshold();
  buildForm();
  if (theme !== "auto") document.documentElement.setAttribute("data-theme", theme);
  renderAll();
})();
