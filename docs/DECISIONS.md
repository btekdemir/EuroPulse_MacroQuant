# Decisions log

Each entry: what was decided, why, and the alternative rejected. Numbers come from
`outputs/validation_report.json` (run of 19 Oct 2026, Eurostat vintage 16 Oct 2026, last period Sep 2026).

---

## D1. Data sources: verified live, not assumed (`config/settings.yaml`, `src/hicp/ingest.py`)

- **What:** I verified every Eurostat code against the live API on 19 Oct 2026:
  - `prc_hicp_minr`: index, `coicop18` = ECOICOP ver.2, unit `I25`;
  - `prc_hicp_iw`: item weights;
  - `prc_hicp_cw`: country weights;
  - `prc_hicp_ctr`: official contributions;
  - `prc_hicp_fpd`: flash and first releases.
- **Why:** the legacy ver.1 datasets (`prc_hicp_midx`, `prc_hicp_inw`, `prc_hicp_cow`) are frozen at 2025. In particular, `prc_hicp_cow` has no 2026 country weights, so it has no weight for Bulgaria. My earlier project used `prc_hicp_cow`; this one uses the ver.2 `prc_hicp_cw`, found through the Eurostat catalogue (`catalogue/toc`).
- **Rejected:** the `eurostat` Python package. It adds a dependency and hides the request, and I wanted the raw JSON-stat payload cached byte-for-byte as evidence.

## D2. Euro area\* = `geo=EA`

- **What:** I use the changing-composition aggregate `geo=EA`.
- **Why:** its Eurostat label is literally "Euro area (EA11-1999, EA12-2001, …, EA20-2023, EA21-2026)". `EA21`, `EA20` and `EA19` are fixed compositions. The country-weight dataset confirms membership: in every year since 1999, the countries carrying a `COWEA` weight are exactly the members that year (gate V7). Bulgaria enters in 2026 with 8.96‰. There is no EA14, because Cyprus and Malta joined together in 2008.

## D3. COICOP ver.2 history is a back-cast: use it, flag it, test the window

- **Evidence:** the EA ver.2 series carry flag `d` ("definition differs") for every month from 1996-01 to 2016-12, and flag `b` (break) in 2017-01. Genuine ver.2 compilation therefore starts in 2017. The unprocessed food weight drops from 74‰ (2016) to 56‰ (2017), a reclassification between processed and unprocessed food.
- **Decision:** use the full back-cast series. It is Eurostat's own official back-calculation, and it is what `prc_hicp_ctr` uses back to 2002. 2017–2026 alone would give about 115 monthly observations, too few to estimate seasonal + AR models or to run a 2010+ backtest. The estimation window (full sample vs post-2010 vs post-2017) will be chosen by the backtest. The FOOD_P/FOOD_NP split around 2017 is the most exposed series.
- **Rejected:** splicing legacy ver.1 series onto ver.2. That would mix two classifications by hand, and Eurostat's back-cast already does it consistently.

## D4. Six modelled components that partition the basket

- **What:** FUEL, ELC_GAS, FOOD_P, FOOD_NP, IGD_NNRG, SERV.
- **Why:** they are the standard ECB special aggregates, with energy and food each split into their two sub-components. They sum to 1000‰ in every year from 2001 (V3: max gap 0.02‰). FUEL + ELC_GAS = NRG and FOOD_P + FOOD_NP = FOOD hold exactly. Energy is split because fuels follow oil prices within a month, while electricity and gas follow regulated, step-wise tariffs: different models. NEIG and services weights only start in 2001, so chain-linking starts in Jan 2001.
- **Rejected:** the 13 COICOP divisions. Energy sits inside CP04 and CP07, so the divisions mix very different price processes, and the ECB's own projections are built on the special aggregates.

## D5. Raw cache keyed by query hash + Eurostat `updated` stamp (`ingest.py`)

- **What:** each raw JSON-stat response is gzipped under a file name made of a hash of the query plus Eurostat's `updated` stamp.
- **Why:** the same vintage means no new file (idempotent). A new release adds a file and keeps the old one. `--offline` replays the latest cache, and `run_manifest.json` records vintage, sha256 and file for each pull.
- **Rejected:** overwriting a single file per dataset. That loses the vintage trail, which a reviewer needs to reproduce a number.

## D6. One chain-link function for components and for countries (`chainlink.py`)

