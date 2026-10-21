/* End-to-end check of every dashboard feature, run inside the page (served by deploy/serve_local.py).
 *
 * Paste into the browser console, or run it through a browser automation tool, on a fresh load of
 * http://127.0.0.1:8812/. It never makes a paid call: POSTs to /api/ask and /api/scenario are answered by stubs
 * below, so the page logic (routing, rendering, verification display, navigation) is what is tested. The real
 * routes are covered by tests/test_ask.py, test_access_code.py and test_deploy_function.py.
 *
 * Returns { passed, failed, results: [{ name, ok, detail }] }.
 */
(async () => {
  const results = [];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const el = (id) => document.getElementById(id);
  const ok = (name, cond, detail = "") => results.push({ name, ok: !!cond, detail: String(detail).slice(0, 160) });
  const step = async (name, fn) => { try { await fn(); } catch (e) { results.push({ name, ok: false, detail: "threw: " + e.message }); } };
  const tab = async (name) => { $(`[data-tab=${name}]`).click(); await sleep(700); };
  const setVal = (input, v, ev = "input") => { input.value = v; input.dispatchEvent(new Event(ev, { bubbles: true })); };
  const visibleText = (n) => (n ? n.textContent.trim() : "");
  const errors = [];
  window.addEventListener("error", (e) => errors.push(e.message));
  const D = JSON.parse(el("dashboard-data").textContent);

  // ---- stubs for the paid routes (records what the page sends)
  const sent = [];
  const realFetch = window.fetch;
  let stubMode = "normal", codeIssued = false;  // "locked": like a site with a code; only the code issued in this run works
  window.fetch = async (u, o = {}) => {
    if (o.method !== "POST") return realFetch(u, o);
    const b = JSON.parse(o.body); sent.push([u, b]);
    const J = (x, s = 200) => new Response(JSON.stringify(x), { status: s, headers: { "Content-Type": "application/json" } });
    if (stubMode === "locked" && !(codeIssued && b.access_code === "e2e-code")) return J({ error: "Access code required.", code_required: true }, 401);
    if (u === "/api/ask") {
      const q = b.question || "";
      if (/what if|shock/i.test(q)) return J({ answerable: true, verified: true, answer: "Building it.", numbers: [], goto: null, scenario_request: true, preset: null, model: "stub", attempts: 1 });
      if (/germany/i.test(q)) return J({ answerable: true, verified: true, answer: `Germany contributes ${D.countries.contributions.DE.slice(-1)[0].toFixed(2)} pp.`,
        numbers: [{ token: D.countries.contributions.DE.slice(-1)[0].toFixed(2), fact_id: "DE_contrib", fact_label: "Germany contribution", fact_value: D.countries.contributions.DE.slice(-1)[0], ok: true }],
        goto: { id: "country_profile", tab: "countries", target: "cp-card", country: "DE" }, scenario_request: false, preset: null, model: "stub", attempts: 1 });
      return J({ answerable: true, verified: true, answer: "Stub answer.", numbers: [], goto: null, scenario_request: false, preset: null, model: "stub", attempts: 1 });
    }
    if (u === "/api/scenario") {
      if (!/\d/.test(b.text)) return J({ error: "No size found." }, 422);
      return J({ scenario: { name: "Stub gas DE", legs: [{ components: ["ELC_GAS"], countries: ["DE"], size_pct: 30, profile: { kind: "permanent" }, start: D.basis.months[0] }],
        second_round: false, second_round_regime: "post2020", rationale: "Stub interpretation for the end-to-end test.", sources: ["stub"], mapping: null },
        interpretation: ["stub", "Applies to ELC_GAS in DE, from 2026-11."], intent: {}, model: "stub" });
    }
    return J({ error: "unknown" }, 404);
  };
  await sleep(1200);  // let the /api/ask probe answer

  // ---------------------------------------------------------------- A. load
  await step("load: header, KPIs, answer, footer", async () => {
    ok("4 KPI cards filled", ["kpi-dec", "kpi-last", "kpi-ecb", "kpi-base"].every((id) => /\d/.test(visibleText(el(id)))));
    ok("answer paragraph", visibleText(el("answer")).length > 80, visibleText(el("answer")).slice(0, 60));
    ok("footer has vintage and commit", /\d{4}-\d{2}-\d{2}/.test(visibleText(el("footer"))), visibleText(el("footer")));
    ok("Ask button + round button visible (live server)", !el("ask-open").hidden && !el("ask-fab").hidden);
  });

  // every tab: every chart has data, every table has rows
  const charts = {};
  for (const t of ["overview", "drivers", "countries", "shocks", "model"]) {
    await step(`tab ${t}: charts and tables render`, async () => {
      await tab(t);
      const plots = $$(`#tab-${t} .plot`);
      const empty = plots.filter((p) => !p.data || !p.data.length).map((p) => p.id);
      charts[t] = plots.map((p) => p.id);
      ok(`${t}: all ${plots.length} charts have data`, empty.length === 0, empty.join(","));
      const overflow = plots.filter((p) => { const s = p.querySelector(".main-svg"); return s && s.getBoundingClientRect().width > p.getBoundingClientRect().width + 2; }).map((p) => p.id);
      ok(`${t}: no chart wider than its card`, overflow.length === 0, overflow.join(","));
      ok(`${t}: no horizontal page scroll`, document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        `${document.documentElement.scrollWidth} > ${document.documentElement.clientWidth}`);
      const tables = $$(`#tab-${t} .tablewrap`).filter((w) => !w.hidden && !w.closest("[hidden]"));
      const emptyT = tables.filter((w) => !w.querySelector("tbody tr")).map((w) => w.id);
      ok(`${t}: visible tables have rows`, emptyT.length === 0, emptyT.join(","));
      const raw = [...el(`tab-${t}`).querySelectorAll("*")].filter((n) => n.children.length === 0 && !n.closest("table") && /^[a-z]+(_[a-z0-9]+)+$/.test(n.textContent.trim()));
      ok(`${t}: no untranslated i18n keys`, raw.length === 0, raw.slice(0, 3).map((n) => n.textContent).join(","));
    });
  }

  // ---------------------------------------------------------------- B. overview
  await tab("overview");
  await step("overview: research note and what-changed", async () => {
    ok("research note shown", !el("note-card").hidden && visibleText(el("note-body")).length > 100);
    ok("what changed sentence", /printed|sorti/.test(visibleText(el("wc-text"))), visibleText(el("wc-text")).slice(0, 70));
    ok("what changed table rows", $$("#tbl-wc tbody tr").length >= 8);
  });
  await step("overview: threshold changes the probability", async () => {
    const thr = $("input.thr"), before = visibleText(el("prob-sentence"));
    setVal(thr, "3.5"); await sleep(200);
    ok("probability sentence updates", visibleText(el("prob-sentence")) !== before);
    setVal(thr, "4"); await sleep(200);
  });
  await step("overview: month explained via menu and chart click", async () => {
    setVal(el("mx-month"), "2022-10", "change"); await sleep(300);
    ok("month menu → sentence", /2022/.test(visibleText(el("mx-sentence"))), visibleText(el("mx-sentence")).slice(0, 60));
    el("p-headline").emit("plotly_click", { points: [{ x: "2023-03-01" }] }); await sleep(300);
    ok("headline click → month", el("mx-month").value === "2023-03", el("mx-month").value);
  });
  await step("overview: October what-if", async () => {
    const n0 = el("p-headline").data.length, s0 = visibleText(el("oct-sentence"));
    setVal(el("oct-in"), "4.0"); await sleep(300);
    ok("adds the conditional path", el("p-headline").data.length > n0);
    ok("sentence changes", visibleText(el("oct-sentence")) !== s0);
    el("oct-reset").click(); await sleep(300);
    ok("reset restores", el("p-headline").data.length === n0);
  });
  await step("overview: October box validates its input (D61)", async () => {
    const s0 = visibleText(el("oct-sentence"));
    for (const bad of ["", "-1", "12"]) {
      setVal(el("oct-in"), bad); await sleep(150);
      ok(`October '${bad}' refused with a message`, !el("oct-warn").hidden && visibleText(el("oct-sentence")) === s0);
    }
    el("oct-reset").click(); await sleep(200);
    ok("reset clears the message", el("oct-warn").hidden);
    setVal(el("oct-in"), "4.2"); await sleep(250);
    ok("a what-if shows a chip above the chart", !el("oct-chip").hidden && el("p-headline").data.length > 0);
    const n1 = el("p-headline").data.length;
    el("oct-chip-rm").click(); await sleep(300);
    ok("Remove takes the what-if line off", el("oct-chip").hidden && el("p-headline").data.length === n1 - 1);
    ok("slider covers the same 0–8 range", el("oct-range").min === "0" && el("oct-range").max === "8");
  });
  await step("live: health route answers 200 (D61)", async () => {
    const r = await fetch("/api/health"); const h = await r.json();
    ok("GET /api/health is 200 with live=true", r.status === 200 && h.live === true);
  });
  await step("overview: range buttons on the headline chart", async () => {
    ok("rangeselector present", !!(el("p-headline").layout.xaxis.rangeselector || {}).buttons);
    // All → 1Y → 3Y must stay on the data (D62: autorange had pushed the end to 2030, leaving 1Y empty).
    const g = el("p-headline"), rb = (lab) => [...g.querySelectorAll(".rangeselector .button")].find((b) => b.textContent.trim() === lab);
    const dmax = Math.max(...g.data.flatMap((d) => d.x || []).map((x) => new Date(x).getTime()).filter(Number.isFinite));
    const ends = [];
    for (const lab of ["All", "1Y", "3Y", "All", "1Y"]) {
      if (!rb(lab)) continue;
      rb(lab).dispatchEvent(new MouseEvent("click", { bubbles: true })); await sleep(350);
      ends.push(Math.round((new Date(g.layout.xaxis.range[1]).getTime() - dmax) / 864e5));
    }
    ok("range buttons in any order end at the data", ends.length === 5 && ends.every((d) => d >= 0 && d <= 40), ends.join(","));
    rb("3Y") && rb("3Y").dispatchEvent(new MouseEvent("click", { bubbles: true })); await sleep(300);
    const yr = el("p-headline").layout.yaxis.range || [];
    ok("y-axis fitted to the visible window", yr.length === 2 && yr[1] - yr[0] < 7, JSON.stringify(yr));
  });

  // Floating-bar bridge (D59): each step is a bar of |change| from the running total; walk it and land on the end bar.
  const bridgeAddsUp = (tr) => {
    const y = tr.orientation === "h" ? tr.x : tr.y, b = tr.base; let cum = y[0];
    for (let i = 1; i < y.length - 1; i++) {
      if (Math.abs(b[i] - cum) < 1e-9) cum += y[i]; else if (Math.abs(b[i] + y[i] - cum) < 1e-9) cum -= y[i]; else return false;
    }
    return Math.abs(cum - y[y.length - 1]) < 1e-6;
  };
  await step("overview: revision waterfall adds up for each choice", async () => {
    const btns = $$("#wc-pick button"), bad = [];
    for (const b of btns) {
      b.click(); await sleep(250);
      if (!bridgeAddsUp(el("p-revision").data[0])) bad.push(b.textContent);
    }
    ok(`${btns.length} surprise/revision waterfalls add up`, btns.length >= 2 && bad.length === 0, bad.join(","));
  });
  await step("overview: beat the model (no shared store locally)", async () => {
    try { localStorage.removeItem("hicp.guess"); } catch (e) { /* ignore */ }
    el("bm-name").value = "E2E tester"; el("bm-value").value = "3.95"; el("bm-go").click(); await sleep(600);
    ok("guess saved and listed", $$("#tbl-guess tbody tr").some((r) => r.textContent.includes("E2E tester")), visibleText(el("bm-status")));
    ok("guess drawn on the band chart", (el("p-guess").data[3].x || []).includes(3.95));
    el("bm-value").value = "99"; el("bm-go").click(); await sleep(200);
    ok("out-of-range guess refused", /between|entre/.test(visibleText(el("bm-status"))));
    try { localStorage.removeItem("hicp.guess"); } catch (e) { /* ignore */ }
  });

  // ---------------------------------------------------------------- C. drivers
  await tab("drivers");
  await step("drivers: bridge chart, both modes add up", async () => {
    const tr = () => el("p-bridge").data[0];
    ok("by component sums to the change", bridgeAddsUp(tr()));
    ok("bars coloured per component", new Set(tr().marker.color).size >= 4);
    $("[data-br=bm]").click(); await sleep(300);
    ok("base effect + momentum sums to the change", tr().base.length === 4 && bridgeAddsUp(tr()));
    $("[data-br=comp]").click(); await sleep(200);
  });
  await step("drivers: contributions click → month explained", async () => {
    el("p-contrib").emit("plotly_click", { points: [{ x: "2022-10-01" }] }); await sleep(500);
    ok("switched to overview at Oct 2022", $("[role=tab][aria-selected=true]").dataset.tab === "overview" && el("mx-month").value === "2022-10");
    await tab("drivers");
  });
  await step("drivers: core inflation card", async () => {
    ok("core text", /2\.\d/.test(visibleText(el("core-text"))), visibleText(el("core-text")).slice(0, 60));
    ok("core table 3 horizons", $$("#tbl-core tbody tr").length === 3);
    ok("core verdict", visibleText(el("core-verdict")).length > 40);
  });

  // ---------------------------------------------------------------- D. countries
  await tab("countries");
  await step("countries: compare add/remove keeps colours", async () => {
    const chips = () => $$("#cc-chips label, #cc-chips .chip, #cc-chips > *").length;
    const c0 = chips();
    const color = (name) => (el("p-ccmp").data.find((tr) => tr.name === name) || {}).line?.color;
    const itBefore = color(D.i18n.en.g_IT) || color(D.i18n.fr.g_IT);
    const first = $$("#cc-chips .chip-x")[0];
    if (first) { first.click(); await sleep(300); }
    ok("remove a country", chips() === c0 - 1, `${c0} → ${chips()}`);
    const opt = [...el("cc-add").options].find((o) => o.value === "ES");
    if (opt) { setVal(el("cc-add"), "ES", "change"); await sleep(300); }
    ok("add a country", chips() === c0, chips());
    const itAfter = color(D.i18n.en.g_IT) || color(D.i18n.fr.g_IT);
    ok("colour follows the country", !itBefore || itBefore === itAfter, `${itBefore} vs ${itAfter}`);
  });
  await step("countries: small multiple click → profile; menu; Italy warning", async () => {
    const xs = el("p-csm").data.map((tr) => tr.xaxis);
    const k = [...new Set(xs)].indexOf("x12");
    el("p-csm").emit("plotly_click", { points: [{ data: { xaxis: "x12" }, x: "2024-01-01" }] }); await sleep(500);
    ok("click opens a profile", el("cp-country").value !== "", el("cp-country").value);
    setVal(el("cp-country"), "IT", "change"); await sleep(400);
    ok("Italy warning shown", !el("cp-warn").hidden);
    setVal(el("cp-country"), "DE", "change"); await sleep(400);
    ok("Germany: summary + sensitivity table", /Germany|Allemagne/.test(visibleText(el("cp-summary"))) && $$("#tbl-cp-sens tbody tr").length === 6);
    ok("no Italy warning for Germany", el("cp-warn").hidden);
  });

  // ---------------------------------------------------------------- E. shocks
  await tab("shocks");
  await step("shocks: every preset runs", async () => {
    const btns = $$("#presets button"), peaks = [];
    for (const b of btns) { b.click(); await sleep(250); peaks.push(visibleText(el("k-peak"))); }
    ok(`${btns.length} presets give distinct peaks`, new Set(peaks).size === btns.length, peaks.join(" | ").slice(0, 150));
  });
  await step("shocks: build a multi-leg shock", async () => {
    const legs = () => $$("#leg-strip button").length;
    const l0 = legs();
    el("leg-add").click(); await sleep(250);
    ok("add a leg", legs() === l0 + 1);
    setVal(el("f-size"), "25"); await sleep(250);
    ok("legs table shown for 2+ legs", !el("legs-block").hidden);
    el("leg-del").click(); await sleep(250);
    ok("delete a leg", legs() === l0);
    const p0 = visibleText(el("k-peak"));
    el("f-second").checked = !el("f-second").checked; el("f-second").dispatchEvent(new Event("input", { bubbles: true })); await sleep(250);
    ok("second round changes the result", visibleText(el("k-peak")) !== p0);
  });
  await step("shocks: reverse stress test solves and applies", async () => {
    $$("#presets button")[0].click(); await sleep(300);
    setVal(el("rev-y"), "4.5"); await sleep(400);
    ok("solution sentence", visibleText(el("rev-out")).length > 20, visibleText(el("rev-out")).slice(0, 70));
    if (!el("rev-apply").hidden) {
      const s0 = el("f-size").value; el("rev-apply").click(); await sleep(300);
      ok("apply sets the size", el("f-size").value !== s0, `${s0} → ${el("f-size").value}`);
    } else ok("apply button available", false, "hidden");
  });
  await step("shocks: reverse stress across all shocks", async () => {
    $$("#presets button")[0].click(); await sleep(250);
    el("leg-add").click(); await sleep(250);
    setVal(el("rev-y"), "4.6"); setVal(el("rev-solve"), "min"); await sleep(500);
    ok("smallest-combination sentence lists both shocks", /1\..*2\./.test(visibleText(el("rev-out"))) && !el("rev-apply").hidden, visibleText(el("rev-out")).slice(0, 90));
    el("rev-apply").click(); await sleep(400);
    ok("applying reaches the target", /4[.,]6/.test(visibleText(el("k-shocked"))), visibleText(el("k-shocked")));
    setVal(el("rev-solve"), "equal"); await sleep(400);
    const sizes = (visibleText(el("rev-out")).match(/[+−-]\d+[.,]\d%/g) || []);
    ok("same-size mode gives equal sizes", sizes.length >= 2 && new Set(sizes).size === 1, sizes.join(" "));
    setVal(el("rev-solve"), "one"); el("leg-del").click(); await sleep(250);
  });
  await step("shocks: scenario comparison save / select / colours", async () => {
    try { localStorage.removeItem("hicp.scenarios"); } catch (e) { /* ignore */ }
    $$("#presets button")[1].click(); await sleep(250);
    setVal(el("f-size"), "33"); await sleep(250);
    el("cmp-name").value = "E2E bear"; el("cmp-save").click(); await sleep(400);
    const names = () => el("p-compare").data.map((tr) => tr.name);
    ok("saved scenario is drawn", names().includes("E2E bear"), names().join(","));
    const colour = (n) => (el("p-compare").data.find((tr) => tr.name === n) || {}).line?.color;
    const c0 = colour("E2E bear");
    $$("#cmp-list input")[0].click(); await sleep(300);
    ok("unticking another keeps this colour", colour("E2E bear") === c0);
    ok("comparison table: baseline + rows", $$("#tbl-compare tbody tr").length === names().length + 1);
    const del = $$("#cmp-list .chip-x").filter((b) => b.textContent === "×")[0]; if (del) { del.click(); await sleep(300); }
    ok("delete removes it", !names().includes("E2E bear"));
    try { localStorage.removeItem("hicp.scenarios"); } catch (e) { /* ignore */ }
  });
  await step("shocks: shock size is bounded, never silently zero (D61)", async () => {
    const dec0 = visibleText(el("k-dec")), size0 = el("f-size").value;
    for (const bad of ["-100", "1000", "", "abc"]) {
      setVal(el("f-size"), bad); await sleep(150);
      ok(`size '${bad}' refused with a message`, !el("size-warn").hidden && visibleText(el("k-dec")) === dec0);
    }
    setVal(el("f-size"), size0); await sleep(150);
    ok("valid size clears the message", el("size-warn").hidden);
  });
  await step("shocks: heatmap labels every row and column (D61)", async () => {
    const H = el("p-heat");
    ok("every country labelled", (H.layout.yaxis.tickvals || []).length === H.data[0].y.length && H.data[0].y.length === 21);
    ok("component names on top", H.layout.xaxis.side === "top");
  });
  await step("shocks: heatmap click opens the cell", async () => {
    const before = JSON.stringify(D.basis.presets[0].legs[0]);
    el("p-heat").emit("plotly_click", { points: [{ customdata: ["FR", "SERV"] }] }); await sleep(400);
    ok("FR services +10% loaded", el("f-size").value === "10" && $("#f-countries input[value=FR]").checked);
    ok("replacement is announced with Undo", !el("heat-notice").hidden && !!$("#heat-notice button"));
    $("#heat-notice button").click(); await sleep(300);
    ok("Undo restores the previous scenario", el("heat-notice").hidden && !($("#f-countries input[value=FR]").checked && el("f-size").value === "10"), before.slice(0, 40));
    el("p-heat").emit("plotly_click", { points: [{ customdata: ["FR", "SERV"] }] }); await sleep(400);
  });
  await step("shocks: share link carries threshold and the reader's rationale (D64)", async () => {
    const box = el("sim-rat-edit");
    ok("custom scenario has a rationale box", !!box);
    if (box) { setVal(box, "E2E: why this scenario"); }
    setVal(el("f-size"), "12"); await sleep(200);
    ok("typed rationale survives an edit", el("sim-rat-edit") && el("sim-rat-edit").value === "E2E: why this scenario");
    const thrIn = $("input.thr"), thr0 = thrIn.value;
    setVal(thrIn, "5"); await sleep(200);
    el("sim-share").click(); await sleep(300);
    ok("link has the threshold", /&t=5\b/.test(location.hash), location.hash.slice(-12));
    const code = (/#s=([A-Za-z0-9_-]+)/.exec(location.hash) || [])[1];
    const dec = code && ShockEngine.decodeScenario(code, D.basis);
    ok("link carries the rationale", dec && dec.scenario && dec.scenario.rationale === "E2E: why this scenario");
    setVal(thrIn, thr0); await sleep(200);
    history.replaceState(null, "", location.href.split("#")[0]);
  });
  await step("shocks: share link round trip", async () => {
    el("sim-share").click(); await sleep(300);
    const code = (/#s=([A-Za-z0-9_-]+)/.exec(location.hash) || [])[1];
    const dec = code && ShockEngine.decodeScenario(code, D.basis);
    ok("link encodes the scenario", dec && dec.scenario && dec.scenario.legs[0].countries[0] === "FR", location.hash.slice(0, 20));
    history.replaceState(null, "", location.href.split("#")[0]);
  });
  await step("shocks: sentence box (stubbed interpreter)", async () => {
    setVal(el("nl-text"), "gas +30% in Germany"); el("nl-go").click(); await sleep(500);
    ok("interpretation shown", !el("nl-confirm").hidden);
    const lines = visibleText(el("nl-lines"));
    ok("codes shown as names (D63)", !/ELC_GAS|\bDE\b/.test(lines) && lines.includes(D.i18n.en.g_DE || "Germany"), lines.slice(0, 120));
    ok("bare 'gas' gets the component note", lines.includes(D.i18n.en.nl_gas_note.slice(0, 20)));
    el("nl-run").click(); await sleep(300);
    ok("scenario loaded", $("#f-countries input[value=DE]").checked && el("f-size").value === "30");
  });

  // ---------------------------------------------------------------- F. model
  await tab("model");
  await step("model: evidence summary and decision-code links (D60)", async () => {
    ok("four summary tiles with numbers", $$("#msum > div").length === 4 && /0\.\d\d/.test(visibleText(el("msum"))));
    ok("six decision codes listed", $$("#dc-list dt").length === 6);
    const a = $("a.dcode");
    ok("codes in the text are links", !!a);
    if (a) { a.click(); await sleep(700); ok("a code link lands on its entry", document.activeElement && el("dc-" + a.dataset.dc) && $("[role=tab][aria-selected=true]").dataset.tab === "model"); }
    ok("old 'Hold-out' label gone", !$$("#bt-sample option").some((o) => /Hold-out|Hors sélection/.test(o.textContent)));
  });
  await step("model: tables, sample menu, horizons, time machine", async () => {
    for (const id of ["tbl-led", "tbl-bt", "tbl-r2", "tbl-cal", "tbl-rt", "tbl-sel", "tbl-val", "tbl-vin"]) ok(`${id} has rows`, $$(`#${id} tbody tr`).length > 0);
    const opts = [...el("bt-sample").options].map((o) => o.value);
    const before = visibleText(el("tbl-bt"));
    setVal(el("bt-sample"), opts[opts.length - 1], "change"); await sleep(300);
    ok("sample menu changes the table", visibleText(el("tbl-bt")) !== before);
    const hb = $$("#track-h button");
    if (hb.length > 1) {
      const sig = () => JSON.stringify(el("p-track").data.map((tr) => (tr.y || []).slice(-3)));
      const d0 = sig(); hb[0].click(); await sleep(300);
      ok("horizon buttons change the track", sig() !== d0);
    }
    ok("round 3 table: bottom-up, 4 models, random walk", $$("#tbl-r3 tbody tr").length === 6 && /Verdict|Verdict/.test(visibleText(el("r3-verdict"))));
    $$("#r3-h button")[0].click(); await sleep(250);
    ok("round 3 horizon switch", $$("#tbl-r3 tbody tr").length === 6 && $$("#r3-h button")[0].getAttribute("aria-pressed") === "true");
    $$("#r3-h button")[2].click(); await sleep(200);
    ok("reconciliation chart: 2 series over all months", el("p-recon").data.length === 2 && el("p-recon").data[0].x.length === D.recon.dates.length);
    ok("reconciliation table rows", $$("#tbl-recon tbody tr").length >= 6);
    const jumps = $$("#tm-jump button"); jumps[2].click(); await sleep(300);
    ok("time machine Jun 2022 readout", /2022/.test(visibleText(el("tm-read"))), visibleText(el("tm-read")).slice(0, 60));
    setVal(el("tm-range"), "10"); await sleep(300);
    ok("slider moves the origin", /2010|2011/.test(visibleText(el("tm-label"))), visibleText(el("tm-label")));
  });

  // ---------------------------------------------------------------- G. downloads and Explain buttons
  await step("every chart: CSV export and Explain button", async () => {
    const all = $$(".plot").filter((p) => p.data);
    const bad = all.filter((p) => window.__chartCsv(p).split("\n").length < 3).map((p) => p.id);
    ok(`CSV for ${all.length} rendered charts`, bad.length === 0, bad.join(","));
    const plotsWithExplain = $$(".plot").filter((p) => { const b = p.nextElementSibling; return b && [...b.querySelectorAll(".ask-explain")].some((x) => !x.hidden); }).length;
    ok("Explain button under every chart", plotsWithExplain === $$(".plot").length, `${plotsWithExplain}/${$$(".plot").length}`);
    const tw = $$(".tablewrap"), noCsv = tw.filter((w) => !(w.nextElementSibling && w.nextElementSibling.classList.contains("dl-bar"))).map((w) => w.id);
    ok(`table CSV button on all ${tw.length} tables`, noCsv.length === 0, noCsv.join(","));
    const emptyCsv = tw.filter((w) => w.querySelector("tr") && window.__tableCsv(w).split("\n").length < 3).map((w) => w.id);
    ok("table CSVs have rows", emptyCsv.length === 0, emptyCsv.join(","));
    const tex = ["tbl-wc", "tbl-bt", "tbl-led", "tbl-r2", "tbl-val"].filter((id) => !el(id).nextElementSibling.querySelector(".ask-explain:not([hidden])"));
    ok("Explain on table-only cards", tex.length === 0, tex.join(","));
  });

  // ---------------------------------------------------------------- H. assistant (stubbed)
  await step("assistant: answer, cited number, Go to", async () => {
    sent.length = 0;
    el("ask-fab").click(); await sleep(200);
    ok("panel opens", !el("ask-panel").hidden);
    setVal(el("ask-text"), "What does Germany contribute?"); el("ask-go").click(); await sleep(500);
    ok("cited number highlighted", $$(".ask-msg .cite").length >= 1);
    const go = $$(".ask-goto").pop(); go.click(); await sleep(500);
    ok("Go to opens Germany's profile", $("[role=tab][aria-selected=true]").dataset.tab === "countries" && el("cp-country").value === "DE");
  });
  await step("assistant: what-if runs in the engine; preset; fragment follow-up", async () => {
    setVal(el("ask-text"), "What if gas rises 30% in Germany?"); el("ask-go").click(); await sleep(700);
    ok("what-if result in the chat", /Largest impact|Impact le plus fort/.test($$(".ask-msg.bot").pop().textContent));
    ok("chat result uses names, not codes", !/ELC_GAS/.test($$(".ask-msg.bot").pop().textContent));
    setVal(el("ask-text"), "oil supply shock"); el("ask-go").click(); await sleep(600);
    ok("preset by name, no interpreter call", $$(".ask-msg.bot").pop().textContent.includes(D.basis.presets[0].name) && !sent.slice(-1)[0][1].text);
    setVal(el("ask-text"), "gas shock in Germany"); el("ask-go").click(); await sleep(600);
    setVal(el("ask-text"), "+40%"); el("ask-go").click(); await sleep(600);
    ok("fragment joined to the pending what-if", sent.slice(-1)[0][1].text === "gas shock in Germany +40%", sent.slice(-1)[0][1].text);
  });
  await step("assistant: Explain sends chart context", async () => {
    sent.length = 0;
    await tab("shocks");
    $("#p-shock + .dl-bar .ask-explain").click(); await sleep(500);
    const b = (sent[0] || [])[1] || {};
    ok("chart id, selection, page facts, traces sent", b.chart === "p-shock" && b.chart_state && (b.chart_facts || []).length >= 5 && (b.chart_traces || []).length >= 1,
      JSON.stringify({ c: b.chart, f: (b.chart_facts || []).length, t: (b.chart_traces || []).length }));
    await tab("model");
    sent.length = 0;
    $("#p-track + .dl-bar .ask-explain").click(); await sleep(500);
    const s = ((sent[0] || [])[1] || {}).chart_state || "";
    ok("track chart sends its horizon", /horizon \d/.test(s), s);
  });
  await step("assistant: access code flow", async () => {
    await sleep(1000);  // let the previous request finish: the page rightly refuses a new one while busy
    stubMode = "locked"; sent.length = 0;
    // A code kept from an earlier visit is sent, refused, and forgotten: the box opens (D61 keeps codes across reloads).
    setVal(el("ask-text"), "Stub question"); el("ask-go").click(); await sleep(500);
    ok("code box appears on 401", !el("ask-code-row").hidden);
    ok("a refused code is forgotten", (() => { try { return !localStorage.getItem("hicp.code"); } catch (e) { return true; } })());
    codeIssued = true;
    el("ask-code").value = "e2e-code"; el("ask-code-go").click();
    setVal(el("ask-text"), "Stub question"); el("ask-go").click(); await sleep(500);
    ok("code is sent with the next call", sent.slice(-1)[0][1].access_code === "e2e-code");
    ok("code kept in this browser", (() => { try { return localStorage.getItem("hicp.code") === "e2e-code"; } catch (e) { return true; } })());
    stubMode = "normal"; codeIssued = false; try { localStorage.removeItem("hicp.code"); } catch (e) { /* ignore */ }
    el("ask-close").click();
  });

  await step("charts: no time window opens on an empty stretch (D61)", async () => {
    const bad = [];
    for (const tb of ["overview", "drivers", "countries", "shocks", "model"]) {
      await tab(tb);
      for (const g of $$(`#tab-${tb} .js-plotly-plot`)) {
        const xr = g.layout && g.layout.xaxis && g.layout.xaxis.range;
        if (!xr || !/^\d{4}-/.test(String(xr[0]))) continue;
        const xs = (g.data || []).flatMap((d) => d.x || []).map((x) => new Date(x).getTime()).filter(Number.isFinite);
        if (xs.length && Math.min(...xs) - new Date(xr[0]).getTime() > 62 * 864e5) bad.push(g.id);
      }
    }
    ok("every dated chart has data from the start of its window", bad.length === 0, bad.join(","));
  });

  // ---------------------------------------------------------------- I. brief, tour, demo
  await step("brief: A4 preview with two charts", async () => {
    await tab("overview");
    el("brief-open").click(); await sleep(4000);
    const d = el("brief-frame").contentDocument;
    const noteFresh = D.research_note && !D.research_note.stale;  // a stale note is left out on purpose (D42)
    ok("brief shown with 2 images", !el("brief-view").hidden && d.images.length === 2 && [...d.images].every((i) => i.naturalWidth > 0));
    ok("brief includes the note only when it is current", d.querySelectorAll("h2").length === (noteFresh ? 4 : 3), `h2=${d.querySelectorAll("h2").length}, fresh=${noteFresh}`);
    el("brief-close").click(); await sleep(200);
    ok("brief button usable again", !el("brief-open").disabled);
  });
  await step("tour: every step has a visible target", async () => {
    el("tour-open").click(); const bad = []; let n = 0;
    for (let i = 0; i < 25; i++) {
      await sleep(600); n++;
      const tg = $(".tour-target"), r = tg && tg.getBoundingClientRect();
      if (!r || !(r.bottom > 0 && r.top < innerHeight)) bad.push(visibleText(el("tour-step")));
      if (el("tour-next").textContent === D.i18n.en.tour_done || el("tour-next").textContent === D.i18n.fr.tour_done) { el("tour-next").click(); break; }
      el("tour-next").click();
    }
    ok(`tour ran ${n} steps and closed`, n >= 6 && n <= 8 && el("tour-box").hidden, n);
    ok("all tour targets on screen", bad.length === 0, bad.join(","));
  });
  await step("demo: every step and exit", async () => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "D", shiftKey: true })); await sleep(300);
    ok("Shift+D opens the demo", !el("demo-panel").hidden);
    let n;
    for (n = 1; n < 30; n++) {
      const last = el("demo-next").textContent === D.i18n.en.tour_done || el("demo-next").textContent === D.i18n.fr.tour_done;
      if (last) break;
      el("demo-next").click(); await sleep(400);
    }
    ok(`demo has ${n} steps`, n >= 14, n);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); await sleep(200);
    ok("Esc closes the demo", el("demo-panel").hidden);
  });

  // ---------------------------------------------------------------- J. language and theme
  await step("French: everything translated, decimal commas", async () => {
    $("[data-lang=fr]").click(); await sleep(600);
    for (const t of ["overview", "drivers", "countries", "shocks", "model"]) {
      await tab(t);
      const raw = [...el(`tab-${t}`).querySelectorAll("*")].filter((n) => n.children.length === 0 && !n.closest("table") && /^[a-z]+(_[a-z0-9]+)+$/.test(n.textContent.trim()));
      ok(`FR ${t}: no raw keys`, raw.length === 0, raw.slice(0, 3).map((n) => n.textContent).join(","));
    }
    await tab("overview");
    ok("FR KPI uses a decimal comma", /\d,\d/.test(visibleText(el("kpi-dec"))), visibleText(el("kpi-dec")).slice(0, 30));
    $("[data-lang=en]").click(); await sleep(500);
  });
  await step("dark theme: colours switch, charts still render", async () => {
    const bg0 = getComputedStyle(document.body).backgroundColor;
    $("[data-theme-btn=dark]").click(); await sleep(600);
    ok("page background changes", getComputedStyle(document.body).backgroundColor !== bg0);
    ok("headline chart re-rendered", el("p-headline").data.length > 3);
    $("[data-theme-btn=auto]").click(); await sleep(400);
  });

  window.fetch = realFetch;
  ok("no JavaScript errors during the run", errors.length === 0, errors.join(" | "));
  const failed = results.filter((r) => !r.ok);
  return { passed: results.length - failed.length, failed: failed.length, failures: failed, total: results.length };
})();
