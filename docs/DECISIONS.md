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

- **Update (20 Oct 2026, after the paid run):** the 23-sentence eval (English, French, 5 multi-shock sentences, 3 sentences that must be rejected) scored **23/23** with `claude-haiku-5-5`: every component, country, size, profile, start month, leg count and rejection was right. The set was written by the author with fairly clear sentences, so this is a smoke test of the main paths, not an accuracy estimate on real user text. The 6 recorded dashboard examples were re-recorded with the tightened instruction: the interpretation lines no longer list defaults as assumptions. Total spend for both runs: 29 API calls at a small-model price, well under a cent.

## D24. Probabilities, fan calibration and the reverse stress test (20 Oct 2026)

- **Probabilities (`outlook.prob_above`):** P(outcome > threshold) is the share of the 198 past h=3 out-of-sample errors that, added to the point forecast, end above the threshold. No distribution is assumed. With the shock engine, the shocked path gets the same error distribution (stated on the page): the baseline's P(Dec > 3.5%) is 82%; the oil preset moves it to 95%.
- **Fan calibration is shown, not hidden:** the fan uses full-sample error quantiles, so full-sample coverage is 68% / 90% by construction. By period it is not: 78% / 93% in 2010–2019, **31% / 77% in 2020–2023** and 83% / 100% in 2024–now (h = 3). So the fixed fan is too wide when calm and too narrow in a crisis, and the probability sentences inherit that. Fixing it (scaling the fan by recent error volatility) is a candidate improvement, not done yet.
- **Reverse stress test (`shocks.solve_size`):** the y/y impact is strictly increasing in a leg's size when the leg has weight and has started, so bisection (80 fixed iterations, over the schema's −49.9% to +199.9%) finds the size that reaches a target. It solves for the selected leg and holds the others fixed. Targets: a y/y level, or "make P(Dec > threshold) equal q", which first converts q into the required point forecast p* = threshold − quantile₁₋q(errors). Unreachable targets report the reachable interval instead of a made-up answer; a shock that starts after the target month is reported as having no effect.
- **Honest reading of the output:** a ramped shock is only partly in place by December (the text says how much), and an answer like "gas −39%" is a size, not a forecast of whether such a move is plausible: the text compares it to the 2021–22 retail energy rise (+75%) as a yardstick.
- **Tests:** the solution is checked by feeding it back through the forward engine (to 1e−9), direction and fixed-other-legs, unreachable and no-effect cases, and the JS solver and quantile equal Python (`tests/test_reverse_stress.py`, `tests/test_probabilities.py`).

## D25. Forecast ledger (20 Oct 2026, `src/hicp/ledger.py`, `ledger/forecast_ledger.jsonl`)

- **What it is:** every run that produces a new forecast appends one line: the forecast with its 68% / 90% band, the last published y/y (the random-walk forecast), the selected models, the git commit, the config hash, and the sha256 of every raw data pull. Each line carries `prev_hash`, the previous line's hash, and its own hash over everything else.
- **Rules:** nothing is recorded if the code has uncommitted changes (the commit would not identify what ran; generated folders `outputs/`, `ledger/`, `data/` are ignored in that check), if the existing chain does not verify, or if the same forecast on the same data was already recorded. `run.py` re-verifies the chain on every run and exits with code 3 if it is broken.
- **Scoring:** when Eurostat publishes a target month, the pipeline scores it automatically: `pending` → `flash` (the preliminary estimate, `prc_hicp_fpd`) → `final` (from the published index). Each row has the error, the random walk's error, and whether the outcome fell inside the 68% and 90% bands. Shown in the dashboard (Model & validation) and written to `outputs/ledger_scores.json`.
- **What it proves, honestly:** editing, deleting or reordering a past entry is detected (tests cover each, plus re-hashing one entry, which breaks the next link). It is **not tamper-proof**: whoever controls the file could rebuild the whole chain, and `run_at` is the local machine's clock. The independent evidence is the git history: commit the ledger and push it, so the remote's commit time dates it.
- **Entry 1 (recorded 20 Oct 2026, code commit `5bd1fe6`):** origin Sep 2026; Oct 3.70, Nov 3.68, Dec 3.82. The October flash is due around the end of October; the next run after it scores the first forecast.

## D26. Research note with machine-verified numbers (20 Oct 2026, `src/hicp/note.py`)

- **Mechanism:** the pipeline builds a fact sheet of 51 named numbers from the validated outputs (forecast and band, contributions, base/momentum, probabilities, backtest metrics, fan coverage by period, scenario peaks, ledger count). An LLM (`claude-opus-5-5`, overridable with `HICP_NOTE_MODEL`) writes a ≤170-word note and must cite, for every number it writes, the id of the fact it comes from. Code then checks every number token: it must be cited, the fact must exist, and the written figure must equal that fact's value at the precision written. Anything else rejects the note (one retry that lists the failures; then it is marked rejected and never shown as a note).
- **Tested hard without the API (`tests/test_note.py`):** invented number, correct-but-uncited number, citation to a fact that does not exist, citing a fact with the wrong value, digits hidden in forms like "3-month" or "40%" or "1,2", French decimal commas and the Unicode minus, the retry-then-accept path, give-up-after-two-attempts, unparseable output.
- **Result of the real run:** English passed on the first attempt (28 numbers), French on the second (21 numbers): the first French draft was rejected by the check.
- **What the check cannot see, found while reading the French note:** it says the upward asymmetry of the band is "liée à l'énergie". The numbers are all verified, but that causal claim is not in the fact sheet; the asymmetry comes from the 2021–22 under-prediction, and attributing it to energy is plausible but not something we measured. The check guarantees that no figure is invented; it does not check wording (direction, causal claims, emphasis). The dashboard says so on the card, and a person reads the note before it is sent. This note should be edited (or regenerated with a stricter instruction) before anyone relies on that phrase.
- **Stale notes:** the note stores a hash of its fact sheet; the dashboard flags it as stale when the numbers have changed since it was written. Generated on demand with `python -m hicp.note --generate`, never inside `run.py`, so the pipeline needs no API key.