- **What:** `chain_link(index, weights, items, start, anchor)` implements I_t = I_Dec(y−1) · Σ s_i,y · I_i,t / I_i,Dec(y−1). It is anchored once to the published level and then fully recursive, so rounding or method errors would compound across 25 years. They don't (V4).
- **Changing composition:** whoever has a weight in year *y* is in the aggregate, so a new member enters in January automatically.
- **Weights:** they are renormalised over the items present. Published weights are rounded, with sums of 1000 ± 0.03.
- **Rejected:** anchoring every December to the published value. It is easier to pass, but it would hide drift.

## D7. Exact contributions, not weight × rate

- **What:** the YoY rate spans two annual links, so each item's contribution has two terms (formula in `chainlink.exact_contributions`).
- **Result:** V5 matches Eurostat's official `prc_hicp_ctr` within **0.009pp max, 0.0027pp mean, over 1,782 observations** (2002–2026, six series). This re-verifies, on new data and more series, the 0.009pp from my earlier project.
- **Rejected:** the naive s_i × π_i. It is not additive and has a provably non-zero error; there is a test for it.

## D8. Validation gates (`validate.py`)

- **Design:** nine gates. Each returns pass/warn/fail with numbers and a capped list of flagged rows, and is written through a pydantic schema. A failing critical gate (V1–V5, V9) stops `run.py` before any forecast. A gate that crashes counts as failed; it doesn't crash the pipeline. Gates only flag; they never edit data.
- **V8 outliers:** the robust z is computed on m/m changes after removing each calendar month's median. HICP is not seasonally adjusted, so January/July sales would otherwise flag every year. 61 flags, mostly ELC_GAS in 2021–22 and NEIG sales-timing shifts. They are kept.
- **V7 honesty:** I compared changing vs fixed composition within enlargement years. The difference is under 0.01pp, because new members weigh 0.15–0.9% and indices are published to 2 decimals. So the binding check in V7 is membership by year, not the level comparison.
- **V9 thresholds:** warn at more than 50 days after the period's month-end, fail at more than 80. Eurostat publishes the full release about 17 days after the *next* month-end, so a correctly refreshed pipeline is at most about 47 days old. A warning means one release has been missed; a failure means two.

---

## D9. PRE-COMMITTED model-selection rule (written 19 Oct 2026, before any backtest was run)

This entry was committed to git before any forecast model existed in the repo (see `git log`).
It does not change after the results are in.

1. **Ladder per component**, simplest first:
   - `SM`: seasonal mean of m/m, i.e. calendar-month dummies only;
   - `AR1`: SM + AR(1);
   - richer: SM + AR(p ≤ 3) chosen by AIC, plus an Easter dummy for services; and for FUEL, SM +
     the contemporaneous Weekly Oil Bulletin pump-price change.

   A model moves up one rung only if it beats the model currently selected.
2. **"Beats"** means lower MSE **and** a Diebold-Mariano test (squared-error loss, Newey-West
   variance with h−1 lags, Harvey-Leybourne-Newbold small-sample correction) with **two-sided
   p < 0.05**.
3. **Loss for selection:** the squared error of the component's cumulative 3-month log change
   (h = 3). This is the quantity that moves the Dec 2026 YoY from a Sep origin.
4. **Selection sample:** forecast origins Jan 2010 – Dec 2019 only. Origins Jan 2020 – latest are a
   hold-out that the rule never sees. Headline results are reported on the full period and on the
   hold-out separately, so selection cannot flatter the reported accuracy.
5. **Estimation window:** expanding from Jan 2001, by default. A rolling 120-month window replaces
   it only under the same DM rule on the same selection sample.
6. **Information set at each origin:**
   - only index data up to the origin month;
   - item weights for year *y* only from the Jan-*y* origin onwards (they are published with
     January data); otherwise the latest known year's weights;
   - pump prices only for Mondays at least 3 days before the origin's HICP release date, taken as
     day 17 of the following month. Unknown pump prices are held flat at the last observed value.
   - Latest-vintage HICP throughout (pseudo-real-time: revisions are small; stated as a limitation).
7. **Headline benchmarks**, all scored at h = 1, 2, 3 on YoY:
   - random walk on YoY (no change);
   - seasonal mean of headline m/m;
   - seasonal random walk of headline m/m (same month last year);
   - direct AR(p, AIC) + seasonal dummies on headline m/m.

   The bottom-up model is reported as an RMSE ratio vs the random walk, with DM p-values.

