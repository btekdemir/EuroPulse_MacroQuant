/* Euro area inflation dashboard. Reads only the embedded, schema-validated pipeline outputs. */
(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("dashboard-data").textContent);
  const NL_EX = D.nl_examples || [];
  const L = D.ledger, RN = D.research_note, R2 = D.round2, CAL = D.calibration, RT = D.realtime;
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
  // The sign follows the rounded value, so a tiny change reads "0.00", never "−0.00" or "+0.00".
  const sgn = (x, d = 2) => { const r = Number(Number(x).toFixed(d)); return (r > 0 ? "+" : r < 0 ? "−" : "") + fmt(Math.abs(x), d); };
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
    const ax = { gridcolor: grid, griddash: "dot", linecolor: axis, zerolinecolor: axis, tickfont: { color: ink, size: 11 },
      title: { font: { color: ink, size: 12 } }, automargin: true };
    return Object.assign({
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: css("--text-primary"), size: 12 },
      margin: { l: 48, r: 16, t: 8, b: 36 }, hovermode: "x unified",
      hoverlabel: { bgcolor: css("--surface-1"), bordercolor: css("--axis"), font: { color: css("--text-primary") } },
      legend: { orientation: "h", y: -0.16, font: { color: ink, size: 11.5 } },
      xaxis: Object.assign({}, ax), yaxis: Object.assign({ ticksuffix: "", nticks: 6 }, ax),
      separators: lang === "fr" ? ", " : ".,",
    }, extra);
  }
  const CFG = { displayModeBar: false, responsive: true };
  // Long time-series charts get range buttons (1Y / 3Y / all) above the plot.
  const RANGED = new Set(["p-headline", "p-contrib", "p-ccmp", "p-cp-drivers", "p-track", "p-core"]);
  const plot = (id, data, layout) => {
    if (RANGED.has(id)) {
      layout = Object.assign({}, layout, { margin: Object.assign({}, layout.margin || {}, { t: 34 }) });
      layout.xaxis = Object.assign({}, layout.xaxis, { rangeselector: { x: 0, y: 1.02, yanchor: "bottom",
        bgcolor: css("--surface-2"), activecolor: css("--band68"), bordercolor: css("--border"), borderwidth: 1,
        font: { color: css("--text-primary"), size: 11 },
        buttons: [{ count: 1, step: "year", stepmode: "backward", label: t("rng_1y") },
          { count: 3, step: "year", stepmode: "backward", label: t("rng_3y") }, { step: "all", label: t("rng_all") }] } });
    }
    const out = Plotly.react(el(id), data, layout, CFG);
    if (RANGED.has(id)) {
      const gd = el(id);
      if (!gd._fitY) {
        gd._fitY = true;
        // The y-axis follows the visible dates (D60): a 1Y or 3Y view is not squeezed by the 2022 peak; "All" keeps the full scale.
        gd.on("plotly_relayout", (ev) => {
          if (ev["xaxis.autorange"]) Plotly.relayout(gd, { "yaxis.autorange": true });
          else if (ev["xaxis.range[0]"] !== undefined || ev["xaxis.range"]) fitY(gd);
        });
      }
      if (layout.xaxis && layout.xaxis.range) out.then(() => fitY(gd));
    }
    return out;
  };
  function fitY(gd) {
    const r = gd.layout.xaxis.range.map((x) => new Date(x).getTime());
    let lo = Infinity, hi = -Infinity;
    for (const tr of gd.data) {
      if (!tr.x || !tr.y || tr.visible === "legendonly") continue;
      tr.x.forEach((x, i) => {
        const tx = new Date(x).getTime(), y = tr.y[i];
        if (tx >= r[0] && tx <= r[1] && Number.isFinite(y)) { lo = Math.min(lo, y); hi = Math.max(hi, y); }
      });
    }
    if (!Number.isFinite(lo)) return;
    const pad = Math.max(0.3, 0.12 * (hi - lo));
    Plotly.relayout(gd, { "yaxis.range": [lo - pad, hi + pad] });
  }

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
  // From ~200 past errors a 0% or 100% is "none / all of the past errors", not certainty: show "<1" / ">99".
  const probTxt = (p) => (p >= 0.995 ? ">99" : p <= 0.005 ? "<1" : fmt(100 * p, 0));
  function bindThreshold() {
    document.querySelectorAll("input.thr").forEach((inp) => inp.addEventListener("input", () => {
      const v = Number(inp.value);
      if (!Number.isFinite(v)) return;
      thr = v;
      document.querySelectorAll("input.thr").forEach((o) => { if (o !== inp) o.value = inp.value; });
      renderProb(); renderOct(); if (activeTab === "shocks") renderShock();
    }));
  }
  function renderProb() {
    const dec = monthLabel(last.date);
    el("t-prob").textContent = t("prob_title", { date: dec });
    el("prob-sentence").textContent = t("prob_sentence", { date: dec, thr: fmt(thr, 1), p: probTxt(probOf(last.point, thr)) });
    el("n-prob").textContent = t("prob_note", { n: ERR3.length });
    table(el("tbl-prob"), [t("prob_col_thr"), t("prob_col_p")],
      [2, 3, 3.5, 4, 4.5, 5].map((x) => [fmt(x, 1) + "%", probTxt(probOf(last.point, x)) + "%"]), [1]);
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
  // ------------------------------------------------------------------ what changed since last month
  function renderChanged() {
    const W = D.changed, s = W.surprise, rv = W.revisions;
    el("wc-title").textContent = t("wc_title", { prev: monthLabel(W.previous_origin) });
    const movers = (bc) => Object.entries(bc).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 2)
      .map(([c, v]) => `${comp(c).toLowerCase()} ${sgn(v)}`).join(", ");
    const lastRv = rv[rv.length - 1];
    el("wc-text").textContent = t("wc_surprise", { m: monthLabel(s.target), act: pct(s.actual, 2), fc: pct(s.forecast, 2), prev: monthLabel(W.previous_origin),
      d: sgn(s.total_pp), movers: movers(s.by_component) })
      + (lastRv ? " " + t("wc_revision", { m: monthLabel(lastRv.target), from: pct(lastRv.previous, 2), to: pct(lastRv.current, 2), d: sgn(lastRv.total_pp), movers: movers(lastRv.by_component) }) : "")
      + " " + t("wc_new", { m: monthLabel(last.date), v: pct(last.point, 2) });
    const cols = [{ k: s, lab: t("wc_col_surprise", { m: monthLabel(s.target) }) }, ...rv.map((r) => ({ k: r, lab: t("wc_col_rev", { m: monthLabel(r.target) }) }))];
    const rows = COMPS.map((c) => [comp(c), ...cols.map((x) => sgn(x.k.by_component[c]))]);
    rows.push([t("wc_resid"), ...cols.map((x) => sgn(x.k.total_pp - COMPS.reduce((a, c) => a + x.k.by_component[c], 0)))]);
    rows.push([t("wc_total"), ...cols.map((x) => sgn(x.k.total_pp))]);
    table(el("tbl-wc"), [t("wc_col_comp"), ...cols.map((x) => x.lab)], rows, cols.map((_, i) => i + 1));
    el("wc-note").textContent = t("wc_note", { prev: monthLabel(W.previous_origin) });
    renderRevision();
  }

  // Revision waterfall (D53): from last month's forecast to the outcome / the new forecast, component by component.
  let wcIdx = 0;
  function renderRevision() {
    const W = D.changed, items = [{ k: W.surprise, from: W.surprise.forecast, to: W.surprise.actual, lab: t("wc_pick_surprise", { m: monthLabel(W.surprise.target) }),
      a: t("wc_from_fc", { o: monthLabel(W.previous_origin) }), b: t("wc_to_actual") },
      ...W.revisions.map((r) => ({ k: r, from: r.previous, to: r.current, lab: t("wc_pick_rev", { m: monthLabel(r.target) }),
        a: t("wc_from_fc", { o: monthLabel(W.previous_origin) }), b: t("wc_to_new", { o: monthLabel(W.origin) }) }))];
    wcIdx = Math.min(wcIdx, items.length - 1);
    const seg = el("wc-pick"); seg.replaceChildren(...items.map((it, i) => {
      const b = node("button", { type: "button", "aria-pressed": String(i === wcIdx) }, it.lab);
      b.addEventListener("click", () => { wcIdx = i; renderRevision(); });
      return b;
    }));
    const it = items[wcIdx], bc = it.k.by_component;
    const steps = COMPS.map((c) => [comp(c), bc[c]]);
    steps.push([t("wc_resid"), it.to - it.from - COMPS.reduce((s, c) => s + bc[c], 0)]);
    const x = [it.a, ...steps.map((s) => s[0]), it.b], y = [it.from, ...steps.map((s) => s[1]), it.to];
    floatBridge("p-revision", { lab: it.a, v: it.from },
      steps.map((s, i) => ({ lab: s[0], v: s[1], color: i < COMPS.length ? SLOT[COMPS[i]] : "--neutral" })), { lab: it.b, v: it.to });
  }

  // ------------------------------------------------------------------ beat the model (D51)
  // Readers post their own guess for the target month; the model's is the recorded forecast. When Eurostat has
  // published the month (a later run), every guess is scored against it. Shared on a site with a store, else local.
  const BM_KEY = "hicp.guess";
  let bmShared = null, bmBound = false;
  const bmLocal = () => { try { return JSON.parse(localStorage.getItem(BM_KEY) || "null"); } catch (e) { return null; } };
  async function bmLoad() {
    if (!liveOk()) { bmShared = { shared: false, guesses: [] }; return; }
    try { const r = await fetch("/api/guess"); bmShared = r.ok ? await r.json() : { shared: false, guesses: [] }; }
    catch (e) { bmShared = { shared: false, guesses: [] }; }
  }
  function renderBeat() {
    const tgt = last.date, actualRow = F.history.find((h) => h.date === tgt), actual = actualRow ? actualRow.yoy : null;
    el("bm-title").textContent = t("bm_title", { m: monthLabel(tgt) });
    el("bm-intro").textContent = t("bm_intro", { m: monthLabel(tgt), v: pct(last.point, 2), lo: fmt(last.quantiles.q16, 1), hi: fmt(last.quantiles.q84, 1) });
    el("bm-name").placeholder = t("bm_name_ph");
    const mine = bmLocal();
    const list = ((bmShared && bmShared.guesses) || []).map((g) => Object.assign({}, g));
    if (mine && !list.some((g) => g.name === mine.name && Math.abs(g.value - mine.value) < 1e-9)) list.push(Object.assign({ local: true }, mine));
    const rows = [{ name: t("bm_model"), value: last.point, model: true }, ...list];
    if (actual !== null) rows.forEach((r) => { r.err = Math.abs(r.value - actual); });
    rows.sort((a, b) => (actual !== null ? a.err - b.err : 0));
    const q = last.quantiles;
    const tr = [
      { x: [q.q05, q.q95], y: [0, 0], mode: "lines", line: { color: css("--band90"), width: 18 }, name: t("s_band90"), hoverinfo: "skip" },
      { x: [q.q16, q.q84], y: [0, 0], mode: "lines", line: { color: css("--band68"), width: 18 }, name: t("s_band68"), hoverinfo: "skip" },
      { x: [last.point], y: [0], mode: "markers", name: t("bm_model"), marker: { symbol: "diamond", size: 14, color: css("--accent"), line: { color: css("--surface-1"), width: 2 } },
        hovertemplate: `${t("bm_model")}: %{x:.2f}%<extra></extra>` },
      { x: list.map((g) => g.value), y: list.map((_, i) => 0.28 + 0.1 * ((i * 7) % 5) / 4), mode: "markers", name: t("bm_guesses"), text: list.map((g) => g.name),
        marker: { size: 10, color: css("--s2"), line: { color: css("--surface-1"), width: 1.5 } }, hovertemplate: "%{text}: %{x:.2f}%<extra></extra>" },
    ];
    const shapes = actual !== null ? [{ type: "line", x0: actual, x1: actual, yref: "paper", y0: 0, y1: 1, line: { color: css("--text-primary"), width: 2 } }] : [];
    const xs = [q.q05, q.q95, ...list.map((g) => g.value), ...(actual !== null ? [actual] : [])];
    plot("p-guess", tr, baseLayout({ hovermode: "closest", margin: { l: 16, r: 16, t: 8, b: 36 }, shapes,
      yaxis: Object.assign(baseLayout().yaxis, { visible: false, range: [-0.3, 0.6] }),
      xaxis: Object.assign(baseLayout().xaxis, { ticksuffix: "%", range: [Math.min(...xs) - 0.3, Math.max(...xs) + 0.3] }) }));
    table(el("tbl-guess"), [t("bm_col_rank"), t("bm_col_name"), t("bm_col_guess"), actual !== null ? t("bm_col_err") : t("bm_col_when")],
      rows.map((r, i) => [actual !== null ? String(i + 1) : "–", r.model ? `${r.name} ★` : r.name + (r.local ? ` (${t("bm_local")})` : ""), pct(r.value, 2),
        actual !== null ? fmt(r.err, 2) : (r.model ? monthLabel(F.origin) : (r.at || "").slice(0, 10))]), [2, 3]);
    el("bm-note").textContent = (actual !== null ? t("bm_scored", { m: monthLabel(tgt), a: pct(actual, 2) }) : t("bm_pending", { m: monthLabel(tgt) }))
      + " " + (bmShared && bmShared.shared ? t("bm_shared", { n: list.length }) : t("bm_localonly"));
    if (!bmBound) {
      el("bm-go").addEventListener("click", bmSubmit);
      el("bm-value").addEventListener("keydown", (e) => { if (e.key === "Enter") bmSubmit(); });
      bmBound = true;
    }
  }
  async function bmSubmit() {
    const name = el("bm-name").value.trim().slice(0, 40), value = Number(el("bm-value").value);
    if (!name || !el("bm-value").value || !Number.isFinite(value) || value < -5 || value > 15) { el("bm-status").textContent = t("bm_invalid"); return; }
    const g = { name, value: Math.round(value * 100) / 100, at: new Date().toISOString().slice(0, 16) + "Z" };
    try { localStorage.setItem(BM_KEY, JSON.stringify(g)); } catch (e) { /* this browser only, if at all */ }
    if (liveOk() && bmShared && bmShared.shared) {
      el("bm-go").disabled = true;
      const { r, body } = await apiPost("/api/guess", { name: g.name, value: g.value });
      el("bm-go").disabled = false;
      el("bm-status").textContent = r.ok ? t("bm_saved_shared") : (r.status === 0 || r.status >= 500 ? t("bm_saved_local") : body.error || t("bm_saved_local"));
      if (r.ok) await bmLoad();
    } else el("bm-status").textContent = t("bm_saved_local");
    renderBeat();
  }

  function renderRiskLine() {
    const k = S.months.indexOf(last.date);
    const best = S.presets.map((p, i) => ({ i, p, r: ShockEngine.simulate(p, S) })).sort((a, b) => Math.abs(b.r.peak_pp) - Math.abs(a.r.peak_pp))[0];
    const line = el("risk-line"); line.replaceChildren(t("risk_line", { name: best.p.name, peak: sgn(best.r.peak_pp), m: monthLabel(best.r.peak_month), dec: pct(best.r.shocked_yoy[k], 1) }) + " ");
    const go = node("button", { type: "button", class: "linkbtn" }, t("risk_open"));
    go.addEventListener("click", () => { showTab("shocks"); el("presets").querySelectorAll("button")[best.i].click(); el("p-shock").closest(".card").scrollIntoView({ block: "start" }); });
    line.appendChild(go);
  }

  function renderOverview() {
    renderRiskLine();
    renderChanged();
    renderBeat();
    const dec = monthLabel(last.date), origin = monthLabel(F.origin);
    const kpi = (id, label, value, sub) => {
      const c = el(id); c.replaceChildren(node("div", { class: "label" }, label), node("div", { class: "value" }, value), node("div", { class: "sub" }, sub));
    };
    const q = last.quantiles;
    kpi("kpi-dec", t("kpi_dec", { date: dec }), pct(last.point),
      t("kpi_band", { lo: fmt(q.q16), hi: fmt(q.q84), lo90: fmt(q.q05), hi90: fmt(q.q95) }));
    el("kpi-dec").querySelector(".value").after(node("div", { class: "point" }, t("kpi_point", { v: pct(last.point, 2) })));  // 1 dp headline: the error is ~0.6 pp
    kpi("kpi-last", t("kpi_last", { date: origin }), sgn(last.point - F.last_actual_yoy, 2) + " " + t("pp"), `${origin}: ${pct(F.last_actual_yoy)}`);
    el("kpi-last").querySelector(".value").after(node("div", { class: "point" }, t("kpi_last_why", { base: sgn(last.base_effect_pp), mom: sgn(last.momentum_pp) })));
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
      { x: fx, y: qs(lo), mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false, meta: { csvName: `${name} (${lo})` } },
      { x: fx, y: qs(hi), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: css(color), name, hoverinfo: "skip",
        meta: { csvName: `${name} (${hi})` } },
      { x: hoverX, y: qs(hi).slice(1), customdata: qs(lo).slice(1), mode: "markers", marker: { size: 1, opacity: 0 },
        showlegend: false, hovertemplate: `${name}: %{customdata:.1f}–%{y:.1f}%<extra></extra>`, meta: { csv: false } },
    ];
    const extra = [];
    if (octPrint !== null) {
      const cond = ShockEngine.conditionalPath(F.headline_index, P[0].date, octPrint, P.map((p) => p.date));
      extra.push({ x: [toDate(F.origin), ...P.map((p) => toDate(p.date))], y: [F.last_actual_yoy, ...P.map((p) => cond[p.date])],
        mode: "lines+markers", name: t("s_if_oct", { v: fmt(octPrint, 1) }), line: { color: css("--s2"), width: 2 },
        marker: { size: 7, color: css("--s2") }, hovertemplate: "%{y:.2f}%" });
    }
    plot("p-headline", [
      ...band("q05", "q95", "--band90", t("s_band90")),
      ...band("q16", "q84", "--band68", t("s_band68")),
      { x: hx, y: hy, mode: "lines", name: t("s_actual"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%" },
      { x: fx, y: fc, mode: "lines", line: { color: acc, width: 2, dash: "dot" }, hoverinfo: "skip", showlegend: false, meta: { csv: false } },
      { x: hoverX, y: fc.slice(1), mode: "lines+markers", name: t("s_forecast"), line: { color: acc, width: 2, dash: "dot" },
        marker: { size: 8, color: acc, line: { color: css("--surface-1"), width: 2 } }, hovertemplate: "%{y:.2f}%" },
      { x: [hx[0], fx[fx.length - 1]], y: [F.ecb_target, F.ecb_target], mode: "lines", name: t("s_target"),
        line: { color: css("--neutral"), width: 1, dash: "dash" }, hoverinfo: "skip" },
      ...extra,
    ], baseLayout({
      yaxis: Object.assign(baseLayout().yaxis, { ticksuffix: "%" }),
      xaxis: Object.assign(baseLayout().xaxis, { range: [`${Number(F.origin.slice(0, 4)) - 2}-${F.origin.slice(5, 7)}-01`, `${last.date}-25`] }),
      shapes: [{ type: "rect", xref: "x", yref: "paper", x0: `${F.origin}-16`, x1: `${last.date}-25`, y0: 0, y1: 1, fillcolor: css("--surface-2"), line: { width: 0 }, layer: "below" },
        { type: "line", xref: "x", yref: "paper", x0: `${F.origin}-16`, x1: `${F.origin}-16`, y0: 0, y1: 1, line: { color: css("--axis"), width: 1, dash: "dot" } }],
      annotations: [{ xref: "x", yref: "paper", x: `${F.origin}-20`, y: 1, text: t("fc_region"), showarrow: false, xanchor: "left", yanchor: "top",
        font: { size: 11, color: css("--text-secondary") } },
      { x: fx[fx.length - 1], y: last.point, text: `<b>${fmt(last.point)}%</b>`, xanchor: "left", xshift: 8,
        showarrow: false, font: { color: css("--text-primary"), size: 13 } }],
      margin: { l: 48, r: 56, t: 8, b: 36 },
    }));
    table(el("tbl-headline"), [t("month"), t("s_forecast"), "q05", "q16", "q84", "q95", t("s_base"), t("s_mom")],
      P.map((p) => [monthLabel(p.date), fmt(p.point, 2), fmt(p.quantiles.q05, 2), fmt(p.quantiles.q16, 2), fmt(p.quantiles.q84, 2),
        fmt(p.quantiles.q95, 2), sgn(p.base_effect_pp), sgn(p.momentum_pp)]), [1, 2, 3, 4, 5, 6, 7]);
    if (!headlineBound) {  // Plotly's .on() adds a listener per call: bind once
      el("p-headline").on("plotly_click", (ev) => {
        const pt = ev.points && ev.points[0];
        if (!pt) return;
        const ym = String(pt.x).slice(0, 7);
        if (MONTHS.includes(ym)) { el("mx-month").value = ym; renderMonth(); }
      });
      headlineBound = true;
    }
    renderMonth();
    renderOct();
  }

  // ------------------------------------------------------------------ 1. one month, explained
  let headlineBound = false;
  const contribOf = (ym) => {
    const h = F.history.find((x) => x.date === ym); if (h) return { c: h.contributions, y: h.yoy, kind: "actual" };
    const p = P.find((x) => x.date === ym); if (p) return { c: p.contributions, y: p.point, kind: "fc" };
    return null;
  };
  const MONTHS = [...F.history.map((h) => h.date), ...P.map((p) => p.date)];
  function renderMonth() {
    const sel = el("mx-month");
    if (!sel.options.length) {
      sel.replaceChildren(...MONTHS.map((m) => node("option", { value: m }, "")));
      sel.value = last.date;
    }
    [...sel.options].forEach((o) => { o.textContent = monthLabel(o.value); });
    const ym = sel.value, prev = ShockEngine.addMonths(ym, -1);
    const cur = contribOf(ym), before = contribOf(prev), ex = ShockEngine.explainMonth(F.headline_index, ym);
    if (!cur || !ex) { el("mx-sentence").textContent = ""; return; }
    let big = null;
    if (before) for (const c of COMPS) { const dc = cur.c[c] - before.c[c]; if (!big || Math.abs(dc) > Math.abs(big.dc)) big = { c, dc }; }
    el("mx-sentence").textContent = t("mx_sentence", {
      month: monthLabel(ym), y: fmt(cur.y, 2), kind: t(cur.kind === "fc" ? "mx_fc" : "mx_actual"), d: sgn(ex.delta_pp), prev: monthLabel(prev),
      y0: fmt(ex.yoy_prev, 2), m: sgn(ex.momentum_pp), mm: sgn(ex.mom_pct, 2), b: sgn(ex.base_effect_pp),
      comp: big ? comp(big.c) : "–", dc: big ? sgn(big.dc) : "–" });
    const ys = COMPS.map(comp), tr = [];
    if (before) tr.push({ type: "bar", orientation: "h", name: `${t("mx_prev_bar")} (${monthLabel(prev)})`, y: ys, x: COMPS.map((c) => before.c[c]),
      marker: { color: css("--axis") }, hovertemplate: "%{x:.2f} " + t("pp") });
    tr.push({ type: "bar", orientation: "h", name: `${t("mx_this_bar")} (${monthLabel(ym)})`, y: ys, x: COMPS.map((c) => cur.c[c]),
      marker: { color: COMPS.map((c) => css(SLOT[c])) }, hovertemplate: "%{x:.2f} " + t("pp") });
    plot("p-month", tr, baseLayout({ barmode: "group", bargap: 0.3, hovermode: "y unified", margin: { l: 10, r: 16, t: 8, b: 36 },
      yaxis: Object.assign(baseLayout().yaxis, { autorange: "reversed" }) }));
  }

  // ------------------------------------------------------------------ 2. what if October prints differently?
  let octPrint = null;
  function renderOct() {
    const first = P[0], decP = P[P.length - 1];
    el("t-oct").textContent = t("oct_title");
    const inp = el("oct-in"), rng = el("oct-range");
    const v = octPrint === null ? first.point : octPrint;
    if (document.activeElement !== inp) inp.value = v.toFixed(2);
    if (document.activeElement !== rng) rng.value = v;
    const months = P.map((p) => p.date);
    const cond = ShockEngine.conditionalPath(F.headline_index, first.date, v, months);
    const err2 = F.error_samples["2"];
    el("oct-sentence").textContent = t("oct_sentence", { v: fmt(v, 1), d: fmt(cond[decP.date], 2), dd: sgn(cond[decP.date] - decP.point),
      b: fmt(decP.point, 2), thr: fmt(thr, 1), p: fmt(100 * ShockEngine.probAbove(cond[decP.date], err2, thr), 0),
      p0: probTxt(probOf(decP.point, thr)) });
    table(el("tbl-oct"), [t("oct_col_month"), t("oct_col_base"), t("oct_col_cond", { v: fmt(v, 1) }), t("oct_col_diff")],
      P.map((p) => [monthLabel(p.date), fmt(p.point, 2), fmt(cond[p.date], 2), sgn(cond[p.date] - p.point)]), [1, 2, 3]);
  }
  function setOct(v) {
    if (!Number.isFinite(v)) return;
    octPrint = Math.abs(v - P[0].point) < 1e-6 ? null : Math.min(8, Math.max(0, v));
    renderOverview();
  }

  // ------------------------------------------------------------------ drivers
  // ------------------------------------------------------------------ core inflation (by-product, D44)
  function renderCore() {
    const K = D.core, lp = K.points[K.points.length - 1];
    const met = (h) => K.metrics.find((r) => r.h === h && r.sample === "full");
    el("core-text").textContent = t("core_text", { last: pct(K.last_actual, 2), o: monthLabel(K.origin), d: monthLabel(lp.date), v: pct(lp.point, 2),
      lo: fmt(lp.quantiles.q16, 1), hi: fmt(lp.quantiles.q84, 1), goods: sgn(lp.contributions.IGD_NNRG), serv: sgn(lp.contributions.SERV),
      head: pct(last.point, 2) });
    const hx = K.history.map((h) => toDate(h.date)), path = [K.origin, ...K.points.map((p) => p.date)].map(toDate);
    const pv = [K.last_actual, ...K.points.map((p) => p.point)];
    const band = (lo, hi, col, name) => [
      { x: path, y: [K.last_actual, ...K.points.map((p) => p.quantiles[hi])], mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false, meta: { csv: false } },
      { x: path, y: [K.last_actual, ...K.points.map((p) => p.quantiles[lo])], mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: css(col), name, hoverinfo: "skip" }];
    plot("p-core", [
      ...band("q05", "q95", "--band90", t("s_band90")), ...band("q16", "q84", "--band68", t("s_band68")),
      { x: hx, y: K.history.map((h) => h.headline_yoy), mode: "lines", name: t("core_headline"), line: { color: css("--neutral"), width: 1.5 }, hovertemplate: "%{y:.2f}%" },
      { x: hx, y: K.history.map((h) => h.core_yoy), mode: "lines", name: t("core_actual"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%" },
      { x: path, y: pv, mode: "lines+markers", name: t("core_fc"), line: { color: css("--accent"), width: 2, dash: "dot" }, marker: { size: 7 }, hovertemplate: "%{y:.2f}%" },
      { x: path, y: path.map(() => K.last_actual), mode: "lines", name: t("core_rw"), line: { color: css("--s2"), width: 1.5, dash: "dash" }, hovertemplate: "%{y:.2f}%" },
    ], baseLayout({ yaxis: Object.assign(baseLayout().yaxis, { ticksuffix: "%" }) }));
    table(el("tbl-core"), [t("core_col_h"), t("core_col_rmse"), t("core_col_rw"), t("core_col_ratio"), t("core_col_p"), "n"],
      [1, 2, 3].map((h) => { const m = met(h); return [String(h), fmt(m.rmse, 2), fmt(m.rmse_rw, 2), fmt(m.rmse_ratio_vs_rw, 2), m.dm_p === null ? "–" : fmt(m.dm_p, 3), String(m.n)]; }),
      [1, 2, 3, 4, 5]);
    const worse = [1, 2, 3].filter((h) => met(h).rmse_ratio_vs_rw > 1), sig = worse.filter((h) => met(h).dm_p !== null && met(h).dm_p < 0.05);
    el("core-verdict").textContent = (K.models.IGD_NNRG === "NC" && K.models.SERV === "NC")
      ? t("core_verdict_nc", { r: fmt(met(3).rmse_ratio_vs_rw, 2) })
      : worse.length === 3
      ? t("core_verdict_rw", { sig: sig.length ? t("core_sig", { hs: sig.join(", ") }) : t("core_nosig"), rw: pct(K.last_actual, 2) })
      : t("core_verdict_model");
    el("core-note").textContent = t("core_note", { goods: K.models.IGD_NNRG, serv: K.models.SERV, gap: fmt(K.max_abs_gap_pp, 3), n: K.n_origins });
  }

  // A bridge as floating bars (D59): Plotly's waterfall cannot colour bars one by one, so each step is a bar from the
  // running total, coloured like its component everywhere else; labels are horizontal and wrapped, values on top.
  const wrapLab = (s, n = 13) => s.split(" ").reduce((acc, w) => {
    const lines = acc.split("<br>"), lastL = lines[lines.length - 1];
    return acc ? (lastL.length + w.length + 1 > n ? acc + "<br>" + w : acc + " " + w) : w;
  }, "");
  function floatBridge(id, start, steps, end) {
    let cum = start.v;
    const base = [0], y = [start.v], col = [css("--text-secondary")], text = [pct(start.v, 2)];
    steps.forEach((s) => { base.push(s.v >= 0 ? cum : cum + s.v); y.push(Math.abs(s.v)); col.push(css(s.color)); text.push(sgn(s.v)); cum += s.v; });
    base.push(0); y.push(end.v); col.push(css("--text-secondary")); text.push(pct(end.v, 2));
    const labs = [start.lab, ...steps.map((s) => s.lab), end.lab];
    const lo = Math.min(start.v, end.v, ...base.slice(1, -1)) - 0.25, hi = Math.max(start.v, end.v, ...base.slice(1, -1).map((b, i) => b + y[i + 1])) + 0.25;
    // Narrow screens: horizontal bars, so each label gets a row of its own instead of colliding under the bars.
    const flat = (el(id).clientWidth || 800) < 640;
    const val = { ticksuffix: "%", range: [lo, hi] }, cat = { tickangle: 0, tickfont: { size: flat ? 11 : 11.5, color: css("--text-secondary") } };
    if (flat) Object.assign(cat, { autorange: "reversed", tickmode: "array", tickvals: labs, ticktext: labs, nticks: 0 });
    const tr = { type: "bar", base, text, textposition: "outside", cliponaxis: false, marker: { color: col, line: { width: 0 } },
      textfont: { size: 12, color: css("--text-secondary") }, hovertemplate: (flat ? "%{y}" : "%{x}") + ": %{text}<extra></extra>", width: 0.62 };
    if (flat) Object.assign(tr, { orientation: "h", x: y, y: labs }); else Object.assign(tr, { x: labs.map((l) => wrapLab(l)), y });
    plot(id, [tr], baseLayout({ showlegend: false, bargap: 0.35, hovermode: "closest", ...(flat ? { height: 340 } : {}),
      margin: flat ? { l: 130, r: 48, t: 8, b: 32 } : { l: 44, r: 16, t: 24, b: 64 },
      [flat ? "xaxis" : "yaxis"]: Object.assign(baseLayout()[flat ? "xaxis" : "yaxis"], val),
      [flat ? "yaxis" : "xaxis"]: Object.assign(baseLayout()[flat ? "yaxis" : "xaxis"], cat) }));
  }


  // ------------------------------------------------------------------ bridge: last print → December (D50)
  // By component: change in each exact chain-linked contribution (they add up to the change in y/y, apart from a
  // small chain-link residual, shown). Base effect vs momentum: the exact log split of the same change.
  let brMode = "comp", brBound = false;
  function renderBridge() {
    const h0 = F.history[F.history.length - 1], d = last, steps = [];
    el("br-title").textContent = t("br_title", { from: monthLabel(h0.date), to: monthLabel(d.date) });
    if (brMode === "comp") {
      COMPS.forEach((c) => steps.push([comp(c), d.contributions[c] - h0.contributions[c]]));
      const resid = (d.point - h0.yoy) - steps.reduce((s, x) => s + x[1], 0);
      steps.push([t("wc_resid"), resid]);
    } else {
      steps.push([t("s_base"), d.base_effect_pp], [t("s_mom"), d.momentum_pp]);
    }
    const x = [monthLabel(h0.date), ...steps.map((s) => s[0]), monthLabel(d.date)];
    const y = [h0.yoy, ...steps.map((s) => s[1]), d.point];
    const colorOf = (lab) => (brMode === "comp" ? (COMPS.find((c) => comp(c) === lab) ? SLOT[COMPS.find((c) => comp(c) === lab)] : "--neutral")
      : (lab === t("s_base") ? "--axis" : "--accent"));
    floatBridge("p-bridge", { lab: monthLabel(h0.date), v: h0.yoy }, steps.map((s) => ({ lab: s[0], v: s[1], color: colorOf(s[0]) })), { lab: monthLabel(d.date), v: d.point });
    const up = steps.filter((s) => s[1] > 0.005).sort((a, b) => b[1] - a[1]), dn = steps.filter((s) => s[1] < -0.005).sort((a, b) => a[1] - b[1]);
    el("br-text").textContent = t("br_text", { from: pct(h0.yoy, 2), to: pct(d.point, 2), d: sgn(d.point - h0.yoy),
      up: up.slice(0, 2).map((s) => `${s[0].toLowerCase()} ${sgn(s[1])}`).join(", ") || "–",
      dn: dn.slice(0, 2).map((s) => `${s[0].toLowerCase()} ${sgn(s[1])}`).join(", ") || "–" });
    el("br-note").textContent = t(brMode === "comp" ? "br_note_comp" : "br_note_bm");
    table(el("tbl-bridge"), [t("br_step"), t("br_value")], x.map((lab, i) => [lab, i === 0 || i === x.length - 1 ? pct(y[i], 2) : sgn(y[i])]), [1]);
    if (!brBound) {
      el("br-mode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
        brMode = b.dataset.br;
        el("br-mode").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        renderBridge();
      }));
      brBound = true;
    }
  }

  function renderDrivers() {
    renderBridge();
    renderCore();
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
    if (!contribBound) {  // click a month: open "One month, explained" for it on the Overview tab
      el("p-contrib").on("plotly_click", (ev) => {
        const pt = ev.points && ev.points[0], ym = pt && String(pt.x).slice(0, 7);
        if (!ym || !MONTHS.includes(ym)) return;
        showTab("overview");
        el("mx-month").value = ym; renderMonth();
        el("mx-month").closest(".card").scrollIntoView({ block: "start", behavior: "smooth" });
      });
      contribBound = true;
    }
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
  // ------------------------------------------------------------------ 4. compare countries
  const CC_SLOTS = ["--s1", "--s2", "--s3"];
  const ccSel = new Map([["DE", 0], ["IT", 1], ["FR", 2]]);  // country -> colour slot: colour follows the country
  function ccToggle(g) {
    if (ccSel.has(g)) ccSel.delete(g);
    else if (ccSel.size < CC_SLOTS.length) ccSel.set(g, [0, 1, 2].find((k) => ![...ccSel.values()].includes(k)));
    renderCountries();
  }
  function renderCompare() {
    const add = el("cc-add");
    const opts = Object.keys(C.yoy).sort((a, b) => geo(a).localeCompare(geo(b), lang)).filter((g) => !ccSel.has(g));
    add.replaceChildren(node("option", { value: "" }, t("cc_choose") + (ccSel.size >= 3 ? " " + t("cc_full") : "")),
      ...opts.map((g) => node("option", { value: g }, geo(g))));
    add.disabled = ccSel.size >= 3;
    const chips = el("cc-chips"); chips.replaceChildren();
    for (const [g, k] of ccSel) {
      const lab = node("label");
      const x = node("button", { type: "button", class: "chip-x", "aria-label": t("cc_remove", { c: geo(g) }) }, "×");
      x.addEventListener("click", () => ccToggle(g));
      lab.append(node("span", { class: "swatch", style: `background:var(${CC_SLOTS[k]})` }), document.createTextNode(geo(g)), x);
      chips.appendChild(lab);
    }
    const xs = C.dates.map(toDate);
    const tr = [{ x: xs, y: C.ea_yoy, mode: "lines", name: geo("EA"), line: { color: css("--text-secondary"), width: 3 }, hovertemplate: "%{y:.1f}%" }];
    for (const [g, k] of ccSel) tr.push({ x: xs, y: C.yoy[g], mode: "lines", name: geo(g), line: { color: css(CC_SLOTS[k]), width: 2 }, hovertemplate: "%{y:.1f}%" });
    plot("p-ccmp", tr, baseLayout({ yaxis: Object.assign(baseLayout().yaxis, { ticksuffix: "%" }) }));
  }
  let contribBound = false, cbarBound = false, csmBound = false, smGeos = [], cpGeo = "DE";

  // ------------------------------------------------------------------ country profile
  function renderProfile() {
    const sel = el("cp-country");
    const order = Object.keys(C.profiles).sort((a, b) => geo(a).localeCompare(geo(b), lang));
    sel.replaceChildren(...order.map((g) => node("option", { value: g }, geo(g))));
    sel.value = cpGeo;
    const g = cpGeo, prof = C.profiles[g], n = C.dates.length - 1, m = C.dates[n], prev = ShockEngine.addMonths(m, -1);
    el("cp-title").textContent = t("cp_title", { c: geo(g) });
    const ex = ShockEngine.explainMonth(prof.index, m);
    const ranked = Object.keys(C.contributions).sort((a, b) => (C.contributions[b][n] || 0) - (C.contributions[a][n] || 0));
    el("cp-summary").textContent = t("cp_summary", { c: geo(g), y: fmt(C.yoy[g][n], 1), m: monthLabel(m), d: ex ? sgn(ex.delta_pp) : "–",
      prev: monthLabel(prev), mo: ex ? sgn(ex.momentum_pp) : "–", b: ex ? sgn(ex.base_effect_pp) : "–",
      w: fmt(C.weights_latest[g] || 0, 1), yr: C.weights_year, ct: fmt(C.contributions[g][n] || 0, 2), r: ranked.indexOf(g) + 1, n: ranked.length });
    const warn = el("cp-warn");
    warn.hidden = prof.max_abs_gap_pp <= 0.02;
    warn.textContent = warn.hidden ? "" : t("cp_warn", { c: geo(g), g: fmt(prof.max_abs_gap_pp, 2) });

    const k0 = Math.max(0, C.dates.length - 36), xs = C.dates.slice(k0).map(toDate);
    const tr = COMPS.map((c) => ({ type: "bar", name: comp(c), x: xs, y: prof.contributions[c].slice(k0),
      marker: { color: css(SLOT[c]), line: { color: css("--surface-1"), width: 1 } }, hovertemplate: "%{y:.2f} " + t("pp") }));
    tr.push({ type: "scatter", mode: "lines", name: geo(g) + " (% y/y)", x: xs, y: C.yoy[g].slice(k0), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%" });
    plot("p-cp-drivers", tr, baseLayout({ barmode: "relative", bargap: 0.25 }));
    el("cp-drivers-note").textContent = t("cp_drivers_note", { g: fmt(prof.max_abs_gap_pp, 2) });

    const W = S.weight_matrix[g], tot = COMPS.reduce((a, c) => a + W[c], 0);
    plot("p-cp-basket", [
      { type: "bar", orientation: "h", name: geo("EA"), y: COMPS.map(comp), x: COMPS.map((c) => 100 * S.ea_effective_weights[c]), marker: { color: css("--axis") }, hovertemplate: "%{x:.1f}%" },
      { type: "bar", orientation: "h", name: geo(g), y: COMPS.map(comp), x: COMPS.map((c) => 100 * W[c] / tot), marker: { color: css("--text-secondary") }, hovertemplate: "%{x:.1f}%" },
    ], baseLayout({ barmode: "group", bargap: 0.3, hovermode: "y unified", margin: { l: 10, r: 16, t: 8, b: 36 },
      yaxis: Object.assign(baseLayout().yaxis, { autorange: "reversed" }), xaxis: Object.assign(baseLayout().xaxis, { ticksuffix: "%", nticks: 4 }) }));

    table(el("tbl-cp-sens"), [t("cp_comp"), t("cp_share"), t("cp_impact")], COMPS.map((c) => {
      const sc = { name: "profile", legs: [{ components: [c], countries: [g], size_pct: 10, profile: { kind: "permanent" }, start: S.months[0] }],
        second_round: false, second_round_regime: "post2020" };
      const r = ShockEngine.simulate(sc, S);
      return [comp(c), fmt(100 * W[c], 2), sgn(r.delta_yoy_pp[0], 3)];
    }), [1, 2]);
  }

  function renderCountries() {
    renderCompare();
    const n = C.dates.length - 1, date = C.dates[n];
    el("t-cbar").textContent = t("ch_country_bar", { date: monthLabel(date) });
    el("n-cbar").textContent = t("ch_country_bar_note", { gap: fmt(C.max_abs_gap_pp, 2) });
    const order = Object.keys(C.contributions).sort((a, b) => (C.contributions[b][n] || 0) - (C.contributions[a][n] || 0));
    plot("p-cbar", [{ type: "bar", orientation: "h", y: order.map(geo), x: order.map((g) => C.contributions[g][n]),
      marker: { color: css("--text-secondary") }, customdata: order.map((g) => C.yoy[g][n]),
      hovertemplate: "%{y}: %{x:.2f} " + t("pp") + " (y/y %{customdata:.1f}%)<extra></extra>" }],
    baseLayout({ hovermode: "closest", margin: { l: 10, r: 16, t: 8, b: 30 }, yaxis: Object.assign(baseLayout().yaxis, { autorange: "reversed" }) }));
    if (!cbarBound) {
      el("p-cbar").on("plotly_click", (ev) => {
        const name = ev.points && ev.points[0] && ev.points[0].y;
        const g = Object.keys(C.yoy).find((k) => geo(k) === name);
        if (g) ccToggle(g);
      });
      cbarBound = true;
    }

    const geos = Object.keys(C.yoy).sort((a, b) => geo(a).localeCompare(geo(b), lang));
    smGeos = geos;
    const cols = window.innerWidth < 700 ? 3 : 5, rows = Math.ceil(geos.length / cols);
    const xs = C.dates.map(toDate);
    let lo = Infinity, hi = -Infinity;
    for (const g of geos) for (const v of C.yoy[g]) if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const data = [], ann = [];
    const lay = baseLayout({ grid: { rows, columns: cols, pattern: "independent", xgap: 0.08, ygap: 0.42 }, showlegend: false,
      hovermode: "x", margin: { l: 30, r: 8, t: 18, b: 20 } });
    geos.forEach((g, k) => {
      const ax = k === 0 ? "" : String(k + 1);
      data.push({ x: xs, y: C.ea_yoy, xaxis: "x" + ax, yaxis: "y" + ax, mode: "lines", line: { color: css("--axis"), width: 1.5 }, name: geo("EA"), hovertemplate: "%{y:.1f}%" });
      const picked = ccSel.has(g);  // not "hi": that name holds the shared y-axis maximum in this function
      data.push({ x: xs, y: C.yoy[g], xaxis: "x" + ax, yaxis: "y" + ax, mode: "lines", name: geo(g), hovertemplate: "%{y:.1f}%",
        line: { color: picked ? css(CC_SLOTS[ccSel.get(g)]) : css("--text-primary"), width: picked ? 2.5 : 1.5 } });
      const base = baseLayout();
      // Years on every panel: a small multiple without a time axis hides which period it shows.
      const y0 = Number(C.dates[0].slice(0, 4));
      const tv = [y0 + 1, y0 + 3, y0 + 5].filter((y) => y <= Number(C.dates[n].slice(0, 4)));
      lay["xaxis" + ax] = Object.assign({}, base.xaxis, { showgrid: false, tickmode: "array", tickvals: tv.map((y) => `${y}-01-01`),
        ticktext: tv.map(String), tickfont: { size: 9, color: css("--text-muted") }, ticks: "outside", ticklen: 3, tickcolor: css("--axis"),
        range: [xs[0], xs[xs.length - 1]] });
      lay["yaxis" + ax] = Object.assign({}, base.yaxis, { range: [Math.floor(lo), Math.ceil(hi)], tickfont: { size: 9, color: css("--text-muted") }, nticks: 3 });
      ann.push({ text: `${ccSel.has(g) ? "<b>" + geo(g) + "</b>" : geo(g)} <span style="color:${css("--text-muted")}">${fmt(C.yoy[g][n])}%</span>`, xref: `x${ax} domain`, yref: `y${ax} domain`,
        x: 0, y: 1.18, xanchor: "left", showarrow: false, font: { size: 11, color: css("--text-primary") } });
    });
    lay.annotations = ann;
    el("p-csm").style.height = (rows * 140 + 50) + "px";
    plot("p-csm", data, lay);
    if (!csmBound) {  // click a panel (country line or the euro area line in it) -> its profile
      el("p-csm").on("plotly_click", (ev) => {
        const pt = ev.points && ev.points[0];
        if (!pt) return;
        const k = pt.data.xaxis === "x" ? 0 : Number(pt.data.xaxis.slice(1)) - 1;
        if (smGeos[k]) { cpGeo = smGeos[k]; renderProfile(); el("cp-card").scrollIntoView({ block: "start", behavior: "smooth" }); }
      });
      csmBound = true;
    }
    renderProfile();
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
    ["rev-solve", "rev-mode", "rev-month", "rev-y", "rev-p"].forEach((id) => el(id).addEventListener("input", renderReverse));
    el("rev-apply").addEventListener("click", () => {
      if (revSolvedAll) { scenario.legs.forEach((x, i) => { x.size_pct = Math.round(revSolvedAll[i] * 1000) / 1000; }); markCustom(); refreshAll(); return; }
      if (revSolved === null) return;
      activeShock().size_pct = Math.round(revSolved * 1000) / 1000; markCustom(); refreshAll();
    });
    el("nl-go").addEventListener("click", nlInterpret);
    el("nl-run").addEventListener("click", nlRun);
    el("nl-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); nlInterpret(); } });
    el("sim-share").addEventListener("click", copyShare);
    el("sim-export").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json" });
      const a = node("a", { href: URL.createObjectURL(blob), download: "scenario.json" });
      document.body.appendChild(a); a.click(); a.remove();
    });
  }

  function refreshAll() { labelForm(); toForm(); renderLegs(); renderShock(); }

  // ---- scenario comparison (D54): the presets plus scenarios the reader saves (kept in this browser), up to four
  // shown together. Colour follows the scenario, not its position (a slot is held while it stays selected).
  const CMP_KEY = "hicp.scenarios", CMP_MAX = 4, CMP_SLOTS = ["--s1", "--s2", "--s3", "--s5"];
  const cmpLoad = () => { try { return JSON.parse(localStorage.getItem(CMP_KEY) || "[]"); } catch (e) { return []; } };
  const cmpStore = (list) => { try { localStorage.setItem(CMP_KEY, JSON.stringify(list)); return true; } catch (e) { return false; } };
  let cmpSaved = cmpLoad().filter((x) => x && x.id && x.scenario && ShockEngine.decodeScenario(ShockEngine.encodeScenario(x.scenario), S).scenario);
  const cmpSel = new Map([["preset-0", 0], ["preset-1", 1]]);  // id -> colour slot
  let cmpBound = false;
  const cmpAll = () => [...S.presets.map((p, i) => ({ id: `preset-${i}`, name: p.name, scenario: p, builtin: true })), ...cmpSaved];
  function cmpToggle(id) {
    if (cmpSel.has(id)) { cmpSel.delete(id); renderScenarioCompare(); return; }
    if (cmpSel.size >= CMP_MAX) { el("cmp-status").textContent = t("cmp_max", { n: CMP_MAX }); return; }
    const used = new Set(cmpSel.values()); cmpSel.set(id, [0, 1, 2, 3].find((k) => !used.has(k)));
    renderScenarioCompare();
  }
  function cmpSave() {
    const name = (el("cmp-name").value || scenario.name || "").trim().slice(0, 60) || t("cmp_unnamed");
    const clean = ShockEngine.decodeScenario(ShockEngine.encodeScenario(Object.assign({}, scenario, { name })), S).scenario;
    if (!clean) { el("cmp-status").textContent = t("share_bad"); return; }
    const id = "saved-" + Date.now().toString(36);
    cmpSaved.push({ id, name, scenario: clean });
    const persisted = cmpStore(cmpSaved);
    el("cmp-status").textContent = persisted ? t("cmp_saved", { name }) : t("cmp_saved_session", { name });
    if (cmpSel.size < CMP_MAX) cmpToggle(id); else renderScenarioCompare();
  }
  function renderScenarioCompare() {
    if (!cmpBound) {
      el("cmp-save").addEventListener("click", cmpSave);
      el("cmp-name").addEventListener("keydown", (e) => { if (e.key === "Enter") cmpSave(); });
      cmpBound = true;
    }
    el("cmp-name").placeholder = scenario.name || "";
    const all = cmpAll(), byId = Object.fromEntries(all.map((x) => [x.id, x]));
    [...cmpSel.keys()].forEach((id) => { if (!byId[id]) cmpSel.delete(id); });
    const list = el("cmp-list"); list.replaceChildren();
    all.forEach((x) => {
      const lab = node("label"), cb = node("input", { type: "checkbox" }); cb.checked = cmpSel.has(x.id);
      cb.addEventListener("change", () => cmpToggle(x.id));
      lab.append(cb, node("span", { class: "swatch", style: cmpSel.has(x.id) ? `background:var(${CMP_SLOTS[cmpSel.get(x.id)]})` : "background:transparent" }), node("span", {}, x.name));
      const load = node("button", { type: "button", class: "chip-x", title: t("cmp_load") }, "↗");
      load.addEventListener("click", (e) => { e.preventDefault(); scenario = JSON.parse(JSON.stringify(x.scenario)); presetIdx = -1; activeLeg = 0; refreshAll(); el("sim-form").scrollIntoView({ block: "start" }); });
      lab.appendChild(load);
      if (!x.builtin) {
        const del = node("button", { type: "button", class: "chip-x", title: t("cmp_delete"), "aria-label": t("cmp_delete") }, "×");
        del.addEventListener("click", (e) => { e.preventDefault(); cmpSaved = cmpSaved.filter((y) => y.id !== x.id); cmpSel.delete(x.id); cmpStore(cmpSaved); renderScenarioCompare(); });
        lab.appendChild(del);
      }
      list.appendChild(lab);
    });
    const k = S.months.indexOf(last.date), xs = S.months.map(toDate);
    const chosen = [...cmpSel.entries()].map(([id, slot]) => ({ x: byId[id], slot, r: ShockEngine.simulate(byId[id].scenario, S) }));
    plot("p-compare", chosen.map(({ x, slot, r }) => ({ x: xs, y: r.delta_yoy_pp, mode: "lines+markers", name: x.name,
      line: { color: css(CMP_SLOTS[slot]), width: 2 }, marker: { size: 6 }, hovertemplate: `${x.name.replace(/[<>&]/g, "")}: %{y:+.2f} ${t("pp")}<extra></extra>` })),
    baseLayout({ yaxis: Object.assign(baseLayout().yaxis, { title: { text: t("pp") }, zeroline: true }),
      shapes: [{ type: "line", x0: toDate(last.date), x1: toDate(last.date), yref: "paper", y0: 0, y1: 1, line: { color: css("--axis"), width: 1, dash: "dash" } }] }));
    table(el("tbl-compare"), [t("cmp_col_name"), t("cmp_col_peak"), t("cmp_col_when"), t("cmp_col_dec", { d: monthLabel(last.date) }), t("cmp_col_level", { d: monthLabel(last.date) }), t("cmp_col_prob", { thr: fmt(thr, 1), d: monthLabel(last.date) }), t("cmp_col_legs")],
      [[t("s_baseline"), "–", "–", "0.00", pct(last.point, 2), probTxt(probOf(last.point, thr)) + "%", "0"],
        ...chosen.map(({ x, r }) => [x.name, sgn(r.peak_pp), monthLabel(r.peak_month), sgn(r.delta_yoy_pp[k]), pct(r.shocked_yoy[k], 2),
          probTxt(probOf(r.shocked_yoy[k], thr)) + "%", String(x.scenario.legs.length)])], [1, 3, 4, 5, 6]);
  }

  // ---- sensitivity heatmap: euro area* December y/y response to +1% in one (country, component) cell.
  // 126 runs of the same engine as the simulator, computed once (they depend on the basis only).
  let heat = null, heatBound = false;
  function heatData() {
    if (heat) return heat;
    const k = S.months.indexOf(last.date), z = {};
    S.countries.forEach((g) => {
      z[g] = COMPS.map((c) => ShockEngine.simulate({ name: "cell", legs: [{ components: [c], countries: [g], size_pct: 1,
        profile: { kind: "permanent" }, start: S.months[0] }], second_round: false, second_round_regime: "post2020",
        rationale: "sensitivity cell", sources: ["engine"] }, S).delta_yoy_pp[k] * 100);  // basis points
    });
    const order = [...S.countries].sort((a, b) => z[b].reduce((s, v) => s + v, 0) - z[a].reduce((s, v) => s + v, 0));
    return (heat = { z, order });
  }
  function renderHeat() {
    const { z, order } = heatData(), ys = order.map(geo), xs = COMPS.map(comp);
    Plotly.react(el("p-heat"), [{ type: "heatmap", x: xs, y: ys, z: order.map((g) => z[g]), customdata: order.map((g) => COMPS.map((c) => [g, c])),
      colorscale: [[0, css("--surface-2")], [1, css("--accent")]], zmin: 0, xgap: 2, ygap: 2,
      texttemplate: "%{z:.1f}", textfont: { size: 10 }, colorbar: { title: { text: "bp" }, thickness: 10, len: 0.6 },
      hovertemplate: `%{y} · %{x}<br>${t("hm_hover")}: %{z:.2f} bp<extra></extra>` }],
    baseLayout({ margin: { l: 10, r: 10, t: 8, b: 60 }, yaxis: Object.assign(baseLayout().yaxis, { autorange: "reversed", automargin: true }),
      xaxis: Object.assign(baseLayout().xaxis, { side: "bottom", automargin: true, tickangle: -20 }) }), CFG);
    table(el("tbl-heat"), [t("hm_country"), ...xs], order.map((g) => [geo(g), ...z[g].map((v) => fmt(v, 2))]), COMPS.map((_, i) => i + 1));
    if (!heatBound) {
      el("p-heat").on("plotly_click", (ev) => {
        const pt = ev.points && ev.points[0];
        if (!pt) return;
        const [g, c] = pt.customdata;
        scenario = { name: `${comp(c)} · ${geo(g)} +10%`, legs: [{ components: [c], countries: [g], size_pct: 10, profile: { kind: "permanent" }, start: S.months[0] }],
          second_round: false, second_round_regime: "post2020", mapping: null, sources: ["Sensitivity heatmap"],
          rationale: "Opened from the sensitivity heatmap: a +10% permanent price-level shock in one country and component, to read the size of the response; not a forecast of any event." };
        presetIdx = -1; activeLeg = 0;
        el("presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        refreshAll();
        el("p-shock").closest(".card").scrollIntoView({ block: "start", behavior: "smooth" });
      });
      heatBound = true;
    }
  }

  // ---- shareable link: the whole scenario in the URL fragment (nothing is sent anywhere)
  const shareUrl = (sc) => `${location.href.split("#")[0]}#s=${ShockEngine.encodeScenario(sc)}`;
  async function copyShare() {
    const url = shareUrl(scenario);
    history.replaceState(null, "", url);
    try { await navigator.clipboard.writeText(url); el("share-status").textContent = t("share_copied"); }
    catch (e) { el("share-status").textContent = t("share_manual"); }  // the address bar now holds the link
  }
  function loadShared() {
    const m = /#s=([A-Za-z0-9_-]+)/.exec(location.hash);
    if (!m) return false;
    const res = ShockEngine.decodeScenario(m[1], S);
    if (!res.scenario) { el("share-status").textContent = t("share_bad"); return false; }
    scenario = res.scenario; presetIdx = -1; activeLeg = 0;
    el("presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
    el("share-status").textContent = t("share_loaded");
    return true;
  }

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
  let revSolved = null; let revSolvedAll = null;  // sizes for all legs (D55)
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
    const solve = el("rev-solve");
    if (!solve.options.length) solve.replaceChildren(node("option", { value: "one" }, ""), node("option", { value: "min" }, ""), node("option", { value: "equal" }, ""));
    solve.options[0].textContent = t("rev_solve_one"); solve.options[1].textContent = t("rev_solve_min"); solve.options[2].textContent = t("rev_solve_equal");
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
    revSolved = null; revSolvedAll = null; apply.hidden = true;
    if (!Number.isFinite(target) || scenario.legs.some((x) => x.components.length === 0)) { out.textContent = ""; return; }
    if (solve.value !== "one") {  // all shocks together (D55)
      const rm = ShockEngine.solveMulti(scenario, S, m, target, solve.value);
      const baseNote0 = t("rev_baseline_note", { b: fmt(S.baseline_yoy[S.months.indexOf(m)], 2) });
      if (!rm.feasible) {
        out.textContent = (rm.reason === "no_effect" ? t("rev_none", { month: monthLabel(m) })
          : t("rev_multi_range", { month: monthLabel(m), ylo: fmt(rm.reach_low, 2), yhi: fmt(rm.reach_high, 2) })) + baseNote0;
        return;
      }
      const parts = scenario.legs.map((x, i) => `${i + 1}. ${legLabel(Object.assign({}, x, { size_pct: rm.sizes_pct[i] })).split(" · ").slice(0, 2).join(" · ")} ${sgn(rm.sizes_pct[i], 1)}%`);
      out.textContent = t(solve.value === "min" ? "rev_multi_min" : "rev_multi_equal", { goal, list: parts.join("; ") }) + baseNote0
        + (mode.value === "prob" ? " " + t("rev_prob_point", { pt: fmt(target, 2) }) : "");
      revSolvedAll = rm.sizes_pct; apply.hidden = false;
      return;
    }
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

  // ---- every paid API call goes through here: adds the access code (if the site has one) and, on a
  // "code required" answer, opens the code box in the Ask panel. The code lives in this tab only.
  let accessCode = "";
  try { accessCode = sessionStorage.getItem("hicp.code") || ""; } catch (e) { /* storage blocked */ }
  // What a reader sees when a live route fails (D60): quota, rate limit, outage or no network. The rest of the page
  // is computed in the browser and keeps working, so the message says so.
  function liveError(r, body, kind) {
    if (r.status === 429) return body.error || t("live_busy");
    if (r.status === 0 || r.status >= 500) return t("live_down_" + kind);
    return body.error || t("live_down_" + kind);
  }
  async function apiPost(url, payload) {
    let r, body = {};
    try {
      r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(accessCode ? Object.assign({}, payload, { access_code: accessCode }) : payload) });
      try { body = await r.json(); } catch (e) { /* non-JSON error page */ }
    } catch (e) { r = { ok: false, status: 0 }; }
    if (r.status === 401 && body.code_required) {
      accessCode = ""; try { sessionStorage.removeItem("hicp.code"); } catch (e) { /* ignore */ }
      if (url === "/api/scenario" && !el("ask-panel").contains(document.activeElement) && el("ask-panel").hidden) {
        el("nl-code-row").hidden = false; el("nl-code").focus();  // ask right under the sentence box
      } else {
        el("ask-code-row").hidden = false;
        if (el("ask-panel").hidden) askToggle(true, "ask-fab");
        el("ask-code").focus();
      }
      body = Object.assign({}, body, { error: t("code_needed") });
    }
    return { r, body };
  }
  function unlock(fromSentenceBox) {
    const inp = el(fromSentenceBox ? "nl-code" : "ask-code"), v = inp.value.trim();
    if (!v) return;
    accessCode = v; try { sessionStorage.setItem("hicp.code", v); } catch (e) { /* ignore */ }
    inp.value = ""; el("ask-code-row").hidden = true; el("nl-code-row").hidden = true;
    if (fromSentenceBox) nlInterpret();  // retry the sentence straight away
    else { el("ask-status").textContent = t("code_saved"); el("ask-text").focus(); }
  }

  async function nlInterpret() {
    const text = el("nl-text").value.trim();
    if (!text) return;
    if (!liveOk()) { el("nl-status").textContent = t("nl_live_off"); return; }
    el("nl-status").textContent = t("nl_busy"); el("nl-go").disabled = true; el("nl-confirm").hidden = true;
    try {
      const { r, body } = await apiPost("/api/scenario", { text });
      if (!r.ok || !body.scenario) {
        el("nl-status").textContent = [404, 405, 501].includes(r.status) ? t("nl_live_off") : liveError(r, body, "nl");
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
    kpi("k-prob", t("k_prob", { date: monthLabel(last.date), thr: fmt(thr, 1) }), probTxt(probOf(r.shocked_yoy[decIdx], thr)) + "%",
      `${t("k_prob_sub", { b: probTxt(probOf(last.point, thr)) })} · ${t("prob_shock_note")}`);

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
    // A fixed minimum scale (±0.5 pp) so bar heights mean the same thing across scenarios: an autoscaled axis made a
    // 0.008 pp shock fill the chart exactly like a 1 pp one. Larger impacts still widen the axis.
    const vals = [...r.delta_yoy_pp, ...(scenario.second_round ? [...r.delta_total_low_pp, ...r.delta_total_high_pp] : [])];
    const vmax = Math.max(0, ...vals), vmin = Math.min(0, ...vals), MIN_SPAN = 0.5;
    const yr = [vmin < -1e-9 ? Math.min(-MIN_SPAN, vmin * 1.15) : -0.02, Math.max(vmax > 1e-9 ? MIN_SPAN : 0.1, vmax * 1.15)];
    const pk = S.months.indexOf(r.peak_month);
    plot("p-shock", tr, baseLayout({ barmode: "relative", bargap: 0.3,
      yaxis: Object.assign(baseLayout().yaxis, { range: yr, autorange: false }),
      annotations: pk >= 0 ? [{ x: toDate(r.peak_month), y: r.delta_yoy_pp[pk], text: `${t("sim_peak_short")} ${sgn(r.peak_pp, Math.abs(r.peak_pp) < 0.1 ? 3 : 2)} ${t("pp")}`,
        showarrow: false, yanchor: r.delta_yoy_pp[pk] >= 0 ? "bottom" : "top", yshift: r.delta_yoy_pp[pk] >= 0 ? 4 : -4,
        font: { size: 11, color: css("--text-secondary") } }] : [] }));

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
  // ------------------------------------------------------------------ time machine
  // Go back to any past origin: what the bottom-up model forecast for the next three months, the fan that
  // could have been drawn THEN (quantiles of the errors already known at that origin), and what happened.
  const TM_MIN_ERRORS = 24;
  const tmBU = B.track.filter((x) => x.model === "bottom_up");
  const tmOrigins = [...new Set(tmBU.map((x) => x.origin))].sort();
  const tmActual = {};
  B.track.filter((x) => x.model === "bottom_up" && x.h === 1 && x.actual !== null).forEach((x) => { tmActual[x.target] = x.actual; });
  F.history.forEach((h) => { tmActual[h.date] = h.yoy; });
  let tmIdx = tmOrigins.indexOf("2022-06") >= 0 ? tmOrigins.indexOf("2022-06") : tmOrigins.length - 1, tmBound = false;

  function tmAt(o) {
    const rows = [1, 2, 3].map((h) => {
      const f = tmBU.find((x) => x.origin === o && x.h === h);
      const known = tmBU.filter((x) => x.h === h && x.actual !== null && x.target <= o).map((x) => x.actual - x.fc);
      const q = known.length >= TM_MIN_ERRORS ? [0.05, 0.16, 0.84, 0.95].map((p) => f.fc + ShockEngine.quantile(known, p)) : null;
      const rw = B.track.find((x) => x.model === "RW" && x.origin === o && x.h === h);
      return { h, target: f.target, fc: f.fc, actual: f.actual, q, n: known.length, rw: rw ? rw.fc : null };
    });
    return rows;
  }

  function renderTM() {
    const r = el("tm-range");
    r.max = String(tmOrigins.length - 1); r.value = String(tmIdx);
    const o = tmOrigins[tmIdx], rows = tmAt(o);
    el("tm-label").textContent = t("tm_origin", { m: monthLabel(o) });
    const j = el("tm-jump");
    if (!j.childElementCount) {
      [["2020-02", "tm_j_covid"], ["2021-09", "tm_j_2021"], ["2022-06", "tm_j_2022"], ["2023-06", "tm_j_2023"], [tmOrigins[tmOrigins.length - 1], "tm_j_now"]]
        .filter(([m]) => tmOrigins.includes(m)).forEach(([m, k]) => {
          const b = node("button", { type: "button", "data-i18n": k });
          b.addEventListener("click", () => { tmIdx = tmOrigins.indexOf(m); renderTM(); });
          j.appendChild(b);
        });
      applyText();
    }
    // readout: the h=3 forecast, its outcome, and whether it fell inside the fan known then
    const h3 = rows[2];
    let read = t("tm_read_fc", { o: monthLabel(o), tgt: monthLabel(h3.target), fc: pct(h3.fc, 2) });
    if (h3.actual !== null) {
      const e = h3.actual - h3.fc;
      const inside = h3.q ? (h3.actual >= h3.q[1] && h3.actual <= h3.q[2] ? "tm_in68" : h3.actual >= h3.q[0] && h3.actual <= h3.q[3] ? "tm_in90" : "tm_out90") : "tm_nofan";
      read += " " + t("tm_read_out", { act: pct(h3.actual, 2), err: sgn(e, 2) }) + " " + t(inside);
      if (h3.rw !== null) read += " " + t("tm_read_rw", { rw: sgn(h3.actual - h3.rw, 2), better: Math.abs(e) < Math.abs(h3.actual - h3.rw) ? t("tm_better") : t("tm_worse") });
    } else read += " " + t("tm_pending");
    el("tm-read").textContent = read;

    const from = addM(o, -24), to = addM(o, 6);
    const hist = Object.keys(tmActual).filter((m) => m >= from && m <= to).sort();
    const path = [o, ...rows.map((x) => x.target)], pv = [tmActual[o], ...rows.map((x) => x.fc)];
    const tr = [];
    if (rows.every((x) => x.q)) {
      const band = (lo, hi, name, col) => [
        { x: path.map(toDate), y: [tmActual[o], ...rows.map((x) => x.q[hi])], mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false, meta: { csv: false } },
        { x: path.map(toDate), y: [tmActual[o], ...rows.map((x) => x.q[lo])], mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: css(col), name, hoverinfo: "skip" }];
      tr.push(...band(0, 3, t("s_band90"), "--band90"), ...band(1, 2, t("s_band68"), "--band68"));
    }
    tr.push({ x: hist.map(toDate), y: hist.map((m) => tmActual[m]), mode: "lines", name: t("tm_actual"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f}%<extra></extra>" });
    tr.push({ x: path.map(toDate), y: pv, mode: "lines+markers", name: t("tm_forecast"), line: { color: css("--accent"), width: 2, dash: "dot" }, marker: { size: 8 }, hovertemplate: "%{y:.2f}%<extra></extra>" });
    plot("p-tm", tr, baseLayout({ hovermode: "x unified", margin: { l: 44, r: 16, t: 8, b: 36 },
      shapes: [{ type: "line", x0: toDate(o), x1: toDate(o), yref: "paper", y0: 0, y1: 1, line: { color: css("--axis"), width: 1, dash: "dash" } }],
      annotations: [{ x: toDate(o), y: 1, yref: "paper", text: t("tm_then"), showarrow: false, xanchor: "left", yanchor: "top", font: { size: 11, color: css("--text-secondary") } }],
      yaxis: Object.assign(baseLayout().yaxis, { ticksuffix: "%" }) }));
    if (!tmBound) {
      r.addEventListener("input", () => { tmIdx = Number(r.value); renderTM(); });
      tmBound = true;
    }
  }
  const addM = (ym, k) => ShockEngine.addMonths(ym, k);

  // ------------------------------------------------------------------ reconciliation with Eurostat (D52)
  function renderRecon() {
    const R = D.recon, st = R.stats, bp = (v) => (v === null ? null : 100 * v);
    el("rc-text").textContent = t("rc_text", { n: st.n_months, from: monthLabel(R.dates[0]), max: fmt(st.yoy_max_abs_err_pp, 3),
      mean: fmt(st.yoy_mean_abs_err_pp, 3), share: fmt(100 * st.match_official_1dp_share, 0), cmax: fmt(st.contrib_max_abs_err_pp, 3) });
    const x = R.dates.map(toDate);
    plot("p-recon", [
      { type: "bar", x, y: R.dates.map((_, i) => (R.yoy_rebuilt[i] === null || R.yoy_published[i] === null ? null : bp(R.yoy_rebuilt[i] - R.yoy_published[i]))),
        name: t("rc_s_head"), marker: { color: css("--s1") }, hovertemplate: "%{y:+.2f} bp<extra></extra>" },
      { type: "scatter", mode: "lines", x, y: R.contrib_max_abs_err_pp.map(bp), name: t("rc_s_contrib"), line: { color: css("--s2"), width: 1.5 },
        hovertemplate: "%{y:.2f} bp<extra></extra>", connectgaps: false },
    ], baseLayout({ hovermode: "x unified", bargap: 0, yaxis: Object.assign(baseLayout().yaxis, { title: { text: "bp" }, zeroline: true }) }));
    table(el("tbl-recon"), [t("rc_col_comp"), t("rc_col_ours"), t("rc_col_off"), t("rc_col_diff")],
      Object.entries(R.latest_contributions).map(([c, [o, f]]) => [D.i18n[lang]["c_" + c] || (c === "NRG" ? t("rc_nrg") : c === "FOOD" ? t("rc_food") : c),
        fmt(o, 3), fmt(f, 2), sgn(o - f, 3)]), [1, 2, 3]);
  }

  // What is pulled, in the brief's own terms (D59): COICOP ver.2 codes, unit I25 (2025 = 100), weights, model.
  function renderMeta() {
    const MODEL = { NC: t("meta_m_nc"), SM: t("meta_m_sm"), ARP: t("meta_m_arp"), PUMP: t("meta_m_pump"), SM_R120: t("meta_m_sm"), ARP_R120: t("meta_m_arp") };
    const rows = COMPS.map((c) => [c, comp(c), fmt(1000 * F.official_weights[c], 1), fmt(100 * F.effective_weights[c], 1), MODEL[F.selected_models[c]] || F.selected_models[c]]);
    rows.push(["TOTAL", t("meta_total"), "1000.0", "100.0", t("meta_m_bu")], ["TOT_X_NRG_FOOD", t("meta_core"), "–", "–", t("meta_m_core")]);
    table(el("tbl-meta"), [t("meta_code"), t("meta_label"), t("meta_w", { y: F.origin.slice(0, 4) }), t("meta_eff"), t("meta_model")], rows, [2, 3]);
    el("meta-note").textContent = t("meta_note", { n: S.countries.length, ds: [...new Set(M.vintages.map((v) => v.dataset))].join(", ") });
  }

  function renderModelSummary() {
    const r = B.metrics.find((x) => x.model === "bottom_up" && x.h === 3 && x.sample === "full");
    const g = V.gates, pass = g.filter((x) => x.status === "pass").length, warn = g.filter((x) => x.status === "warn").map((x) => x.gate);
    const tile = (v, l, s) => { const d = node("div"); d.append(node("div", { class: "v" }, v), node("div", { class: "l" }, l), node("div", { class: "s" }, s)); return d; };
    el("msum").replaceChildren(
      tile(fmt(r.rmse_ratio_vs_rw, 2), t("msum_ratio"), t("msum_ratio_s", { rmse: fmt(r.rmse, 2), rw: fmt(r.rmse_rw, 2) })),
      tile(fmt(r.dm_p, 3), t("msum_dm"), t("msum_dm_s")),
      tile(fmt(D.recon.stats.contrib_max_abs_err_pp, 3) + " " + t("pp"), t("msum_rc"), t("msum_rc_s", { h: fmt(D.recon.stats.yoy_max_abs_err_pp, 3) })),
      tile(`${pass + warn.length}/${g.length}`, t("msum_val"), warn.length ? t("msum_val_warn", { p: pass, g: warn.join(", ") }) : t("msum_val_ok")));
    el("msum-note").textContent = t("msum_note");
  }
  const DCODES = ["D27", "D28", "D29", "D44", "D56", "D57"];
  function renderCodes() {
    el("dc-list").replaceChildren(...DCODES.flatMap((c) => [node("dt", { id: "dc-" + c }, c), node("dd", {}, t("dc_" + c))]));
  }
  // Decision codes in any text become links to the list at the end of the Model tab (D60).
  function linkCodes(root = document.querySelector("main")) {
    const re = new RegExp(`\\b(${DCODES.join("|")})\\b`);
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) =>
      (re.test(n.nodeValue) && !n.parentElement.closest("#dc-list, a, button, script, style, .js-plotly-plot, .ask-msg")) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
    const hits = []; while (walk.nextNode()) hits.push(walk.currentNode);
    for (const n of hits) {
      const parts = n.nodeValue.split(new RegExp(`\\b(${DCODES.join("|")})\\b`));
      n.replaceWith(...parts.map((s, i) => (i % 2 ? node("a", { class: "dcode", href: "#dc-" + s, "data-dc": s }, s) : document.createTextNode(s))));
    }
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a.dcode"); if (!a) return;
    e.preventDefault();
    if (activeTab !== "model") document.querySelector("[data-tab=model]").click();
    setTimeout(() => {
      const dt = el("dc-" + a.dataset.dc); if (!dt) return;
      dt.scrollIntoView({ behavior: "smooth", block: "center" });
      [dt, dt.nextElementSibling].forEach((x) => { x.classList.add("flash"); setTimeout(() => x.classList.remove("flash"), 1800); });
    }, 350);
  });

  function renderModel() {
    renderModelSummary();
    renderCodes();
    renderRecon();
    renderMeta();
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
    renderTM();
    renderLedger();
    renderRound2();
    renderRound3();
    renderRound4();
    renderCalibration();
    renderRealtime();
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

  // ------------------------------------------------------------------ round 3 (D56): direct and ML models
  let r3H = 3;
  function renderRound3() {
    foldStatus("r3-status", D.round3.candidate);
    const R3 = D.round3, bu = (h) => R2.metrics.find((r) => r.model === "bottom_up" && r.h === h && r.sample === "full");  // the model of its time
    const seg = el("r3-h"); seg.replaceChildren(...[1, 2, 3].map((h) => {
      const b = node("button", { type: "button", "aria-pressed": String(h === r3H) }, t("r3_h", { h }));
      b.addEventListener("click", () => { r3H = h; renderRound3(); });
      return b;
    }));
    const NAME = { M2_sarima: t("r3_m2"), M3_enet: t("r3_m3"), M4_gbm: t("r3_m4"), M5_ensemble: t("r3_m5") };
    const rows = R3.metrics.filter((r) => r.h === r3H && r.sample === "full");
    const b0 = bu(r3H);
    const body = [[t("r3_bu"), fmt(b0.rmse, 3), fmt(b0.rmse_ratio_vs_rw, 2), fmt(b0.dm_p, 3), "–", "–"],
      ...rows.sort((a, b) => a.rmse - b.rmse).map((r) => {
        const hs = R3.holm.find((d) => d.name === r.model);
        return [NAME[r.model] || r.model, fmt(r.rmse, 3), fmt(r.rmse_ratio_vs_rw, 2), r.dm_p === null ? "–" : fmt(r.dm_p, 3),
          r.dm_p_vs_bottom_up === null ? "–" : fmt(r.dm_p_vs_bottom_up, 3), r3H === 3 ? (hs && hs.rejected ? t("r3_pass") : t("r3_fail")) : "–"];
      }),
      [t("r3_rw"), fmt(rows[0] ? rows[0].rmse_rw : NaN, 3), "1.00", "–", "–", "–"]];
    table(el("tbl-r3"), [t("r3_col_model"), t("r3_col_rmse"), t("r3_col_ratio"), t("r3_col_p"), t("r3_col_pbu"), t("r3_col_holm")], body, [1, 2, 3, 4]);
    const best = rows.slice().sort((a, b) => a.rmse - b.rmse)[0];
    el("r3-verdict").textContent = R3.candidate
      ? t("r3_verdict_pass", { m: NAME[R3.candidate] })
      : t("r3_verdict_none", { best: best ? NAME[best.model] : "–", rb: fmt(best ? best.rmse : NaN, 3), bu: fmt(b0.rmse, 3), h: r3H });
    const lastPts = Object.entries(R3.latest).map(([k, v]) => `${NAME[k]} ${pct(v[v.length - 1].fc, 2)}`).join(" · ");
    el("r3-latest").textContent = t("r3_latest", { d: monthLabel(last.date), list: lastPts, bu: pct(last.point, 2) });
  }

  // ------------------------------------------------------------------ round 4 (D57): bottom-up variants
  function foldStatus(id, passed) {
    const s = el(id); s.textContent = passed ? t("fold_passed") : t("fold_none"); s.classList.toggle("ok", !!passed);
  }
  function renderRound4() {
    foldStatus("r4-status", D.round4.adopted);
    const R4 = D.round4, NAME = { B1_core_nochange: t("r4_b1"), B2_allbutfuel_nochange: t("r4_b2"), B3_allbutfuel_shrink: t("r4_b3") };
    const rows = R4.metrics.filter((r) => r.h === 3 && r.sample === "full").sort((a, b) => a.rmse - b.rmse);
    const hs = (m) => R4.holm.find((d) => d.name === m);
    table(el("tbl-r4"), [t("r3_col_model"), t("r3_col_rmse"), t("r3_col_ratio"), t("r3_col_p"), t("r3_col_pbu"), t("r3_col_holm")],
      [[t("r4_bu"), fmt(rows[0].rmse_bottom_up, 3), fmt(rows[0].rmse_bottom_up / rows[0].rmse_rw, 2), "–", "–", "–"],
        ...rows.map((r) => [NAME[r.model] + (R4.adopted === r.model ? " ★" : ""), fmt(r.rmse, 3), fmt(r.rmse_ratio_vs_rw, 2), fmt(r.dm_p, 3),
          fmt(r.dm_p_vs_bottom_up, 3), hs(r.model).rejected ? `${t("r3_pass")} (${fmt(hs(r.model).threshold, 4)})` : `${t("r3_fail")} (${fmt(hs(r.model).threshold, 4)})`]),
        [t("r3_rw"), fmt(rows[0].rmse_rw, 3), "1.00", "–", "–", "–"]], [1, 2, 3, 4]);
    const a = R4.adopted && rows.find((r) => r.model === R4.adopted);
    el("r4-verdict").textContent = a ? t("r4_verdict", { m: NAME[a.model], p: fmt(a.dm_p, 3), thr: fmt(hs(a.model).threshold, 4), r: fmt(a.rmse, 3), rb: fmt(a.rmse_bottom_up, 3) })
      : t("r4_verdict_none");
  }

  function renderRound2() {
    foldStatus("r2-status", R2.adopted);
    const row = (m) => R2.metrics.find((x) => x.model === m && x.h === 3 && x.sample === "full");
    const holm = Object.fromEntries(R2.holm.map((h) => [h.name, h]));
    const order = ["bottom_up", "C1_ppi", "C2_combo", "C3_ic"];
    table(el("tbl-r2"), [t("r2_model"), t("r2_ratio"), t("r2_p"), t("r2_thr"), t("r2_pass")],
      order.map((m) => {
        const r = row(m), hm = holm[m];
        const gated = m === "C1_ppi" && hm.p === null;
        return [t("m_" + m), fmt(r.rmse_ratio_vs_rw, 3), gated ? t("r2_gated", { p: fmt(R2.gate.dm_p, 2) }) : fmt(hm.p, 3),
          fmt(hm.threshold, 4), hm.rejected ? t("yes") : t("no")];
      }), [1, 2, 3]);
    if (R2.adopted) { el("r2-verdict").textContent = t("r2_adopted", { m: t("m_" + R2.adopted) }); return; }
    const cands = ["C2_combo", "C3_ic"].concat(holm.C1_ppi.p === null ? [] : ["C1_ppi"]);
    const best = cands.reduce((a, b) => (row(b).rmse < row(a).rmse ? b : a));
    el("r2-verdict").textContent = t("r2_none", { r: fmt(row(best).rmse_ratio_vs_rw, 2), p: fmt(holm[best].p, 3), thr: fmt(holm[best].threshold, 4) });
  }

  function renderCalibration() {
    const sx = Object.keys(CAL.sigma), sy = sx.map((k) => CAL.sigma[k]);
    plot("p-sigma", [{ x: sx.map(toDate), y: sy, mode: "lines", name: t("cal_sigma"), line: { color: css("--text-primary"), width: 2 }, hovertemplate: "%{y:.2f} " + t("pp") }],
      baseLayout({ showlegend: false, title: { text: t("cal_sigma"), font: { size: 12, color: css("--text-secondary") }, x: 0 }, margin: { l: 48, r: 16, t: 30, b: 30 } }));
    const per = { "2010-2019": "sample_2010-2019", "2020-2023": "sample_2020-2023", "2024-now": "sample_2024-now", "all scored": "sample_full" };
    table(el("tbl-cal"), [t("cal_fan"), t("cal_period"), "n", t("cal_pinball"), t("cal_in68"), t("cal_in90")],
      CAL.rows.filter((r) => r.h === 3).map((r) => [t("fan_" + r.fan), t(per[r.period]), String(r.n), fmt(r.pinball, 3),
        fmt(100 * r.in68, 0) + "%", fmt(100 * r.in90, 0) + "%"]), [2, 3, 4, 5]);
    const dcs = CAL.decision;
    // Reading, computed from the rows above (a hand-written version went stale when the model changed, D59).
    const cr = (fan, per) => (CAL.rows.find((r) => r.fan === fan && r.h === 3 && r.period === per) || {});
    el("cal-reading").textContent = t("cal_reading", { b: fmt(100 * cr("B", "2020-2023").in68, 0), a: fmt(100 * cr("A", "2020-2023").in68, 0),
      ar: fmt(100 * cr("A", "all scored").in68, 0), cur: fmt(100 * cr("current", "all scored").in68, 0) });
    el("cal-verdict").textContent = dcs.adopt_B ? t("cal_verdict_adopt", { p: fmt(dcs.dm_p, 3) })
      : t("cal_verdict_keep", { pct: fmt(100 * (1 - dcs.mean_loss_B / dcs.mean_loss_A), 0), a: fmt(dcs.mean_loss_A, 3), b: fmt(dcs.mean_loss_B, 3), p: fmt(dcs.dm_p, 2) });
  }

  function renderRealtime() {
    table(el("tbl-rt"), [t("rt_target"), t("bt_model"), "h", "n", t("rt_ratio"), t("rt_p"), t("rt_ratio_lv"), t("rt_p_lv")],
      RT.rows.map((r) => [r.target === "flash" ? t("rt_fls") : t("rt_fin"), t("m_" + r.model), String(r.h), String(r.n),
        fmt(r.ratio, 3), r.dm_p === null ? "–" : fmt(r.dm_p, 3), fmt(r.ratio_latest_vintage, 3), r.dm_p_latest_vintage === null ? "–" : fmt(r.dm_p_latest_vintage, 3)]),
      [2, 3, 4, 5, 6, 7]);
    const bu = RT.rows.filter((r) => r.model === "bottom_up" && r.ratio !== null && r.ratio_latest_vintage !== null);
    const dmax = Math.max(...bu.map((r) => Math.abs(r.ratio - r.ratio_latest_vintage)));
    el("rt-reading").textContent = t("rt_reading", { d: fmt(dmax, 2) });
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
    if (tab === "shocks") { refreshAll(); renderNL(); renderScenarioCompare(); renderHeat(); }
    if (tab === "model") renderModel();
    linkCodes();
  }
  function renderAll() { applyText(); renderAsk(); renderTab(activeTab); linkCodes(); }

  function setTheme(th) {
    theme = th; store.set("hicp.theme", th);
    if (th === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", th);
    renderAll();
  }

  function showTab(name) {
    activeTab = name;
    document.querySelectorAll("[role=tab]").forEach((x) => x.setAttribute("aria-selected", String(x.dataset.tab === name)));
    document.querySelectorAll("[role=tabpanel]").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
    renderTab(name);
    fitPlots(name);
  }
  // Plotly cannot measure a chart in a hidden tab, so a window resize while a tab is hidden (or a render made while
  // it was hidden, e.g. for the brief) leaves its charts at the old width, overflowing their cards. Refit on show.
  function fitPlots(name) {
    setTimeout(() => el("tab-" + name).querySelectorAll(".plot").forEach((p) => { if (p.data) Plotly.Plots.resize(p); }), 0);
  }
  document.querySelectorAll("[role=tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  // ------------------------------------------------------------------ guided tour
  // Never opens by itself: a one-line banner offers it on the first visit, the Tour button restarts it.
  // Every feature, in reading order. Steps with `when` appear only where that feature is available.
  const TOUR_ALL = [
    { key: "answer", tab: "overview", sel: "#answer" },
    { key: "changed", tab: "overview", sel: "#wc-card", self: true },
    { key: "note", tab: "overview", sel: "#note-title", when: () => !el("note-card").hidden },
    { key: "prob", tab: "overview", sel: "#t-prob" },
    { key: "beat", tab: "overview", sel: "#bm-title" },
    { key: "fan", tab: "overview", sel: "#p-headline", corner: "left" },  // the fan sits at the right of the chart
    { key: "month", tab: "overview", sel: "#mx-month" },
    { key: "october", tab: "overview", sel: "#oct-in" },
    { key: "drivers", tab: "drivers", sel: "#p-contrib" },
    { key: "bridge", tab: "drivers", sel: "#br-title" },
    { key: "basemom", tab: "drivers", sel: "#p-basemom" },
    { key: "core", tab: "drivers", sel: "#core-card", self: true },
    { key: "countries", tab: "countries", sel: "#p-csm" },
    { key: "profile", tab: "countries", sel: "#cp-summary", self: true },  // the whole card is taller than the screen
    { key: "shock", tab: "shocks", sel: "#sim-form" },
    { key: "reverse", tab: "shocks", sel: "#rev-card", self: true },
    { key: "compare", tab: "shocks", sel: "#cmp-card", self: true },
    { key: "heat", tab: "shocks", sel: "#hm-card", self: true },
    { key: "backtest", tab: "model", sel: "#tbl-bt" },
    { key: "timemachine", tab: "model", sel: "#tm-card", self: true },
    { key: "trust", tab: "model", sel: "#tbl-r2" },
    { key: "recon", tab: "model", sel: "#rc-card", self: true },
    { key: "ledger", tab: "model", sel: "#n-led" },
    { key: "ask", tab: "overview", sel: "#ask-open", self: true, when: () => !el("ask-open").hidden },
    { key: "brief", tab: "overview", sel: "#brief-open", self: true },
  ];
  let TOUR = TOUR_ALL;
  let tourIdx = -1, tourEl = null;
  const tourTarget = (s) => { const e = document.querySelector(s.sel); return s.self ? e : (e.closest(".card") || e); };

  function tourShow(i) {
    if (i === 0 || tourIdx < 0) TOUR = TOUR_ALL.filter((s) => !s.when || s.when());
    tourIdx = i;
    const s = TOUR[i];
    if (activeTab !== s.tab) showTab(s.tab);
    if (tourEl) tourEl.classList.remove("tour-target");
    tourEl = tourTarget(s);
    { const f = tourEl.closest("details.fold") || tourEl.querySelector("details.fold"); if (f) f.open = true; }
    tourEl.classList.add("tour-target");
    el("tour-step").textContent = t("tour_step", { i: i + 1, n: TOUR.length });
    el("tour-title").textContent = t(`tour_${s.key}_t`);
    el("tour-body").textContent = t(`tour_${s.key}_b`);
    el("tour-back").disabled = i === 0;
    el("tour-next").textContent = i === TOUR.length - 1 ? t("tour_done") : t("tour_next");
    el("tour-shade").hidden = false;
    el("tour-box").hidden = false;
    el("tour-banner").hidden = true;
    // If the target and the box fit together, put the target at the top with the box underneath;
    // otherwise centre the target and park the box in a corner (tourPlace).
    const th = tourEl.getBoundingClientRect().height, bh = el("tour-box").offsetHeight;
    if (innerWidth > 700 && th + bh + 40 < innerHeight) window.scrollBy(0, tourEl.getBoundingClientRect().top - 16);
    else tourEl.scrollIntoView({ block: "center" });
    requestAnimationFrame(tourPlace);
    el("tour-next").focus({ preventScroll: true });
  }

  function tourPlace() {
    if (tourIdx < 0) return;
    const box = el("tour-box");
    if (innerWidth <= 700) { box.style.top = ""; box.style.left = ""; return; }  // CSS bottom sheet on phones
    const r = tourEl.getBoundingClientRect(), bw = box.offsetWidth, bh = box.offsetHeight, gap = 12;
    let top = r.bottom + gap, left = Math.min(Math.max(8, r.left), innerWidth - bw - 8);
    if (top + bh > innerHeight - 8) top = r.top - bh - gap;               // not enough room below: above
    if (top < 8) {  // target too tall for the box above or below: a bottom corner, away from the key content
      top = innerHeight - bh - 16;
      left = TOUR[tourIdx].corner === "left" ? 16 : innerWidth - bw - 16;
    }
    box.style.top = top + "px";
    box.style.left = left + "px";
  }

  function tourEnd() {
    if (tourEl) tourEl.classList.remove("tour-target");
    tourIdx = -1; tourEl = null;
    el("tour-shade").hidden = true;
    el("tour-box").hidden = true;
    el("tour-banner").hidden = true;
    store.set("hicp.tour", "done");
    showTab("overview");
    window.scrollTo(0, 0);
    el("tour-open").focus({ preventScroll: true });
  }

  el("tour-open").addEventListener("click", () => tourShow(0));
  el("tour-start").addEventListener("click", () => tourShow(0));
  el("tour-dismiss").addEventListener("click", () => { store.set("hicp.tour", "dismissed"); el("tour-banner").hidden = true; });
  el("tour-next").addEventListener("click", () => (tourIdx >= TOUR.length - 1 ? tourEnd() : tourShow(tourIdx + 1)));
  el("tour-back").addEventListener("click", () => { if (tourIdx > 0) tourShow(tourIdx - 1); });
  el("tour-skip").addEventListener("click", tourEnd);
  window.addEventListener("resize", tourPlace);
  window.addEventListener("scroll", tourPlace, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (tourIdx < 0) return;
    if (e.key === "Escape") { e.preventDefault(); tourEnd(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); el("tour-next").click(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); el("tour-back").click(); }
    else if (e.key === "Tab") {  // keep focus inside the dialog
      const f = [...el("tour-box").querySelectorAll("button:not([disabled])")];
      const k = f.indexOf(document.activeElement);
      e.preventDefault();
      f[(k + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
    }
  });
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => {
    lang = b.dataset.lang; store.set("hicp.lang", lang); renderAll();
    if (tourIdx >= 0) tourShow(tourIdx);  // re-translate the open step
  }));
  document.querySelectorAll("[data-theme-btn]").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeBtn)));
  document.querySelectorAll(".toggle-table").forEach((b) => b.addEventListener("click", () => {
    const tb = el(b.dataset.table); tb.hidden = !tb.hidden; b.textContent = tb.hidden ? t("table_show") : t("table_hide");
  }));
  el("bt-sample").addEventListener("change", renderModel);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (theme === "auto") renderAll(); });

  el("note-toggle").addEventListener("click", () => { const c = el("note-check"); c.hidden = !c.hidden; renderNote(); });
  // ------------------------------------------------------------------ one-page brief (print / save as PDF)
  // Built from what the page already shows, in the current language, always in the light theme so it prints well.
  async function openBrief() {
    el("brief-open").disabled = true;
    try { await buildBrief(); } finally { el("brief-open").disabled = false; }
  }
  async function buildBrief() {
    const prevTheme = document.documentElement.getAttribute("data-theme");
    document.documentElement.setAttribute("data-theme", "light");
    renderOverview(); renderDrivers();
    const img = async (id, h) => {  // without the on-screen range buttons
      const gd = el(id), lay = Object.assign({}, gd.layout, { margin: Object.assign({}, gd.layout.margin, { t: 8 }) });
      lay.xaxis = Object.assign({}, gd.layout.xaxis, { rangeselector: { visible: false } });
      return Plotly.toImage({ data: gd.data, layout: lay }, { format: "png", width: 1000, height: h, scale: 2 });
    };
    let fan = "", contrib = "";
    try { fan = await img("p-headline", 360); contrib = await img("p-contrib", 330); } catch (e) { /* charts optional */ }
    if (prevTheme) document.documentElement.setAttribute("data-theme", prevTheme); else document.documentElement.removeAttribute("data-theme");
    renderAll();
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const kpis = ["kpi-dec", "kpi-last", "kpi-ecb", "kpi-base"].map((id) => {
      const k = el(id);
      return `<div class="k"><div class="l">${esc(k.querySelector(".label").textContent)}</div><div class="v">${esc(k.querySelector(".value").textContent)}</div><div class="s">${esc(k.querySelector(".sub").textContent)}</div></div>`;
    }).join("");
    const probs = [3, 3.5, 4, 4.5, 5].map((x) => `<td>${probTxt(probOf(last.point, x))}%</td>`).join("");
    const m = (B.metrics || []).find((r) => r.model === "bottom_up" && r.h === 3 && r.sample === "full");
    const n = RN && RN.notes.find((x) => x.lang === lang);
    const note = n && n.verified && !RN.stale ? `<h2>${esc(n.title)}</h2>${n.body.split(/\n{2,}/).map((p) => `<p>${esc(p)}</p>`).join("")}` : "";
    const vint = M.vintages.filter((v) => ["index_ea", "item_weights", "country_weights"].includes(v.name)).map((v) => `${v.dataset} ${v.updated.slice(0, 10)}`).join(" · ");
    const html = (`<!doctype html><html lang="${lang}"><head><meta charset="utf-8"><title>${esc(t("brief_title"))} – ${esc(monthLabel(F.origin))}</title>
<style>@page{size:A4;margin:12mm} *{box-sizing:border-box} body{font:10.5pt/1.42 system-ui,-apple-system,"Segoe UI",sans-serif;color:#111;margin:0;background:#fff}
.wrap{max-width:186mm;margin:0 auto;padding:6mm 0} h1{font-size:16pt;margin:0} .sub{color:#555;font-size:9pt;margin:2px 0 8px}
h2{font-size:11pt;margin:10px 0 4px} p{margin:0 0 6px} .kp{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:6px 0}
.k{border:1px solid #ddd;border-radius:6px;padding:6px 8px}.k .l{font-size:8pt;color:#555}.k .v{font-size:15pt;font-weight:600}.k .s{font-size:7.5pt;color:#666}
img{width:100%;display:block} table{border-collapse:collapse;font-size:9pt} td,th{border-bottom:1px solid #e3e3e3;padding:2px 8px;text-align:right} th:first-child,td:first-child{text-align:left}
.foot{color:#666;font-size:7.5pt;border-top:1px solid #ddd;margin-top:8px;padding-top:4px} .two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media screen{body{background:#f3f3f3}.wrap{background:#fff;padding:12mm;margin:10px auto;box-shadow:0 2px 12px rgba(0,0,0,.15)}.noprint{text-align:center;margin:10px}}
@media print{.noprint{display:none}}</style></head><body>
<div class="wrap"><h1>${esc(t("title"))}</h1><div class="sub">${esc(t("brief_sub", { origin: monthLabel(F.origin), run: M.run_at.slice(0, 10) }))}</div>
<div class="kp">${kpis}</div>
<h2>${esc(t("answer_title"))}</h2><p>${esc(el("answer").textContent)}</p>
<h2>${esc(el("wc-title").textContent)}</h2><p>${esc(el("wc-text").textContent)}</p>
${fan ? `<img src="${fan}" alt="">` : ""}
<div class="two"><div><h2>${esc(t("brief_risks", { date: monthLabel(last.date) }))}</h2><table><tr><th>${esc(t("brief_thr"))}</th>${[3, 3.5, 4, 4.5, 5].map((x) => `<th>${pct(x, x % 1 ? 1 : 0)}</th>`).join("")}</tr><tr><td>P(&gt;)</td>${probs}</tr></table>
${m ? `<p style="margin-top:6px">${esc(t("brief_acc", { r: fmt(m.rmse, 2), rw: fmt(m.rmse_rw, 2), p: fmt(m.dm_p, 2), n: m.n }))}</p>` : ""}</div>
<div>${contrib ? `<img src="${contrib}" alt="">` : ""}</div></div>
${note}
<div class="foot">${esc(t("brief_foot", { vint, commit: M.code_version }))}</div></div></body></html>`);
    // Shown in an in-page preview (no pop-up to block); its own print() prints only the brief.
    const fr = el("brief-frame");
    fr.srcdoc = html;
    el("brief-view").hidden = false;
    el("brief-print").focus();
  }
  el("brief-open").addEventListener("click", openBrief);
  el("brief-print").addEventListener("click", () => el("brief-frame").contentWindow.print());
  el("brief-close").addEventListener("click", () => { el("brief-view").hidden = true; el("brief-open").focus(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !el("brief-view").hidden) el("brief-close").click(); });

  // ------------------------------------------------------------------ interview demo mode (#demo or Shift+D)
  // A presenter's script: each step sets the page up (tab, selection, scenario) and shows what to say.
  // No button: reviewers never see it. Nothing here calls a paid API; the Ask step only types the question.
  // Scroll once the tab switch has laid out (a short timer: animation frames stall in background tabs), and instantly: a smooth scroll started while
  // charts are still resizing ends up in the wrong place.
  const focusCard = (sel) => setTimeout(() => {
    const e = document.querySelector(sel); if (!e) return;
    openFold(e);
    const card = e.closest(".card") || e;
    window.scrollTo(0, Math.max(0, card.getBoundingClientRect().top + window.scrollY - 12));
    card.classList.add("ask-flash"); setTimeout(() => card.classList.remove("ask-flash"), 1800);
  }, 80);
  const DEMO_ALL = [
    { key: "answer", run: () => { showTab("overview"); window.scrollTo(0, 0); } },
    { key: "changed", run: () => { showTab("overview"); focusCard("#wc-card"); } },
    { key: "note", when: () => !el("note-card").hidden, run: () => { showTab("overview"); focusCard("#note-card"); } },
    { key: "prob", run: () => { showTab("overview"); focusCard("#t-prob"); } },
    { key: "beat", run: () => { showTab("overview"); focusCard("#bm-card"); el("bm-name").focus({ preventScroll: true }); } },
    { key: "fan", run: () => { showTab("overview"); focusCard("#p-headline"); } },
    { key: "month", run: () => { showTab("overview"); el("mx-month").value = "2022-10"; renderMonth(); focusCard("#mx-month"); } },
    { key: "october", run: () => { showTab("overview"); setOct(4.0); focusCard("#oct-in"); } },
    { key: "bridge", run: () => { setOct(P[0].point); showTab("drivers"); focusCard("#br-card"); } },
    { key: "drivers", run: () => { showTab("drivers"); focusCard("#p-contrib"); } },
    { key: "core", run: () => { showTab("drivers"); focusCard("#core-card"); } },
    { key: "profile", run: () => { showTab("countries"); cpGeo = "IT"; el("cp-country").value = "IT"; renderProfile(); focusCard("#cp-card"); } },
    { key: "heat", run: () => { showTab("shocks"); focusCard("#hm-card"); } },
    { key: "shock", run: () => {
      showTab("shocks"); scenario = JSON.parse(JSON.stringify(S.presets[1])); scenario.second_round = true; presetIdx = -1; activeLeg = 0;
      refreshAll(); focusCard("#p-shock"); } },
    { key: "reverse", run: () => { showTab("shocks"); el("rev-solve").value = "min"; renderReverse(); focusCard("#rev-card"); } },
    { key: "compare", run: () => { showTab("shocks"); focusCard("#cmp-card"); } },
    { key: "backtest", run: () => { showTab("model"); focusCard("#tbl-bt"); } },
    { key: "timemachine", run: () => { showTab("model"); tmIdx = Math.max(0, tmOrigins.indexOf("2022-06")); renderTM(); focusCard("#tm-card"); } },
    { key: "trust", run: () => { showTab("model"); focusCard("#tbl-r2"); } },
    { key: "recon", run: () => { showTab("model"); focusCard("#rc-card"); } },
    { key: "ledger", run: () => { showTab("model"); focusCard("#n-led"); } },
    { key: "ask", when: () => !el("ask-open").hidden, run: () => {
      if (el("ask-panel").hidden) askToggle(true, "ask-fab");
      el("ask-text").value = t("demo_ask_q"); } },
    { key: "brief", run: () => { if (!el("ask-panel").hidden) askToggle(false); showTab("overview"); window.scrollTo(0, 0); } },
  ];
  let DEMO = DEMO_ALL, demoIdx = -1;
  function demoShow(i) {
    if (demoIdx < 0) DEMO = DEMO_ALL.filter((s) => !s.when || s.when());
    demoIdx = Math.max(0, Math.min(DEMO.length - 1, i));
    const s = DEMO[demoIdx];
    el("demo-panel").hidden = false;
    el("demo-step").textContent = t("demo_step", { i: demoIdx + 1, n: DEMO.length });
    el("demo-title").textContent = t(`demo_${s.key}_t`);
    el("demo-notes").textContent = t(`demo_${s.key}_n`, { dec: pct(last.point, 1), base: sgn(last.base_effect_pp), mom: sgn(last.momentum_pp) });
    el("demo-back").disabled = demoIdx === 0;
    el("demo-next").textContent = demoIdx === DEMO.length - 1 ? t("tour_done") : t("tour_next");
    s.run();
  }
  function demoEnd() {
    el("demo-panel").hidden = true; demoIdx = -1; setOct(P[0].point);
    if (location.hash === "#demo") history.replaceState(null, "", location.href.split("#")[0]);
  }
  el("demo-next").addEventListener("click", () => (demoIdx >= DEMO.length - 1 ? demoEnd() : demoShow(demoIdx + 1)));
  el("demo-back").addEventListener("click", () => demoShow(demoIdx - 1));
  el("demo-exit").addEventListener("click", demoEnd);
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "");
    if (!typing && e.shiftKey && (e.key === "D" || e.key === "d")) { e.preventDefault(); demoIdx < 0 ? demoShow(0) : demoEnd(); return; }
    if (demoIdx < 0 || typing || tourIdx >= 0) return;
    if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); el("demo-next").click(); }
    else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); el("demo-back").click(); }
    else if (e.key === "Escape") demoEnd();
  });

  // ------------------------------------------------------------------ 5. PNG / CSV for every chart
  function chartCsv(gd) {
    const rows = [["series", "x", "y"]];
    (gd.data || []).forEach((tr, k) => {
      const meta = tr.meta || {};
      if (meta.csv === false || !tr.x || !tr.y) return;
      const name = meta.csvName || tr.name || `series ${k + 1}`;
      const horiz = tr.orientation === "h";
      for (let i = 0; i < tr.x.length; i++) rows.push([name, horiz ? tr.y[i] : tr.x[i], horiz ? tr.x[i] : tr.y[i]]);
    });
    const q = (v) => { const s = v === null || v === undefined ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    return rows.map((r) => r.map(q).join(",")).join("\n") + "\n";
  }
  document.querySelectorAll(".plot").forEach((p) => {
    const bar = node("div", { class: "dl-bar" });
    const png = node("button", { type: "button", class: "dl-btn", "data-i18n": "dl_png" });
    const csv = node("button", { type: "button", class: "dl-btn", "data-i18n": "dl_csv" });
    png.addEventListener("click", () => { if (p.data) Plotly.downloadImage(p, { format: "png", filename: p.id.replace(/^p-/, "hicp-"), scale: 2 }); });
    csv.addEventListener("click", () => {
      if (!p.data) return;
      const a = node("a", { href: URL.createObjectURL(new Blob([chartCsv(p)], { type: "text/csv" })), download: p.id.replace(/^p-/, "hicp-") + ".csv" });
      document.body.appendChild(a); a.click(); a.remove();
    });
    const ex = node("button", { type: "button", class: "dl-btn ask-explain", "data-i18n": "ask_explain", hidden: true });
    ex.addEventListener("click", () => askExplain(p));
    bar.append(png, csv, ex);
    p.after(bar);
  });
  window.__chartCsv = chartCsv;  // exposed for the automated check only

  // Tables: every table gets its own CSV (exactly what it shows), and the tables that carry a card on their own
  // (no chart beside them) also get "Explain this", with the same chart-context mechanism as the charts.
  const EXPLAIN_TABLES = new Set(["tbl-wc", "tbl-prob", "tbl-oct", "tbl-led", "tbl-bt", "tbl-r2", "tbl-rt", "tbl-sel", "tbl-val", "tbl-vin", "tbl-compare", "tbl-recon", "tbl-r3", "tbl-r4"]);
  function tableCsv(w) {
    const q = (v) => { const s = String(v).replace(/\s+/g, " ").trim(); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    return [...w.querySelectorAll("tr")].map((tr) => [...tr.children].map((c) => q(c.textContent)).join(",")).join("\n") + "\n";
  }
  window.__tableCsv = tableCsv;  // exposed for the automated check only
  document.querySelectorAll(".tablewrap").forEach((w) => {
    const bar = node("div", { class: "dl-bar" });
    const csv = node("button", { type: "button", class: "dl-btn", "data-i18n": "dl_csv_table" });
    csv.addEventListener("click", () => {
      if (!w.querySelector("tr")) return;
      const a = node("a", { href: URL.createObjectURL(new Blob([tableCsv(w)], { type: "text/csv" })), download: w.id.replace(/^tbl-/, "hicp-table-") + ".csv" });
      document.body.appendChild(a); a.click(); a.remove();
    });
    bar.appendChild(csv);
    if (EXPLAIN_TABLES.has(w.id)) {
      const ex = node("button", { type: "button", class: "dl-btn ask-explain", "data-i18n": "ask_explain", hidden: true });
      ex.addEventListener("click", () => askExplain(w));
      bar.appendChild(ex);
    }
    w.after(bar);
  });

  // ------------------------------------------------------------------ dashboard assistant (D34)
  // Answers come from /api/ask, which only uses the pipeline's fact sheet and checks every number against the
  // fact it cites. The button appears only if that route exists (GET answers 405 there, 404 on a static host).
  const askHist = [];
  let askBusy = false;

  function askAnswerNode(res) {
    const box = node("div", { class: "ask-msg bot" + (res.answerable ? "" : " muted") });
    const txt = res.answer;
    let pos = 0;
    for (const n of res.numbers || []) {
      const k = txt.indexOf(n.token, pos);
      if (k < 0) continue;
      box.append(txt.slice(pos, k));
      box.append(node("span", { class: "cite", tabindex: 0, title: `${n.fact_label} = ${fmt(n.fact_value, 3)}` }, n.token));
      pos = k + n.token.length;
    }
    box.append(txt.slice(pos));
    if (res.goto && !res.scenario_request) {  // a what-if gets its own "Open in the simulator" button below
      const tgt = el(res.goto.target), card = tgt && tgt.closest(".card");
      const name = (card && card.querySelector("h2") && card.querySelector("h2").textContent.trim()) || t("tab_" + res.goto.tab);
      const label = res.goto.country ? `${name} · ${geo(res.goto.country)}` : name;
      const go = node("button", { type: "button", class: "btn ask-goto" }, t("ask_goto", { name: label }));
      go.addEventListener("click", () => askGoto(res.goto));
      box.append(node("br"), go);
    }
    const nNum = (res.numbers || []).length;
    box.append(node("span", { class: "meta" }, nNum ? t("ask_checked", { n: nNum, model: res.model }) : t("ask_model", { model: res.model })));
    return box;
  }

  // Switch tab, open the right country if asked, scroll the section into view and flash it.
  const openFold = (e) => { const f = e && (e.closest("details.fold") || e.querySelector("details.fold")); if (f) f.open = true; };
  function askGoto(g) {
    showTab(g.tab);
    openFold(el(g.target));
    if (g.country) { cpGeo = g.country; el("cp-country").value = g.country; renderProfile(); }
    const tgt = el(g.target);
    if (!tgt) return;
    const card = tgt.closest(".card") || tgt;
    if (window.matchMedia("(max-width: 700px)").matches) askToggle(false);  // the panel covers the page on phones
    card.scrollIntoView({ block: "start", behavior: "smooth" });
    card.classList.add("ask-flash");
    setTimeout(() => card.classList.remove("ask-flash"), 1800);
  }

  // A what-if question: the scenario interpreter (/api/scenario) turns the words into a scenario, and the
  // impact numbers below come from ShockEngine.simulate in the page, never from the language model.
  // A what-if the interpreter could not finish (e.g. no size given) waits for the next message, which is then
  // read together with it: "oil shock" then "+40%" becomes "oil shock +40%".
  let askPendingWhatIf = null;

  async function askScenario(q) {
    el("ask-status").textContent = t("ask_building");
    const { r, body } = await apiPost("/api/scenario", { text: q });
    el("ask-status").textContent = "";
    if (!r.ok || !body.scenario) {
      askPendingWhatIf = r.status === 422 ? q : null;
      askLog(node("div", { class: "ask-msg bot muted" }, (body.error || t("ask_sc_failed")) + (askPendingWhatIf ? " " + t("ask_sc_followup") : "")));
      return;
    }
    askPendingWhatIf = null;
    askScenarioResult(body.scenario, body.interpretation || [], t("ask_sc_meta", { model: body.model }));
  }

  // A preset needs no interpreter: the page already has it.
  const presetBase = (k) => S.presets[k].name.split("(")[0].trim().toLowerCase();
  const presetIn = (q) => { const s = q.toLowerCase(); return S.presets.findIndex((_, k) => s.includes(presetBase(k))); };
  // The preset as it stands fits only if the question adds no number of its own once the preset's name is removed.
  const presetAsIs = (q, k) => !/\d/.test(q.toLowerCase().replace(S.presets[k].name.toLowerCase(), "").replace(presetBase(k), ""));

  function askScenarioResult(sc, interpretation, meta) {
    const res = ShockEngine.simulate(sc, S), k = S.months.indexOf(last.date);
    const box = node("div", { class: "ask-msg bot" });
    box.append(node("b", {}, t("ask_sc_title")));
    const ul = node("ul", { class: "ask-sc-lines" });
    interpretation.forEach((l) => ul.appendChild(node("li", {}, l)));
    box.append(ul);
    const lines = [
      t("ask_sc_peak", { pp: sgn(res.peak_pp), month: monthLabel(res.peak_month) }),
      t("ask_sc_dec", { date: monthLabel(last.date), pp: sgn(res.delta_yoy_pp[k]), y: pct(res.shocked_yoy[k]), base: pct(last.point) }),
      t("ask_sc_prob", { thr: fmt(thr, 1), p: probTxt(probOf(res.shocked_yoy[k], thr)), b: probTxt(probOf(last.point, thr)) }),
    ];
    lines.forEach((l) => box.append(node("div", {}, l)));
    const open = node("button", { type: "button", class: "btn ask-goto" }, t("ask_sc_open"));
    open.addEventListener("click", () => {
      scenario = JSON.parse(JSON.stringify(sc)); presetIdx = -1; activeLeg = 0;
      el("presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
      askGoto({ tab: "shocks", target: "p-shock", country: null });
      refreshAll();
    });
    const link = node("button", { type: "button", class: "btn ask-goto" }, t("share_copy"));
    link.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(shareUrl(sc)); link.textContent = t("ask_sc_copied"); }
      catch (e) { history.replaceState(null, "", shareUrl(sc)); link.textContent = t("ask_sc_inbar"); }
    });
    box.append(node("div", { class: "row", style: "gap:6px;margin-top:2px" }, undefined));
    box.lastChild.append(open, link);
    box.append(node("span", { class: "meta" }, meta));
    askLog(box);
    askHist.push({ role: "assistant", content: lines.join(" ") });
  }

  // "Explain" on a chart: the question names the chart; the server adds what it shows, and the page sends the
  // selection and any numbers it computed itself (the current shock, a chosen month) as page facts.
  function chartContext(pid) {
    const F_ = (id, label, value) => ({ id: "page_" + id, label, value });
    if (pid === "p-shock" || pid === "p-shockpath") {
      const r = ShockEngine.simulate(scenario, S), k = S.months.indexOf(last.date);
      return { state: `${scenario.name}: ${scenario.legs.map(legLabel).join("; ")}${scenario.second_round ? " (with second round)" : ""}`,
        facts: [F_("peak_pp", `Peak impact of the current shock on headline y/y (${r.peak_month}), pp`, r.peak_pp),
          F_("dec_pp", `Impact of the current shock on ${last.date} headline y/y, pp`, r.delta_yoy_pp[k]),
          F_("dec_first_pp", `First-round part of that impact, pp`, r.delta_first_round_pp[k]),
          F_("dec_second_pp", `Second-round part of that impact, pp`, r.delta_second_round_pp[k]),
          F_("dec_shocked", `Headline y/y in ${last.date} with the shock, %`, r.shocked_yoy[k]),
          F_("n_legs", "Number of shocks (legs) in the scenario", scenario.legs.length)] };
    }
    if (pid === "p-compare" || pid === "tbl-compare") {
      const k = S.months.indexOf(last.date), all = Object.fromEntries(cmpAll().map((x) => [x.id, x])), facts = [];
      [...cmpSel.keys()].forEach((id, i) => {
        const x = all[id]; if (!x) return;
        const r = ShockEngine.simulate(x.scenario, S);
        facts.push(F_(`s${i + 1}_peak`, `Peak impact of scenario '${x.name}', pp`, r.peak_pp), F_(`s${i + 1}_dec`, `Impact of '${x.name}' on ${last.date}, pp`, r.delta_yoy_pp[k]),
          F_(`s${i + 1}_level`, `${last.date} y/y under '${x.name}', %`, r.shocked_yoy[k]));
      });
      return { state: `compared: ${[...cmpSel.keys()].map((id) => (all[id] || {}).name).join("; ")}`, facts };
    }
    if (pid === "p-month") {
      const m = el("mx-month").value, ex = ShockEngine.explainMonth(F.headline_index, m);
      return { state: `month ${m}`, facts: [F_("m_yoy", `Headline y/y in ${m}, %`, ex.yoy),
        F_("m_dyoy", `Change in y/y from the previous month to ${m}, pp`, ex.delta_pp),
        F_("m_mom", `Momentum part of that change, pp`, ex.momentum_pp), F_("m_base", `Base-effect part of that change, pp`, ex.base_effect_pp)] };
    }
    if (pid === "p-cp-drivers" || pid === "p-cp-basket") return { state: `country ${geo(cpGeo)} (${cpGeo})`, facts: [] };
    if (pid === "p-ccmp") return { state: `countries ${[...ccSel.keys()].map((g) => `${geo(g)} (${g})`).join(", ") || "none selected"}`, facts: [] };
    if (pid === "p-track") return { state: `horizon ${trackH} months`, facts: [] };  // track-h is a button group, not an input
    if (EXPLAIN_TABLES.has(pid)) return { state: "", facts: [] };
    return { state: "", facts: [] };
  }

  function askExplain(p) {
    const card = p.closest(".card"), h = card && card.querySelector("h2");
    const title = (h && h.textContent.trim()) || p.id;
    const ctx = chartContext(p.id);
    if (el("ask-panel").hidden) askToggle(true, "ask-fab");
    // What is drawn, read from the chart itself so the explanation never guesses at styles.
    const traces = (p.data || []).filter((tr) => !(tr.meta && tr.meta.csv === false) && (tr.name || tr.type === "bar")).map((tr) => {
      const kind = tr.type === "bar" ? "bars" : (tr.fill && tr.fill !== "none") ? "shaded band"
        : `${tr.line && tr.line.dash && tr.line.dash !== "solid" ? tr.line.dash + " " : "solid "}line${/markers/.test(tr.mode || "") ? " with markers" : ""}`;
      return `${kind}${tr.name ? ": " + tr.name : ""}`;
    }).filter((x, i, a) => a.indexOf(x) === i);
    askSend(t("ask_explain_q", { title }), { chart: p.id, chart_state: ctx.state, chart_facts: ctx.facts, chart_traces: traces });
  }

  function askLog(n) { const log = el("ask-log"); log.appendChild(n); log.scrollTop = log.scrollHeight; }

  async function askSend(q, extra) {
    q = (q || el("ask-text").value).trim();
    if (!q) return;
    if (askBusy) { el("ask-status").textContent = t("ask_wait"); return; }  // e.g. a second Explain click
    askBusy = true; el("ask-go").disabled = true; el("ask-text").value = "";
    askLog(node("div", { class: "ask-msg user" }, q));
    el("ask-suggest").hidden = true;  // the examples have done their job; give the answers the room
    // Only a bare fragment completes it ("+40%", "40 % for six months"), not a new question that happens to hold a digit.
    if (askPendingWhatIf && !extra && q.length <= 40 && !q.includes("?") && /^[\s+\-−%]*\d/.test(q)) {
      const whole = `${askPendingWhatIf} ${q}`;
      askPendingWhatIf = null;
      try { await askScenario(whole); } finally { askBusy = false; el("ask-go").disabled = false; }
      return;
    }
    askPendingWhatIf = null;
    el("ask-status").textContent = t("ask_busy");
    try {
      const { r, body } = await apiPost("/api/ask", Object.assign({ question: q, history: askHist.slice(-4) }, extra || {}));
      el("ask-status").textContent = "";
      if (!r.ok) { askLog(node("div", { class: "ask-msg bot muted" }, liveError(r, body, "ask"))); return; }
      if (!body.verified) { askLog(node("div", { class: "ask-msg bot muted" }, t("ask_unverified"))); return; }
      askLog(askAnswerNode(body));
      askHist.push({ role: "user", content: q }, { role: "assistant", content: body.answer });
      const named = presetIn(q), bare = named >= 0 && q.length <= presetBase(named).length + 12;
      if (body.scenario_request || (!body.answerable && bare)) {  // a bare preset name is a what-if too
        const k0 = Number.isInteger(body.preset) && S.presets[body.preset] ? body.preset : named;
        const k = k0 >= 0 && presetAsIs(q, k0) ? k0 : -1;  // any other number (a size, a date) goes to the interpreter
        if (k >= 0) {
          const pre = S.presets[k];
          askScenarioResult(JSON.parse(JSON.stringify(pre)), [t("ask_sc_preset", { name: pre.name }), pre.rationale], t("ask_sc_meta_preset"));
        } else await askScenario(q);
      }
    } catch (e) {
      el("ask-status").textContent = ""; askLog(node("div", { class: "ask-msg bot muted" }, t("ask_failed")));
    } finally { askBusy = false; el("ask-go").disabled = false; }
  }

  function renderAsk() {
    el("ask-text").placeholder = t("ask_placeholder");
    el("ask-code").placeholder = t("code_placeholder"); el("nl-code").placeholder = t("code_placeholder");
    el("ask-fab").setAttribute("aria-label", t("ask_title")); el("ask-fab").title = t("ask_title");
    el("ask-suggest").replaceChildren(...[t("ask_s1"), t("ask_s2"), t("ask_s3"), t("ask_s4")].map((q) => {
      const b = node("button", { type: "button" }, q);
      b.addEventListener("click", () => askSend(q));
      return b;
    }));
  }

  let askFrom = "ask-fab";  // focus goes back to whichever button opened the panel
  function askToggle(open, from) {
    if (from) askFrom = from;
    el("ask-panel").hidden = !open;
    el("ask-fab").hidden = open;  // the panel sits where the round button is
    ["ask-open", "ask-fab"].forEach((id) => el(id).setAttribute("aria-expanded", String(open)));
    if (open) el("ask-text").focus(); else el(askFrom).focus();
  }

  if (liveOk()) {
    fetch("/api/ask", { method: "GET" }).then((r) => {
      bmLoad().then(() => { if (activeTab === "overview") renderBeat(); });
      if (r.status === 405) {
        el("ask-open").hidden = false; el("ask-fab").hidden = false;
        document.querySelectorAll(".ask-explain").forEach((b) => { b.hidden = false; });
      }
    }).catch(() => {});
  }
  el("ask-open").addEventListener("click", () => askToggle(el("ask-panel").hidden, "ask-open"));
  el("ask-fab").addEventListener("click", () => askToggle(true, "ask-fab"));
  el("ask-code-go").addEventListener("click", () => unlock(false));
  el("ask-code").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); unlock(false); } });
  el("nl-code-go").addEventListener("click", () => unlock(true));
  el("nl-code").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); unlock(true); } });
  el("ask-close").addEventListener("click", () => askToggle(false));
  el("ask-go").addEventListener("click", () => askSend());
  el("ask-text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askSend(); }
    else if (e.key === "Escape") askToggle(false);
  });

  document.querySelectorAll("details.fold").forEach((f) => f.addEventListener("toggle", () => {
    if (f.open) setTimeout(() => f.querySelectorAll(".plot").forEach((p) => { if (p.data) Plotly.Plots.resize(p); }), 0);
  }));
  el("mx-month").addEventListener("change", renderMonth);
  el("oct-in").addEventListener("input", () => setOct(Number(el("oct-in").value)));
  el("oct-range").addEventListener("input", () => setOct(Number(el("oct-range").value)));
  el("oct-reset").addEventListener("click", () => setOct(P[0].point));
  el("cc-add").addEventListener("change", () => { const g = el("cc-add").value; if (g) ccToggle(g); });
  el("cp-country").addEventListener("change", () => { cpGeo = el("cp-country").value; renderProfile(); });
  bindThreshold();
  buildForm();
  if (theme !== "auto") document.documentElement.setAttribute("data-theme", theme);
  const shared = loadShared();
  renderAll();
  if (location.hash === "#demo") setTimeout(() => demoShow(0), 600);  // after the Ask probe has answered
  else if (shared) showTab("shocks");
  else if (store.get("hicp.tour", null) === null) el("tour-banner").hidden = false;
})();