---

## D27. PRE-REGISTERED round 2: can we beat the random walk at h = 3? (written 20 Oct 2026, before any round-2 result)

Committed to git before the code that runs it. It does not change after the results are in.

**Question:** does any candidate beat the random walk on headline y/y at h = 3, significantly, after correcting for the number of tests?

**Candidates (exactly three, no others will be tried in this round):**

- **C1 — producer energy prices lead electricity & gas.**
  - Model: ELC_GAS m/m = 12 month dummies + Σ_{k=1..6} β_k · 100·Δln PPI_{t−k}.
  - Data: Eurostat `sts_inppd_m`, `nace_r2=D35` (electricity, gas, steam), `geo=EA21`, `unit=I21`, NSA. This is a fixed composition, used as an indicator; the changing-composition aggregate does not exist for this dataset. 180 of 320 observations carry Eurostat's `i` flag; they are used as published.
  - Information set: at origin t, PPI is known up to t−1 (it is released about 35 days after month-end; on 20 Oct 2026 the latest is Aug 2026). Unknown PPI changes are set to 0, i.e. the PPI level is held flat, as with pump prices.
  - Gate: C1 enters the headline test only if it passes the D9 rule at component level against the current ELC_GAS model (SM): lower MSE and DM p < 0.05 on the 3-month cumulative change, 2010–2019 origins. If it fails, C1 is reported as rejected at the component stage.
  - Rationale: retail electricity and gas tariffs follow wholesale and producer costs with a lag. ELC_GAS was 41% of the squared h = 3 error in 2021–23.
- **C2 — combination:** the equal-weight average of the bottom-up (current) and direct AR headline forecasts. The weights are fixed and not estimated. Rationale: forecast combination; the two approaches' errors are not identical.
- **C3 — intercept correction:** bottom-up forecast + the mean of the last three one-month-ahead headline errors known at the origin (forecasts made at t−3, t−2, t−1 for targets t−2, t−1, t). Rationale: Clements–Hendry; errors were autocorrelated in the crisis (0.41).

**Test family and decision rule:**
- **Family:** four hypotheses, each "no better than the random walk at h = 3": the current bottom-up model (round 1) plus C1–C3.
- **Test:** each is a Diebold-Mariano test (squared error, NW h−1 lags, HLN correction, two-sided) on all origins 2010-01 → latest with an observed outcome.
- **Correction:** Holm step-down at α = 0.05 across the four.
- **Adoption:** if one or more candidates C1–C3 pass, the one with the lowest full-sample h = 3 MSE becomes the published model. Otherwise the current model stays, and the result is reported as it is.
- **Also reported, not used for the decision:** h = 1, 2; the 2010–2019 and 2020-on samples; DM vs the current bottom-up model.

**Disclosed before running:** C1 and C3 were motivated by the error decomposition of 20 Oct 2026, which used 2020–2023 outcomes, and C2 by known round-1 numbers. So none of these candidates is a clean out-of-sample discovery; the 2020-on sample is not a clean hold-out for them. Each candidate's rationale is standard in the literature, which limits but does not remove the data-snooping concern. The Holm correction covers this round's family only, not every idea considered along the way.

### D27 results (run 20 Oct 2026, after the pre-registration commit 0fb7156; reproduced by `python run.py` → `outputs/round2.json`)

| Model (h = 3, 198 origins) | RMSE ratio vs RW | DM p | Holm threshold | Passes |
|---|---|---|---|---|
| Current bottom-up | 0.838 | 0.140 | 0.0250 | no |
| C1 producer-price-led ELC_GAS | 0.793 | gated out (component stage p = 0.33) | 0.0500 | no |
| C2 bottom-up + direct AR average | 0.827 | 0.091 | 0.0167 | no |
| C3 intercept correction | **0.769** | **0.026** | 0.0125 | no |

- **Decision, per the rule:** no candidate passes, so the current model stays. The best candidate (C3) would be significant as a single test at 5%, but not after Holm's correction for four tests.
- **C1:** at component level the producer-price model lowered ELC_GAS's 2010–2019 MSE (1.23 vs 1.41) but not significantly (p = 0.33), so the gate stopped it. Its headline numbers are reported for information only.
- **Where the gains are:** in 2010–2019 every model's h = 3 ratio is 0.95–1.03 and none is significant; the improvements come from 2020 on (C3 0.71, C1 0.75, current 0.81). Combined with the data-snooping disclosure above, the honest statement is: *we do not have significant evidence of beating the random walk at h = 3*.
- **h = 1, 2 (reported, not part of the decision):** every candidate beats the random walk at h = 1 (p ≤ 0.009); at h = 2, C1 (p = 0.013), C2 (p = 0.045) and C3 (p = 0.008) do, against 0.057 for the current model.
- **One implementation detail D27 did not anticipate:** C3 needs one-month errors from before the first origin, which cannot be computed (the fuel model needs 60 months of bulletin data in 2009). The first three origins therefore use the 0–2 errors already known; 2010-01 has no correction.
- **What would be legitimate next:** not a round 3 on the same data, which would be a search for a significant result. Instead, (a) the forecast ledger accumulates genuinely out-of-sample outcomes from Oct 2026 on, and (b) information the random walk cannot have at h = 2–3, such as an energy futures curve (not freely available).