---

*Entries D10–D15 were written after the backtest, on 19 Oct 2026. Numbers come from `outputs/backtest_metrics.json` and `outputs/forecast.json`.*

## D10. External energy data (`src/hicp/external.py`)

- **What:** three public sources, none needing a key:
  - the EC Weekly Oil Bulletin (euro area weighted pump prices with taxes: euro95, diesel, heating oil);
  - Brent spot from FRED `DCOILBRENTEU`;
  - the ECB EUR/USD reference rate.

  The pump-price regressor is the equal-weight geometric mean of the three products. The fuel equation's coefficient absorbs the scale.
- **Why:** fuels reprice within the month, and the bulletin is observed weekly before the HICP release. My earlier project found its value comes from this timing, not from any model sophistication.
- **Rejected:** a Brent futures-curve bridge. I found no public, scriptable futures curve, so beyond the last bulletin I assume no change in pump prices. This is stated in the forecast assumptions. Brent in EUR is ingested for the shock engine (preset 1).

## D11. Information set at each origin (verified by tests)

- **Origin:** month *t*, whose full release is assumed on day 17 of *t+1*. Sep 2026 was actually released on 16 Oct.
- **Bulletins:** known if Monday + 3 days ≤ release date. For the live forecast that means 5 and 12 Oct 2026.
- **Weights:** year-*y* weights are used only from origin Jan *y* onwards. When the horizon crosses January, the old year's weights are used. A test checks that this differs from using the true new weights, so look-ahead would be detectable.
- **Data:** latest-vintage HICP. The backtest is pseudo-real-time, not a real-time one with first releases. That is a limitation; HICP revisions are small.

## D12. Selection outcome (applied mechanically; selection origins 2010–2019)

| Component | Selected | Why |
|---|---|---|
| FUEL | PUMP (pump-price regression) | MSE 17.5 vs 26.6 for SM, DM p = 0.006. The rolling window did not pass (p = 0.21). |
| ELC_GAS | SM | AR1 lower MSE but p = 0.07: rejected |
| FOOD_P | ARP (AIC) | SM → AR1 p = 0.002 → ARP p = 0.013 |
| FOOD_NP | SM | AR1 and ARP worse |
| IGD_NNRG | ARP, rolling 120m | ARP vs SM p < 0.001; rolling vs expanding p < 0.001 |
| SERV | SM, rolling 120m | ARP with Easter did not beat SM (p = 0.74); rolling vs expanding p < 0.001 |

- **Reading:** a rolling window wins for NEIG and services. Their seasonal patterns (sales periods, package-holiday timing) drift over 25 years, so old seasonal means go stale. Services staying at a seasonal mean is consistent with BoG WP 363, where the richer services equation lost to simple benchmarks.
- **Interpretation I made:** the D9 ladder has more than one candidate on the richer rung for FUEL (ARP and PUMP). Each candidate is tested against the current model, and among those that pass, the lowest-MSE one is chosen. Only PUMP passed.

## D13. Seasonal random walk dropped as a separate benchmark

- **Why:** rolling last year's m/m forward is algebraically the random walk on YoY: H_t · (H_{t+h−12}/H_{t−12}) / H_{t+h−12} = H_t/H_{t−12}. My first run scored it at a ratio of exactly 1.000, and I checked this before believing it. The identity is pinned by `tests/test_forecast.py::test_seasonal_rw_on_mom_is_identical_to_rw_on_yoy`.
- **What is scored instead:** the seasonal-mean benchmark, direct (`direct_SM`) and bottom-up (`bottom_up_SM`).

## D14. Headline backtest results (200 origins, 2010-01 → 2026-08)

| h | RMSE (pp) | Ratio vs RW | DM p vs RW | DM p vs direct AR | Bias (pp) | Direction |
|---|---|---|---|---|---|---|
| 1 | 0.27 | 0.72 | 0.009 | 0.013 | −0.04 | 79% |
| 2 | 0.49 | 0.81 | 0.057 | 0.099 | −0.09 | 70% |
| 3 | 0.67 | 0.84 | 0.140 | 0.552 | −0.13 | 65% |

- **Honest reading:**
  - The gain over the random walk is significant at h = 1, where the pump bulletin bites. It is not significant at h = 3, the target horizon (p = 0.14), even though the RMSE is 16% lower.
  - Over the full sample, bottom-up beats the direct AR at h = 1 but not at h = 3 (p = 0.55). This matches Hubrich (2005) and ECB WP 2501: for the euro area aggregate, bottom-up ≈ direct at 1–3 months.
