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