---

## D28. PRE-REGISTERED: a crisis-aware fan (written 20 Oct 2026, before any result)

**Problem being fixed:** the published fan uses full-sample error quantiles (in-sample) and is too narrow in crises: the 68% band held 31% of outcomes in 2020–2023, 78% in 2010–2019 (D24). This is a calibration question, not a point-forecast one; the point forecast does not change.

**Both fans are built recursively** (only errors whose target month has been published by the origin), so the comparison has no look-ahead. Neither fan is the in-sample one currently shown.
- **A (fixed width, recursive):** point + empirical quantiles of the h-step errors known at the origin.
- **B (volatility-scaled):** point + σ_t × empirical quantiles of the standardised errors z = e / σ_o known at the origin.
  - σ_t is the root mean square of the last 12 one-month-ahead errors known at origin t.
  - σ_o is that same measure at each past error's own origin.
- **Requirements:** at least 12 one-month errors before σ is defined, and at least 36 errors (or standardised errors) before a fan is built. Origins without both fans are not scored.

**Scoring (h = 3, primary):**
- The quantile (pinball) loss averaged over q = 0.05, 0.16, 0.84, 0.95, per origin.
- B is adopted for the published fan and the probabilities if its mean loss is lower than A's and a Diebold-Mariano test on the per-origin loss differential (NW h−1 lags, HLN, two-sided) gives p < 0.05. Otherwise the current fan stays and the result is reported.

**Also reported:**
- coverage of the 68% and 90% bands for A, B and the current in-sample fan, by period (2010–2019, 2020–2023, 2024–now);
- h = 1 and h = 2.

**Disclosed:** this fix was proposed after seeing the crisis coverage (31%), so the crisis period is not a clean hold-out for it; the rule is fixed before running.

## D29. Real-time robustness check (written 20 Oct 2026, before any result; no decision depends on it)

**Question:** do the backtest results depend on revised data? The forecasts keep using latest-vintage inputs (full real-time component vintages do not exist). What changes is that they are scored against what Eurostat published at the time, with a random walk that also uses only first-published figures.

**First-release outcomes:**
- **Up to Dec 2025:** legacy `prc_hicp_fp` (ECOICOP ver.1, `coicop=CP00`, `geo=EA`). This is the figure actually released then: flash from Aug 2017, first full release from 1997.
- **From Jan 2026:** `prc_hicp_fpd` (ver.2, `coicop18=TOTAL`).
- **Not used:** `prc_hicp_fpd` values before 2026. They are reclassified back-series, not what was released; checked on 20 Oct 2026, they differ from the legacy first releases in 11 of 108 months, by up to 0.3pp.

**Reported:** for h = 1, 2, 3, the RMSE ratio vs the real-time random walk and its DM p-value, (a) against the first full release and (b) against the flash. Each is shown next to the same origins scored on latest-vintage data.

**Caveat stated up front:** first releases are rounded to 0.1, which adds the same rounding noise to both models.

### D28 results (run 20 Oct 2026 after commit e0bfd11; `outputs/calibration.json`, Model & validation tab)

| h = 3, 148 scored origins from 2014-03 | Quantile loss | Inside 68% | Inside 90% |
|---|---|---|---|
| A fixed width, real time | 0.141 | 60% | 78% |
| B crisis-aware, real time | 0.132 | 60% | 79% |
| Current fan (in-sample, for reference) | 0.131 | 63% | 87% |

- **Decision, per the rule:** B lowers the loss by 6% but DM p = 0.36, so B is **not adopted**; the current fan stays.
- **In 2020–2023 B is clearly better:** 68% band 46% vs 31%, 90% band 73% vs 60%, loss 0.231 vs 0.261. It is still short of nominal coverage.
- **In calm periods B is slightly worse:** 2010–2019 loss 0.090 vs 0.086; 2024–now 68% coverage 70% vs 83%.
- **A finding about the old table:** the per-period coverage table in D24 used in-sample quantiles. In real time a fixed-width fan covers 60% (68% band) and 78% (90% band) at h = 3, so the in-sample table flattered it. The dashboard now shows the real-time comparison instead.
- **The published live fan is unaffected:** at the latest origin all errors are known, so the in-sample and real-time fans coincide (checked: identical quantiles).
- **A bug caught on the way:** coverage first came out as 1%, which is impossible. The cause was a pandas 3 behaviour: `.mean()` of NumPy booleans stored in an object column returns a wrong value. Coverage is now stored as 0/1 floats, and a test pins the dtype (`tests/test_calibration.py`).

### D29 results (`outputs/realtime.json`)