- **Where it breaks:** in 2020–2023 the h = 3 RMSE is 1.15pp with bias −0.64pp, so the model under-predicted the surge. Seasonal and AR models can't see regulated-tariff jumps or fiscal measures. ECB WP 3062 finds that even perfect commodity foresight under-predicted 2022.
- **Hold-out (2020+, never seen by the selection rule):** the h = 1 ratio is 0.68 (p = 0.025), so the selection did not overfit 2010–2019.

## D15. Fan chart = empirical out-of-sample errors

- **What:** point forecast + quantiles (5/16/50/84/95) of the backtest's own errors at each horizon, over all 200 origins.
- **Why:** model-implied bands from OLS residuals ignore parameter, model and aggregation uncertainty, and they assume symmetry. The empirical errors are skewed upwards (2021–22 under-prediction), so the fan is too. December 2026 has a 68% band of 3.5–4.4% and a 90% band of 3.2–5.1%.
- **Rejected:** bands that exclude 2022. That would make the fan look narrower than the forecaster's actual track record.

---

## D16. Scope change: no Power BI pack (20 Oct 2026)

- **What:** I dropped the Power BI pack.
- **Why:** the brief allows any framework for the dashboard ("link, interactive HTML export, runnable code, or any file that lets us explore your results interactively"). I can't build or test a `.pbix` on a Mac. A single self-contained HTML file opens offline by double-click on any machine, and it is the one I can test end to end.
- **What's kept:** the validated JSON outputs are the data layer the Power BI pack would have read. Anyone on the team could point Power BI at `outputs/*.json` later.

## D17. Shock engine (`src/hicp/shocks.py`, mirrored in `dashboard/shock_engine.js`)

- **Design:** a shock is a deviation of the consumer price *level* for chosen components in chosen countries, following a profile: permanent, decaying, temporary, ramp, or an estimated lag profile.
- **Weights:** each (country, component) cell's share of the euro area\* basket at Sep 2026 prices:
  - the country weight (`prc_hicp_cw`) × the country's price drift since December;
  - × the component's effective weight within that country.

  The 21 × 6 cells re-aggregate to the euro area effective weights within 2e−5.
- **YoY impact:** ΔYoY_t = (1 + π_t) · (R_t / R_{t−12} − 1), with R the shocked/baseline level ratio. This is exact given the level path. A permanent shock lifts YoY for 12 months and then drops out (base effect); a test checks that.
- **One engine, two languages:** the dashboard recomputes in the browser. `tests/test_shock_engine_parity.py` runs the JS engine in Node and requires agreement to 1e−12 on nine scenarios.
- **Simplifications, stated in the assumptions panel:**
  - weights held at their Sep 2026 values (no drift, no Jan 2027 reweighting);
  - no policy or demand response.
- **Rejected:** the naive s_i × shock. It ignores effective-weight drift: fuels are 4.0% official vs 5.2% effective.

## D18. Pass-through estimates (`src/hicp/passthrough.py`)

- **Fuel elasticity to Brent in EUR:** 0.31 (HAC s.e. 0.04, 2005–2026), with 66% of it in month 0. Excise duty is a fixed amount per litre, hence well below 1. This maps preset 1 (Brent +30%) to a fuel price-level shock of +8.4%.
- **Second round, energy → core:** a distributed lag over 12 months, with month dummies and Newey-West errors.

  | Regime | 12-month cumulative | 95% CI | Months |
  |---|---|---|---|
  | 2002–2019 | 0.016 (not significant) | −0.03 to 0.06 | 216 |
  | 2021–2026 | 0.074 | 0.047 to 0.101 | 69 (short) |

  Default is off; the toggle is labelled "estimated, uncertain". The band uses the pointwise CI bounds of the cumulative response, so it is approximate.
- **Bug found and fixed before release:** my first version used Σγ_k Δe_{t−k}, which is the core *m/m* response, as if it were the core *level* deviation. The level is Σ_j Δe_j · C(t−j), with C the cumulative impulse response.

## D19. Presets (`config/scenarios/preset_*.json`, regenerated each run from the data)

