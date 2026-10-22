# EuroPulse: euro area HICP bottom-up forecast, shock simulation & dashboard

> Status (21 Oct 2026): pipeline, validation, forecast, backtest, shock engine, dashboard and assistant are done
> and pass a clean-clone test (below). Deck and defence notes are prepared separately.

**Dashboard:** open `outputs/dashboard.html`. It is one self-contained file that works offline,
with an FR/EN toggle and five tabs: Overview, Drivers, Countries, Shock simulator, Model &
validation. Each page has its own short tour, which starts by itself the first time that page is opened in a browser; **Tour** replays it (Shift+D, or `#demo` in the address, runs the full presenter demo). Every chart and table has CSV export (charts also PNG) and "Explain this".

For the LLM features too (the Ask panel, "Explain this" and natural-language scenarios), run
`.venv/bin/python deploy/serve_local.py` and open http://127.0.0.1:8812. This needs `ANTHROPIC_API_KEY`
in `.env`. Without a key, or in the offline file, those buttons are simply hidden.

**Deck:** `deck/deck.pptx`, five slides with speaker notes, built from the outputs: `python deck/deck_data.py`
(every number, read from `outputs/`) then `node deck/build_deck.js` (needs the `pptxgenjs` npm package).

**Live site:** https://hicpinflationshocksimulator.vercel.app. Everything works without a login. The LLM
features (Ask, "Explain this" answers, sentence scenarios) need an **access code**, which is given in the
submission email; it is asked for once and then kept in that browser. Without it, "Explain this" shows the
card's own written reading instead. The code only protects the paid API quota.

## Answer first

**Euro area\* headline HICP, Dec 2026 (h = 3 from the Sep 2026 release): 3.8% YoY (3.77%)**
(68% band 3.4–4.2%, 90% band 3.0–5.1%; Sep actual 3.8%). Path: Oct 3.8%, Nov 3.7%.
The base effect subtracts 0.11pp by December and is already locked in; momentum adds 0.12pp.
Fuels contribute 1.3pp (fuel prices +32% YoY) and services 1.5pp.
Source: `outputs/forecast.json`.