| Bottom-up vs random walk | h = 1 | h = 2 | h = 3 |
|---|---|---|---|
| Scored on first full release (200 origins) | 0.739 (p 0.011) | 0.826 (p 0.076) | 0.846 (p 0.165) |
| Same origins, revised data | 0.722 (p 0.009) | 0.812 (p 0.057) | 0.838 (p 0.140) |
| Scored on the flash (110 origins, 2017+) | 0.687 (p 0.015) | 0.781 (p 0.053) | 0.816 (p 0.140) |

- **Reading:** the conclusions do not depend on revisions. Real-time ratios are within 0.02 of the revised-data ones; the slight weakening is consistent with first releases being rounded to 0.1.
- **Limit:** the inputs remain latest-vintage, because complete real-time component vintages are not published.

## D30. Keeping the ledger running (`scripts/monthly_update.sh`, `.github/workflows/monthly.yml`)

- **What:** the script pulls the latest data, reruns everything, records a new forecast if the data changed, scores past forecasts, and commits only when something real changed: the ledger, the scores, or the forecast. It refuses to run with uncommitted code changes, matching the ledger rule.
- **Schedule:** the GitHub Actions workflow runs it around Eurostat's flash days (1st–3rd) and full-release days (16th–19th) and pushes the commit. The remote's commit time is the independent timestamp the ledger needs.
- **Untested** until the repository is on GitHub (there is no remote yet). No secrets are needed: public data only, and the paid LLM features are not run there.
- **Incident, 20 Oct 2026:** the first run of the script recorded **entry 2 with the same numbers as entry 1**. The repeat check keyed on the data vintages, and two datasets had been added that day (producer prices, legacy first releases). The entry stays: deleting it is exactly what the ledger is built to make detectable. The rule was tightened afterwards: a repeat is now the same origin with the same numbers, whatever the vintages (`tests/test_ledger.py`). Entry 2's scores will equal entry 1's.

## D31. Guided tour (20 Oct 2026)

- **Design:** the dashboard never opens a dialog by itself, because the reviewers' first look should be the answer. On a first visit a one-line banner offers a six-step tour. The "Tour" button in the header restarts it.
- **The six steps:** the answer; the fan; base effect vs momentum; the shock simulator; the reverse stress test; how far to trust it (round 2, calibration, ledger). Each step switches tab, highlights its area and explains it in one or two sentences, in EN/FR.
- **Behaviour:** Esc, the arrow keys and Tab (focus stays in the dialog) all work, and focus returns to the Tour button at the end. The choice is remembered (local storage, wrapped so a blocked storage only means the banner shows again). On phones the box is a bottom sheet.
- **Checked in the browser:** every step is fully in view at 1024×768 and 375×812, there is no horizontal scroll, and switching language translates the open step. Only on step 2 does the box overlap its target, unavoidably, because the chart is taller than the free space; there it sits bottom-left so the fan on the right stays visible.

## D32. More interactive charts (20 Oct 2026)

- **One month, explained (Overview):** click any month on the headline chart, or pick it from the menu, which works with the keyboard.
  - The panel splits the change in y/y from the previous month into momentum and base effect. It uses the same algebra as `base_momentum`, ported to the browser: `explainMonth`, which equals Python to 1e−9 (`tests/test_interactive.py`).
  - It also shows each component's contribution in that month next to the previous month, and names the biggest mover.
  - Example: Oct 2022, +0.68pp, with momentum +1.62 and base effect −0.94; the biggest mover is electricity & gas (+0.42).
- **What if October prints differently? (Overview):**
  - Type or slide October's y/y. The October surprise stays in the price level and the forecast's Nov/Dec monthly changes are kept, so Nov and Dec y/y follow arithmetically (`conditionalPath`, tested).
  - The new path is drawn on the headline chart. P(Dec > threshold) uses the two-month-ahead errors, which is why it changes even when October equals the forecast; the sentence says so.
  - Example: October at 4.0% instead of 3.70 puts December at 4.11% and raises P(Dec > 4%) from 36% to 66%.
  - This is arithmetic, not a re-estimated model, and in 2021–23 surprises persisted, so it is a lower bound in such periods (stated on the card).
- **Compare countries (Countries):** up to three countries against the euro area\*. Add them from the menu or by clicking a bar; the selected countries are highlighted in the small multiples. Colour follows the country, not its position: removing one does not repaint the others (checked).
- **Downloads:** every chart has PNG (Plotly, 2× resolution) and CSV buttons. The CSV is in long format (series, x, y); hover-only helper traces are left out and band edges are named by quantile.

## D33. Country profile (20 Oct 2026)

- **What:** click a country's small multiple, or pick it from the menu, and a profile card opens below. It has five parts:
  - a one-line summary: y/y, the change from last month split into momentum and base effect (the same `explainMonth` algebra as the euro area), the country's weight and its contribution rank;
  - the country's own component contributions over the last 36 months, with its y/y line;
  - its basket at today's prices (effective weights) next to the euro area\*;
  - the euro area\* impact of a +10% permanent shock to each component in that country only, from the same shock engine as the simulator.