1. **Oil supply shock:** Brent +30% → FUEL +8.4% via the estimated elasticity and lag profile, from Nov 2026.

   Effect: +0.46pp at peak, +0.42pp on Dec 2026. If second round is on, the peak becomes +0.64pp in Oct 2027.
2. **European gas price spike:** retail ELC_GAS +20%, ramped over 6 months to reflect regulated and fixed-term contracts.

   The size is about a quarter of the 2021–22 retail rise (+75% from Jun 2021 to the Oct 2022 peak, measured in our data). This mapping is judgemental: there is no TTF series in the pipeline.

   Effect: +1.07pp at peak.
3. **France regulated electricity tariff +10%:** FR ELC_GAS +6.24%, because electricity (`CP0451`) is 62.4% of France's ELC_GAS weight in 2026. Starts Feb 2027 (the TRVE revision month).

   Effect: +0.06pp.

## D20. Dashboard: one offline HTML file (`dashboard/`)

- **What:**
  - Plotly is inlined from the installed Python package, with no CDN. The file is 5.2 MB and opens by double-click.
  - Data comes only from the schema-validated outputs, which are re-validated at build time.
  - FR/EN covers every label, tooltip and note via `i18n.json`, and a test enforces key parity. The preset rationales are English-only, and the page says so in FR mode.
- **Design:**
  - a validated colour-blind-safe six-slot palette, checked with the palette validator: all hard gates pass in light and dark;
  - in light mode three slots are below 3:1 contrast, so every multi-series chart has a table view;
  - consistent component colours;
  - a source line on every chart;
  - light/dark plus OS auto;
  - works at phone width (no horizontal scroll at 375px).
- **Verified in a browser:** five tabs, no console errors. The simulator numbers equal the Python engine's, and the FR toggle, dark mode and mobile width were all checked.

## D21. Structural break tests for the energy → core regime (20 Oct 2026, `passthrough.break_tests`)

- **Why:** D18 split the second round at 2020 on prior evidence, not from a test. This entry tests that choice.
- **Specification:** the D18 distributed lag over the full sample, plus a post-break intercept and post-break lag coefficients γ_k, with HAC (Newey-West) errors.

  H0: Σγ_k = 0, i.e. the 12-month cumulative pass-through is unchanged.

| Test | Result |
|---|---|
| Chow at 2020-01, cumulative | +0.078 higher after (s.e. 0.026), χ²(1) p = 0.003 |
| Chow at 2020-01, all 13 γ jointly | χ²(13) p = 0.12 (the shift is in the sum; single lags are noisy) |
| sup-Wald / QLR (Andrews 1993), central 70% | 17.9 vs 5% critical value 8.68, so the pass-through is unstable |
| Break date sensitivity 2019 / 2020 / 2021 / 2022 | difference +0.083 / +0.078 / +0.053 / +0.052; p 0.001 / 0.003 / 0.046 / 0.029 |

- **The sup-Wald maximum is at 2012-09, not 2020. Why that is not a 2012 break:**
  - The sub-sample pass-through is −0.005 (2002–12) and 0.001 (2013–19): both zero, and equal.
  - It is 0.091 (s.e. 0.015) only from 2020.
  - A single-break test puts the break early because the high-pass-through period sits at the end of a long "after" segment, and a balanced split gives a smaller standard error.
  - I also checked on synthetic data with a known break: sup-Wald locates the date only to within about ±2 years, because the statistic sums 13 noisy lag coefficients (`tests/test_break_tests.py`).
- **Is it just 2022?**
  - Dropping the peak (Jan 2022 – Jun 2023): 0.088 (s.e. 0.032). The difference survives.
  - Dropping all of 2021–23: 0.042 (s.e. 0.056) on 45 months, too few to tell. Most of the evidence comes from that episode.
- **Decision:** keep the two regimes. The default post-2020 estimate stays, the toggle stays off by default and labelled uncertain, and the evidence is shown in the dashboard (Model & validation tab).
- **Not done:** Bai-Perron multiple-break tests, and a level-dependent (threshold) pass-through model. The latter is ECB WP 3062's finding of stronger pass-through at high prices, and the natural next step.

## D22. LLM scenario builder and Vercel deployment (20 Oct 2026; code written and tested, not yet run against the real API)