## Quickstart

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py            # live pull → clean → validate → backtest → forecast (~6 min)
.venv/bin/python run.py --offline  # replay the cached vintages (~5 min, most of it Round 3's 200 refits)
.venv/bin/python -m pytest         # tests (data-dependent ones skip until run.py has been run once)
```

Outputs, all schema-validated:
- `validation_report.json`
- `forecast.json`
- `backtest_metrics.json`
- `what_changed.json`
- `core.json`
- `countries.json`
- `shock_basis.json`
- `round2.json`, `calibration.json`, `realtime.json`
- `ledger_scores.json`
- `ask_facts.json`
- `run_manifest.json`

All are in `outputs/`, with JSON Schemas in `outputs/schemas/`.

**Clean-clone test (21 Oct 2026):** a fresh `git clone` + venv + `pip install -r requirements.txt` + `run.py`
pulled the data live in 3 min 10 s. All tests passed. The forecast, backtest, core, what-changed and country
outputs were identical to the committed ones (no numeric difference above 1e−8).

## Method (bottom-up, as in Eurosystem practice)

1. Forecast each of the six components' monthly log change. Every model has calendar-month
   dummies; on top of that, some add AR lags, an Easter dummy, or the Weekly Oil Bulletin
   pump-price change.
2. Chain-link the component levels to the headline with the weights known at the origin.
3. Take YoY against the published headline, then compute exact contributions and the split into
   base effect and momentum.

**Pre-committed model-selection rule** (committed before any backtest; `docs/DECISIONS.md` D9):
keep the simpler model unless a richer one beats it with Diebold-Mariano p < 0.05. Selection
uses 2010–2019 origins only; 2020 onwards is a hold-out.

Published model since round 4 (D57): services and non-energy industrial goods as "no change in y/y", the other
four components with their D9 models.

| h | RMSE | Ratio vs random walk | DM p | vs direct AR, p |
|---|---|---|---|---|
| 1 | 0.23pp | 0.63 | <0.001 | <0.001 |
| 2 | 0.44pp | 0.73 | 0.001 | <0.001 |
| 3 | 0.63pp | 0.79 | 0.016 | 0.056 |

Before round 4, the D9 models gave 0.27 / 0.49 / 0.67pp (ratios 0.72 / 0.81 / 0.84, h = 3 DM p 0.14).

**Round 3 (pre-registered, D56):** SARIMA (airline), Elastic Net, gradient boosting (LightGBM-style, from scikit-learn)
and their ensemble, forecasting headline directly. None passes Holm against the random walk at h = 3. The bottom-up
model of the time stayed the most accurate (RMSE 0.671 against 0.710 for the best alternative, Elastic Net), and gradient boosting is
worse than the random walk.

**Round 4 (pre-registered, D57):** bottom-up variants. Forecasting services and goods as "no change in y/y" (B1) passed
Holm narrowly (p 0.016 against a threshold of 0.0167) and beat the earlier bottom-up model (RMSE 0.632 against 0.671),
so under the pre-registered rule it became the published model. Checks before adoption: a variant that replaces nothing
reproduces the old bottom-up exactly, and the gain is the same in 2010–2019 and since 2020.

The model beats the random walk at every horizon; at h = 3 significantly only since round 4, and narrowly. It
under-predicted the 2021–22 surge (2020–2023 h = 3 bias −0.37pp; −0.64pp before round 4). See D14, D57.

## Core inflation (by-product, D44)

Core HICP (`TOT_X_NRG_FOOD`) is built from the same goods and services forecasts, with no new model.
Rebuilding it from the two components matches Eurostat's core within 0.05pp.

With the D9 models, **a random walk was more accurate for core at every horizon** (RMSE 0.29 vs 0.24 at h = 1,
DM p 0.015; 0.49 vs 0.41 at h = 3, p 0.12). The dashboard said so, and no model was re-selected after seeing it.
That finding motivated round 4 (D57), which was pre-registered and switched goods and services to "no change in y/y".
Core is now forecast essentially as a random walk (RMSE 0.40 vs 0.41 at h = 3).

## Shock simulator

You pick components and/or countries, a price-level shock, a start month and a profile
(permanent, decaying, temporary, ramp). The pass-through to euro area\* headline YoY is
recomputed in the browser:

- **First round:** effective weights per country × component.
- **Second round (optional):** a regime-dependent energy → core distributed lag, with a 95% band.

Every scenario is a validated `Scenario` object with a mandatory rationale; download it from the
dashboard. Presets, in `config/scenarios/`:

| Preset | Mapping | Peak impact on headline |
|---|---|---|
| Oil supply shock, Brent +30% | fuel elasticity 0.31 (estimated) → FUEL +8.4% | +0.46pp (Jan 2027) |
| European gas price spike | retail ELC_GAS +20% over 6 months (judgemental) | +1.07pp (Apr 2027) |
| France regulated electricity +10% | electricity 62.4% of FR ELC_GAS → +6.24% | +0.06pp |

Assumptions are listed in `src/hicp/shocks.py` and shown in the dashboard. See D17–D19.

## What else the dashboard does

- **Probabilities:** "P(December y/y > X%)" from the empirical error sample, also for the shocked path (D24).
- **Reverse stress test:** "what size of shock gets December to 3%?", solved for the selected shock (D24).
- **Forecast ledger:** every published forecast is recorded in a hash-chained file and scored automatically when Eurostat releases the figure; Model & validation shows the live record (D25).
- **Robustness:** the backtest scored against figures as first published gives the same conclusions (D29); a crisis-aware fan is tested against the fixed one in real time (D28), and an attempt to beat the random walk at h = 3 was pre-registered and failed after Holm's correction (D27).
- **Keeping it running:** `bash scripts/monthly_update.sh` (or the GitHub Actions workflow once the repo is pushed) records and scores each new forecast.
- **Research note:** an LLM-written note in English and French whose every number is checked against the pipeline outputs (D26). Regenerate with `PYTHONPATH=src python -m hicp.note --generate` (paid API call).
- **What changed since last month:** the surprise in the new print and the revisions, by component (D39).
- **Any month, explained:** momentum vs base effect for any month; click a month on the headline or contributions chart (D32, D41).
- **Country profile:** click a country for its own drivers, its basket against the euro area\*, and its euro area\* sensitivity (D33).
- **Sensitivity heatmap:** euro area\* response to +1% in each country × component; click to simulate (D38).
- **Time machine:** any past origin's forecast, the fan known then, and the outcome. June 2022 shows the model's biggest miss (D40).
- **Shareable scenarios:** "Copy link" puts the scenario in the URL; links are validated on load (D35).
- **One-page brief:** "Brief (PDF)" prints an A4 summary (D42).
- **Reconciliation:** our headline rebuilt from six components and our contributions, month by month against Eurostat's, in basis points (D52).
- **Revision waterfall:** last month's forecast to the outcome or the new forecast, by component (D53).
- **Scenario comparison:** save scenarios and show up to four side by side, with December impact, level and probability (D54).
- **Reverse stress test across all shocks:** the smallest combination, or the same size on each (D55).
- **Bridge to December:** a waterfall from the last print to December, by component or base effect vs momentum (D50).
- **Beat the model:** readers enter a December guess, scored with the model's once Eurostat publishes (D51).
- **Interview demo:** `#demo` in the URL or Shift+D opens a 23-step presenter script with speaker notes (D43, D48).