- **Not included:** a country forecast. The backtest and the model choice (D9) are for the euro area\* headline only. A country forecast would not have been tested, so it is not shown.
- **Italy finding:** each country's exact contributions add up to its published y/y within 0.02pp, except Italy, which is off by up to 0.12pp. Italy's published TOTAL is not the weighted chain-link of its published components. Other countries reproduce their totals to about 0.01 index points; Italy is off by about 0.10. The cause is not identified; seasonal-item treatment is a guess, not verified. The card warns whenever the gap is above 0.02pp, and `tests/test_country_profiles.py` pins the gap so that a change in the data shows up.

## D34. Dashboard assistant, "Ask the dashboard" (20 Oct 2026)

- **What:** an "Ask" panel that answers questions about the dashboard, such as why December is higher, what Germany contributes, or how accurate the forecast is. Answers use only a fact sheet: `outputs/ask_facts.json`, which `run.py` builds from the validated outputs.
  - The sheet has 493 numbers: the research-note facts, forecast detail per horizon, 24 months of euro area\* history with the momentum/base split, and each country's y/y, weight, contribution, rank and drivers.
  - It also has a short non-numeric context: definitions, the selected models, and what is not modelled.
- **Same contract as the research note:**
  - The LLM must cite a fact id for every number it writes.
  - `hicp.numcheck`, the code the note uses (moved into its own module), checks each number against the fact it cites.
  - A failed check is retried once with the list of failures. If it still fails, the answer is not shown and the page says why.
  - Questions the sheet cannot answer come back as "not covered" with no numbers. Examples: ECB decisions, country forecasts, anything beyond three months.
  - The check guarantees that no figure in a shown answer is invented. It does not guarantee the words (it is sign-insensitive), so the page lets you hover any number to see the fact it came from.
- **Cost and safety:**
  - The model is `claude-haiku-5-5`, and the system prompt (fact sheet) is prompt-cached.
  - Limits: 400-character questions, at most 4 earlier messages of 800 characters each, and 3000 output tokens (Haiku 5.5 thinks by default: about 750 thinking tokens per answer were seen).
  - The per-IP rate limit is the same as `/api/scenario`. The hard cap is the monthly spend limit on the Anthropic account.
  - The question, the history and the sheet are treated as data, not instructions.
- **Where it shows:** only where `/api/ask` exists, i.e. on the Vercel site or with `deploy/serve_local.py`. The page probes the route with a GET, which answers 405 there and 404 on a static host. The offline HTML file never shows the button, so reviewers who open the file see no broken feature.
- **Tested:** `tests/test_ask.py` uses a fake client and makes no API calls. It checks:
  - that the facts match the outputs;
  - retry, then withholding;
  - the refusal path;
  - history trimming;
  - the handler guards (413/400/429);
  - that the deploy bundle imports without pandas.
  The UI was checked in the browser with a stubbed response (EN/FR, phone width, static host hides the button).
- **Live check (20 Oct 2026, 5 questions, Haiku 5.5):**
  - All 5 were verified: four on the first attempt, the French one on the second.
  - The questions: why December is higher (EN), accuracy vs the random walk (FR), P(Dec > 4%) (TR), an ECB cut (out of scope, correctly answered "not covered" with no numbers), and Italy's contribution and its month split (EN; it also mentioned the Italy caveat from the context).
  - Every cited value was re-checked by hand against the sheet.
  - Each answer took 2–16 s and used about 0.8–1.3k output tokens, mostly thinking. The 21k-token sheet was cached after the first call.
  - The first attempt exposed a bug: with max_tokens 1000, the model's thinking left too little room and the JSON was cut off. Fixed with 3000, and malformed output is now retried (tested).
  - Two style points were fixed in the prompt afterwards, and the fix has not been re-run live: French and Turkish answers used a decimal point instead of a comma, and one probability was written as 35.86%.
- **Navigation (added after the first local try):** asked "where can I see country-based drivers?", the assistant described the view but could not say where it was.
  - It now gets a map of 29 sections (`hicp.ask.SECTIONS`: tab, element, what it shows) and may return `goto`, plus `goto_country` for the country profile.
  - The server accepts only ids in the map, and a country only with the country profile.
  - The page then shows a "Go to: …" button. It switches tab, opens the country, scrolls to the card and highlights it. On phones it also closes the panel.
  - A test checks that every section's element and tab exist in the page.
  - Live check (2 calls, after the rule was made stronger): "where can I see country based drivers" → country_profile; "Almanya'nın sürücülerini nerede görebilirim?" → country_profile with DE. Both were verified on the first attempt (6 s and 3 s).

## D35. Shareable scenario links (20 Oct 2026)

- **What:** "Copy link" in the simulator puts the whole scenario into the URL fragment (`#s=` + base64url JSON). Opening the link starts on the simulator with that exact scenario.
  - The fragment is never sent to a server, so links work for the offline file too.
  - If the clipboard is blocked, the address bar already holds the link, and the page says so.
- **A link is untrusted input:** `ShockEngine.decodeScenario` rebuilds the scenario field by field.
  - Components, countries and start months must exist in the basis. The size must be inside the schema's limits (−50 to 200%). The profile must be one of the five kinds, with valid parameters. There must be 1 to 6 legs.
  - Unknown fields are dropped and strings are truncated.
  - A link that fails is ignored with a message, and the default scenario shows.
- **Tested:** `tests/test_share_link.py`.
  - Every preset round-trips and simulates identically in Python.
  - Unicode survives.
  - Seven kinds of bad link are rejected, and garbage is reported as unreadable.
  - Browser check: a link with a 37% size reopened on the simulator with the same peak (+0.34pp, Feb 2027).