- **What:** a text box in the simulator ("gas +40% in Germany and Italy, fading over 6 months") that an LLM turns into a validated `Scenario`. The user sees the interpretation, confirms, and the deterministic engine runs it.
- **The LLM's whole job** is to fill `ScenarioIntent` (`src/hicp/nl_scenario.py`): which components, which countries, the size the user wrote, which time-path phrase the user used, the start month, and a list of assumptions. A test pins that the only numeric fields are `size_pct` and `profile_months`, both copies of the user's own words.
- **Code does the rest:**
  - Brent → fuel: the estimated elasticity (0.31) and lag profile. It equals the hand-built oil preset (tested).
  - "Fading over N months" → half-life N/2, "for N months" → temporary, "phased in over N" → ramp. Each conversion is shown to the user as a line of the interpretation.
  - Size and month ranges are validated by the same `Scenario` schema as everything else. An out-of-range or incomplete request is rejected with a message, never silently repaired.
- **Prompt injection:** the model has no tools and its output is only a schema instance. In the worst case it emits a valid but odd scenario that the user reads before running. Tested with an "ignore previous instructions, 9999%" case: the range check stops it.
- **Model:** `claude-haiku-5-5` by default (overridable with `HICP_NL_MODEL`): classification into a small schema does not need a larger model, and it keeps the cost far below the $10 monthly cap. I chose it for cost; the eval below is how we check it is accurate enough, and a bigger model is a one-variable change if it is not.
- **Deployment (`deploy/`):** static dashboard plus one Python function. The key is only a Vercel environment variable. The real cap is the $10 spend limit on the Anthropic account; the in-memory per-IP rate limit is best-effort only, because serverless instances do not share memory. The function bundle has its own two-line `requirements.txt` (anthropic, pydantic).
- **If the LLM or the site is down:** everything but the text box still works, and `outputs/dashboard.html` still opens offline with recorded examples.
- **Tested without spending anything:** 23 unit tests with a fake client, and 4 HTTP tests of the function (rate limit, no secret leakage, size limits). The dashboard's live path was tested in a browser with a mocked `fetch` (success, error message, non-JSON 502).
- **Not yet done:**
  - the 18-sentence accuracy eval (`python -m hicp.nl_scenario --eval`, English, French, and 3 sentences that must be rejected);
  - recording the 6 example outputs for the offline dashboard (`--record`);
  - the actual Vercel deploy.

  Each of the first two makes about 20 paid API calls (well under a cent at this model's price) and waits for your approval.

## D23. Multi-shock scenarios (20 Oct 2026)

- **Why:** the first design allowed one shock per scenario: one component list × one country list × one size × one profile, applied to every combination. "Electricity −15% in Spain, oil +20% in Germany, food +8% in Malta" could not be expressed, and ticking three countries and three components would silently apply one figure to nine cells.
- **Design:** a `Scenario` is now a list of `Leg`s (up to 6, one per validated chart colour). Each leg has its own components, countries, size, profile and start month. Second-round settings stay scenario-level.
- **Engine (`shocks._cell_shocks`):** each (country, component) cell sums the log price-level deviations of the legs that touch it, so overlapping shocks compound (+10% and +10% = +21%) and nothing is overwritten. The order of legs does not matter. The by-leg table shows each leg run alone; the sum of those can differ from the total only when legs overlap or through the YoY ratio's mild non-linearity.
- **Old scenarios still load:** a validator converts the earlier one-shock JSON into a one-leg scenario. `tests/data_single_leg_reference.json` freezes the single-shock engine's outputs (and the basis they were computed on) from before the change; the new engine reproduces them to 1e−12.
- **Tests (`tests/test_multi_leg.py`):** regression to the old results; disjoint legs equal a single leg on the union; compounding; order invariance; a hand calculation of the user's own Spain/Germany/Malta sentence; per-leg start months; the JS engine equals Python on multi-leg and overlapping scenarios.
- **LLM:** the intent schema is now a list of `ShockIntent`s. Its numeric fields are still only copies of the user's figures (tested). The prompt tells the model never to merge shocks or apply one figure to everything, and a problem in one shock is reported as "Shock 2: …".
- **A subtlety to state openly:** "oil +20% in Germany" is read as a *Brent* change (the oil price itself), which the code converts to fuel +5.8% through the 0.31 elasticity. A user who means "petrol prices in Germany +20%" should say "fuel prices". The interpretation lines show which reading was taken, before anything runs. Brent is a global price, so applying it to one country is a modelling choice the user makes explicit.
- **Not yet re-run:** the 23-sentence eval (5 multi-shock cases added) and the 6 recorded examples, because both call the paid API.