## Ask the dashboard (optional, needs an API key)

A chat panel that answers only from `ask_facts.json`, a fact sheet of about 500 numbers built by `run.py`.
- The LLM must cite a fact for every number it writes, and code checks each one. An answer that fails the check is not shown.
- "Go to" buttons take you to the section that shows the answer.
- What-if questions run in the shock engine, not in the LLM.
- "Explain this" sits under every chart.

Design, limits and live checks: D34–D37.

## Natural-language scenario builder (optional)

Type "gas +40% in Germany and Italy, fading over 6 months" in the simulator. An LLM only fills a small
schema (components, countries, the user's own numbers, the time-path phrase); Brent → fuel and every other
conversion is deterministic code; you confirm the interpretation before the engine runs it. It never
produces a number or a forecast. Code: `src/hicp/nl_scenario.py`; deployment (Vercel, with a spend cap):
`deploy/README.md`; design and limits: D22. The page works without it.

## Data sources (verified against the live API, 19 Oct 2026)

Base URL: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<dataset>` (JSON-stat 2.0).

| Dataset | Content | Key dimensions used | Coverage seen |
|---|---|---|---|
| `prc_hicp_minr` | Monthly HICP index and rates, ECOICOP ver.2 | `coicop18`, `unit` = `I25` / `RCH_A` / `RCH_M`, `geo` | 1996-01 → 2026-09 |
| `prc_hicp_iw` | Item weights, ‰ | `coicop18`, `geo` | 1996 → 2026 |
| `prc_hicp_cw` | Country weights, ‰ of euro area\* | `statinfo=COWEA`, `geo` | 1996 → 2026 (BG from 2026) |
| `prc_hicp_ctr` | Official contributions to EA annual inflation, pp | `coicop18` (NRG, FOOD, FOOD_P, FOOD_NP, IGD_NNRG, SERV) | 2002-01 → 2026-09 |
| `prc_hicp_fpd` | Flash (`FLS`) and first full (`FIN`) releases | `release` | flash to 2026-09 |

External (public, no key; last observation at the 19 Oct 2026 pull):

| Source | Series | Last obs. |
|---|---|---|
| EC Weekly Oil Bulletin | EA weighted pump prices with taxes (euro95, diesel, heating oil), EUR/1000 l | 2026-10-12 |
| FRED `DCOILBRENTEU` | Brent spot, USD/bbl | 2026-10-14 |
| ECB `EXR.D.USD.EUR.SP00.A` | USD per EUR reference rate | 2026-10-19 |

Not used: legacy ECOICOP ver.1 datasets (`prc_hicp_midx`, `prc_hicp_inw`, `prc_hicp_cow`). They are frozen at 2025.

**Euro area\*** = `geo=EA`, labelled by Eurostat "Euro area (EA11-1999, EA12-2001, EA13-2007,
EA15-2008, EA16-2009, EA17-2011, EA18-2014, EA19-2015, EA20-2023, EA21-2026)". The country
weights confirm membership year by year (gate V7). See `docs/DECISIONS.md` D2.

**COICOP ver.2 history is a back-cast.** Months 1996-01 to 2016-12 carry Eurostat flag `d`
(definition differs), and 2017-01 carries `b` (break). See D3.

## Modelled components (partition of the basket, Σ = 1000‰ every year from 2001)

| Code | Component |
|---|---|
| `FUEL` | Liquid fuels and fuels for personal transport |
| `ELC_GAS` | Electricity, gas, solid fuels and heat |
| `FOOD_P` | Processed food incl. alcohol and tobacco |
| `FOOD_NP` | Unprocessed food |
| `IGD_NNRG` | Non-energy industrial goods |
| `SERV` | Services |

## Validation gates (latest run)

| Gate | Check | Result |
|---|---|---|
| V1 | Schema, dtypes, units, codes | pass |
| V2 | No gaps or duplicates, common last period (157 series) | pass |
| V3 | Weights sum to 1000‰ (EA max gap 0.02‰; country weights 0.03‰) | pass |
| V4 | Headline rebuilt from 6 components, recursive chain-link, 309 months | pass: YoY max 0.030pp, mean 0.007pp |
| V5 | Exact contributions vs official `prc_hicp_ctr`, 1,782 obs | pass: max 0.009pp, mean 0.003pp |
| V6 | EA rebuilt from 21 countries × country weights | pass: YoY max 0.039pp |
| V7 | Membership by year = accession dates; enlargement years | pass |
| V8 | Robust-z outliers on seasonally-demeaned m/m | warn: 61 flagged, kept |
| V9 | Freshness | pass: Sep 2026, 19 days after month-end |

## How AI was used

Claude Code helped write the code. Every modelling and data decision is logged with its
alternative in `docs/DECISIONS.md`, and I reviewed and understood each one.