## D36. The assistant runs what-if scenarios (20 Oct 2026)

- **What:** a question such as "what if gas rises 30% in Germany?" or "ya petrol %20 düşerse?" gets a real simulation in the chat.
  - The assistant flags it (`scenario_request`, accepted only on an answerable reply) and answers in one sentence with no numbers.
  - The page then sends the same sentence to the existing scenario interpreter, `/api/scenario` (D26, same schema and guards).
  - It runs the result with `ShockEngine.simulate` and shows four things: how the scenario was interpreted, the peak impact, the December impact and shocked level, and P(December above the threshold) against the baseline.
- **Why the numbers can be trusted:** the impact figures are computed in the page by the same engine as the simulator, which matches Python to 1e−12 (D20). They are not written by a language model, and the bubble says so. The language models only turn words into a scenario, and the interpretation is shown so the reader can check it.
- **Buttons:** "Open in the simulator" loads the scenario (tab, form, charts). "Copy link" gives a shareable link to it (D35). The answer bubble's own "Go to" button is hidden for what-ifs: it would have opened the simulator with the previous scenario.
- **Cost:** two API calls per what-if question: ask (Haiku), then the interpreter.
- **Tested:**
  - `tests/test_ask.py`: the flag passes through, and never on a "not covered" reply.
  - Browser, with stubbed APIs: Germany gas +30% gave a +0.41pp peak in the chat, equal to `simulate` on the same scenario. "Open in the simulator" showed the same peak, with DE ticked and size 30.
- **Live check (2 questions, 4 calls):**
  - EN, "What if gas prices rise 30% in Germany?": flagged and answered with no numbers (4 s). Interpreted (1.7 s) as electricity & gas, DE, +30%, permanent from Oct 2026, with no second round. Result: +0.41pp peak in Dec 2026 and December at 4.22% instead of 3.82%. This equals the JS figure from the browser test.
  - TR, "Ya İspanya'da elektrik %15 düşer, İtalya'da gıda %5 artarsa ne olur?": two legs. ES electricity & gas −15%, and IT processed + unprocessed food +5%, both permanent from Oct 2026. Net +0.085pp in December, which puts December at 3.90%.

## D37. "Explain this" on every chart (20 Oct 2026)

- **What:** each of the 15 charts has an "Explain this" button next to PNG/CSV. It is shown only where `/api/ask` exists. It opens the assistant with the question "Explain this chart: “<title>”", and the request carries the chart's id.
  - The server adds what that chart shows, from `hicp.ask.CHARTS` (plot id → section, description). The answer explains how to read the chart and the one or two points that matter now, and points `goto` at it.
- **Selections and page facts:**
  - The page also sends the reader's current selection as data: the shock scenario, the chosen month, the country, the compared countries, the horizon.
  - For charts whose numbers are computed in the browser (the shock impact, the chosen month's split), it sends up to 30 page facts (`page_*`). The server accepts only well-formed ids, finite numbers and string labels.
  - These page facts join the fact list for that one request, so cited page numbers pass the same check.
  - A page fact comes from the reader's browser, not from the pipeline. It can only make an answer agree with what that reader's page shows, and the id prefix keeps it apart from pipeline facts.
- **Tested:**
  - `tests/test_ask.py`: context and page facts reach the model; malformed page facts are dropped; an unknown chart id gets no page facts; every chart in the page has an entry and a section.
  - Browser, with a stubbed API: 15 buttons. The headline chart, the shock chart (with the current preset's peak, December impact, its split and shocked level) and the country profile (Germany) each sent the right context.
- **Live check (2 calls):** both answers were verified.
  - The shock chart, with the default oil preset: the answer used the page facts (+0.42pp in December, 4.23%, peak in January 2027, all first round). Verified on the first attempt, 10 s.
  - The headline chart: the answer used the last print, the three forecasts, both bands, and the 31% crisis-period coverage. Verified on the second attempt, 17 s.
- **Two fixes came out of that check:**
  - The answers wrote numbers like 0.4155 although the prompt asked for at most two decimals. The rule is now enforced in code: such a number is sent back for rounding, which is tested.
  - The headline answer called the dotted forecast line "dashed" (the dashed line is the ECB target). The button now sends the chart's own list of series, read from the plot (bars, shaded band, solid/dot/dash line, name), and the model is told to describe visuals only from it.
  - Both fixes are tested with the fake client. They have not been re-run live.
- **Fixes after a local try (the user's transcript):**
  - "oil supply shock" was flagged as a what-if and sent to the interpreter, which failed with "No size found". The follow-up "+%40" was then answered "not covered".
  - **Presets:** the assistant now knows the simulator's ready-made scenarios (`AskFacts.presets`) and may return `preset`. The server accepts only an index in range, and only on a what-if.
  - The page runs a preset directly with the engine, with no interpreter call. It also matches a preset name in the question itself, as a fallback when the model returns no index or replies "not covered".
  - **Follow-ups:** when the interpreter rejects a what-if as incomplete (422), the page says "reply with just the missing part". A short next message that contains a number is joined to it and sent to the interpreter, without going through the assistant again.
  - Browser check with stubbed APIs: "oil supply shock" ran preset 0. "gas shock in Germany" then "+%40" became "gas shock in Germany +%40" and was built. Tested in `tests/test_ask.py` (preset bounds). Not re-run live.

## D38. Sensitivity heatmap (21 Oct 2026)

- **What:** a 21 × 6 grid on the Shock simulator tab. Each cell is the euro area\* December y/y response, in basis points, to a +1% permanent price-level rise in one country and component from next month. The response is first round only.
  - The 126 cells are computed with `ShockEngine.simulate` (the simulator's engine, parity-tested with Python), once per page load.
  - Countries are sorted by their total. Clicking a cell opens a +10% version of that shock in the simulator.
- **Check:** the largest cell is German services, at 13.5bp per 1%. That agrees with the country profile, where +10% gives +1.35pp. Italy's electricity & gas cell is 1.17bp, and +10% gives a 0.12pp peak.
- **Why basis points per 1%:** the response is linear in size, so one unit makes every cell comparable. The note on the card says this.

## D39. What changed since last month (21 Oct 2026)

- **What:** an Overview card covering two things.
  - The surprise in the newly published month (actual minus last month's forecast).
  - The revision to every month both forecasts cover.
  - Each is split by component using exact chain-linked contributions, with the small chain-link residual shown.
- **Last month's forecast:** `build_outlook(origin=previous)` re-runs the same machinery as of the previous origin. Its headline numbers equal the backtest's forecasts from that origin to 1e−9 (`tests/test_outlook_changed.py`).
  - It uses today's data vintage (pseudo-real-time), and the card says so.
  - The ledger only stores headline points, so it cannot give the component split. The ledger keeps the headline forecast as recorded at the time, for checking data revisions. (A first draft promised an automatic switch to the ledger; that was not implemented, so the claim was removed after code review.)
- **Result (Sep 2026 run):** September printed 3.77% against 3.73% forecast in August, a surprise of +0.04pp (non-energy industrial goods −0.13, services +0.10). November was revised from 3.74% to 3.68%.
- The assistant's fact sheet includes these numbers (`wc_*`), and the section map includes the card.

## D40. Time machine (21 Oct 2026)

- **What:** a slider over all 200 backtest origins, plus jump buttons (Feb 2020, Sep 2021, Jun 2022, Jun 2023, latest). For each origin it shows:
  - the three-month bottom-up forecast made then;
  - the fan that could have been drawn then, using only errors whose target month was already published, with at least 24 of them;
  - the outcome and the random walk's error.
- **Why the fan known then:** the live fan uses the full error sample, which includes hindsight. Showing the real-time fan makes the 2022 miss visible as it would have looked.
  - From June 2022, the model forecast September at 8.06%. The outcome was 9.93%, outside even the 90% band known then, and the random walk did better.
- The data is the backtest track already in the page, so nothing new is estimated.

## D41. Range buttons and a clickable contributions chart (21 Oct 2026)

- **Range buttons:** 1Y / 3Y / All on the long time-series charts (headline, contributions, country comparison, country drivers, track record).
- **Clickable contributions:** clicking a month on the contributions chart opens "One month, explained" for that month on the Overview tab, as the headline chart already did.

## D42. One-page brief (21 Oct 2026)

- **What:** "Brief (PDF)" builds an A4 page from what the dashboard shows, in the current language:
  - the KPIs, the answer, and what changed;
  - the fan chart;
  - P(December above 3–5%) and accuracy vs the random walk;
  - the contributions chart;
  - the research note, if it is verified and not stale;
  - Eurostat vintages and the commit.
  The browser's print dialog saves it as PDF.
- **Design choices:**
  - It is an in-page preview (an iframe), not a pop-up, because the first version's `window.open` was blocked.
  - Charts are rendered in the light theme whatever the page theme, and without the range buttons. The theme is restored afterwards.
  - The research note is left out when stale (the numbers changed since it was written), rather than printed with wrong figures.

## D43. Tour and interview demo cover every feature (21 Oct 2026)

- **Tour:** 16 steps instead of 6, with keyed texts in EN/FR.
  - The steps: answer, what changed, fan, month explained, October what-if, drivers, base/momentum, countries, country profile, shock simulator, reverse stress test, heatmap, time machine, trust, Ask (only where the assistant is live), brief.
  - Checked: every step's target is on screen and the box fits, at 1024×768 and at phone width (FR).
- **Demo mode:** a presenter's script, opened with `#demo` in the URL or Shift+D. There is no button, so reviewers never see it. It has 14 steps, and each sets the page up and shows short speaker notes (EN/FR):
  - October 2022 in the month explainer;
  - October at 4.0%;
  - Italy's profile with its warning;
  - the gas preset with second round;
  - June 2022 in the time machine;
  - the Ask panel with a question typed in. The demo does not send it, so it never spends money by itself.
  - Keys: → / ← to move, Esc to exit. Exiting resets the October what-if.
  - The notes only state things checked elsewhere in this file. One unverified claim, that the fan is wider after 2020, was removed.
  - Scrolling waits a short timer after the tab switch, because animation frames stall in background tabs and made the first version scroll one step late.

## D44. Core inflation, as a by-product (21 Oct 2026)

- **What:** core HICP (Eurostat `TOT_X_NRG_FOOD`: excluding energy, food, alcohol and tobacco) on the Drivers tab, built from two of the six components already forecast for the headline: non-energy industrial goods and services.
  - Same component models, same weights known at each origin, same chain-link (`hicp.core`). No new model.
  - The published core index is the actual.
  - The card shows the history against the headline, a forecast with a fan from its own backtest errors, the goods/services split, and the random walk (last print held).
- **Aggregation check:** feeding the realised goods and services changes through the same chain-link reproduces published core y/y within 0.05pp (RMS 0.01pp, 558 cases; tested). Contributions add up within 0.016pp since 2010.
- **Result, stated on the card:** a random walk is more accurate for core at every horizon.
  - Full sample, 198–200 origins: RMSE 0.29 vs 0.24 (h=1, DM p 0.015), 0.41 vs 0.32 (h=2, p 0.007), 0.49 vs 0.41 (h=3, p 0.12).
  - The measurement was checked before being reported (perfect-foresight test above).
  - Likely reasons: core is very persistent, and the goods and services models (ARP and SM, rolling 120 months) were chosen for the headline, where the bottom-up model does beat the random walk at one month.
- **Not done, on purpose:** re-selecting a core model after seeing this would be selection on the evaluation sample. The card recommends the last print as the better core forecast and says why. A dedicated core model would need its own pre-committed rule and its own hold-out sample.
- The assistant knows these facts (`core_*`) and the section. The tour and the demo have a core step; demo titles no longer carry step numbers, since the panel shows "i of n".

## D45. Access code for the paid routes (21 Oct 2026)

- **Why:** the deployed link is public and the Vercel address is guessable. The monthly spend limit caps the loss, but someone could still drain it just before the interview, which would leave the assistant dead during the demo.
- **What:** if `HICP_ACCESS_CODE` is set (on Vercel, as a Secret), `/api/ask` and `/api/scenario` answer 401 unless the JSON body carries the same `access_code`.
  - The check is constant-time (`hmac.compare_digest`).
  - It runs after the per-IP rate limit, so guesses are throttled like any request, and before any LLM call.
  - If the variable is unset (local runs, tests), the routes stay open.
- **Page:** every paid call goes through one helper, `apiPost`. On a "code required" answer, the Ask panel opens a password field. The code is kept in `sessionStorage` (this tab only) and sent with later calls. A wrong code clears it and asks again. The dashboard itself never needs the code.
- **Tested:** `tests/test_access_code.py`.
  - Missing, wrong and non-string codes give 401, and the LLM client is never called.
  - The right code gives 200.
  - With the variable unset, the routes are open.
  - The 7th wrong guess in a minute gives 429.
  - Browser, against the real local server started with a test code: the code box appears, a wrong code is refused, and the right one is attached to the next request (that request was answered by a stub, so no paid call was made).
- `deploy/README.md` no longer quotes a per-token price: it was never verified, so the reader is told to check the Console.

## D46. End-to-end dashboard check (21 Oct 2026)

- **What:** `tests/e2e/dashboard_e2e.js` makes 101 assertions on every feature, run inside the page against `deploy/serve_local.py` (which serves it at `/e2e.js`).
  - Every tab: charts have data and fit their cards, tables have rows, no untranslated keys, no horizontal scroll.
  - Overview: threshold, month explainer (menu and chart click), October what-if, range buttons.
  - Drivers: contributions click, core card.
  - Countries: compare add/remove with stable colours, small-multiple click, profile menu, Italy warning.
  - Shock simulator: every preset, multi-leg add/delete, second round, reverse stress test solve and apply, heatmap click, share-link round trip, sentence box.
  - Model & validation: all tables, sample menu, horizon buttons, time machine.
  - Every chart: CSV export and an Explain button.
  - Assistant (answer with cited number, Go to, what-if in the engine, preset by name, fragment follow-up, Explain context, access-code flow).
  - Brief, the full tour and demo, French, dark theme, no JavaScript errors.
- **No paid calls:** POSTs to the two LLM routes are answered by stubs inside the script. The real routes are covered by the Python tests, and the live site was checked for 200/401 with curl.
- **Runs:** 101/101 at 1280×800 and at 375×812.
- **Bugs it found, now fixed:**
  - "Explain" on the track chart sent `horizon undefined` (it read `.value` from a button group).
  - The simulator form widened phones to 417px (449px in French). The causes were a fieldset's default min-content width, a grid column sized by its widest item, and a `nowrap` chip label.
- **Bugs in the test itself, now fixed:** a dataset code read as an i18n key; the horizon button that was already selected; a stub that matched "Germany" before "what if"; a reverse test on a preset that starts after December (the page correctly says no size can reach the target).

## D47. Shock impact chart on a comparable scale (21 Oct 2026)

- **Problem (user-reported):** the impact bars looked the same in every scenario, always full height. The y-axis autoscaled to each scenario's maximum, so a +0.008pp shock filled the chart exactly like a +1pp one. A permanent shock is also, correctly, flat for 12 months, which made the effect stronger.
- **Fix:** the axis always spans at least 0 to +0.5pp, or −0.5pp to 0 for negative shocks, and widens only when the impact is larger. Bar heights are now comparable across scenarios, and a label marks the peak with its value.
- Checked: oil +0.46pp on a 0–0.52 axis, gas +1.07pp on 0–1.23, the French tariff +0.058pp on 0–0.50 (small bars), a −15% shock −0.14pp on −0.5–0.1. The end-to-end check is still 101/101.
