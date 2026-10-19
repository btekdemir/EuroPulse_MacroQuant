# Euro Area HICP: Bottom-up Forecast, Shock Simulation & Dashboard

> Work in progress (19 Oct 2026): data, validation, chain-linking, forecast and backtest are done.
> Shocks, dashboard and deck are next.

## Answer first

**Euro area\* headline HICP, Dec 2026 (h = 3 from the Sep 2026 release): 3.8% YoY**
(68% band 3.5–4.4%, 90% band 3.2–5.1%; Sep actual 3.8%). Path: Oct 3.7%, Nov 3.7%.
The base effect subtracts 0.11pp by December and is already locked in; momentum adds 0.16pp.
Fuels contribute 1.3pp (fuel prices +32% YoY) and services 1.4pp.
Source: `outputs/forecast.json`.

## Quickstart

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py            # live pull → clean → validate → backtest → forecast (~4 min, mostly Eurostat latency)
.venv/bin/python run.py --offline  # replay the cached vintages (~45 s)
.venv/bin/python -m pytest         # tests
```

Outputs, all schema-validated:
- `validation_report.json`
- `forecast.json`
- `backtest_metrics.json`
- `run_manifest.json`

All are in `outputs/`, with JSON Schemas in `outputs/schemas/`.

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

| h | RMSE | Ratio vs random walk | DM p | vs direct AR, p |
|---|---|---|---|---|
| 1 | 0.27pp | 0.72 | 0.009 | 0.013 |
| 2 | 0.49pp | 0.81 | 0.057 | 0.099 |
| 3 | 0.67pp | 0.84 | 0.140 | 0.552 |

The model beats the random walk significantly at h = 1. At h = 3 the RMSE is lower, but not
significantly. It under-predicted the 2021–22 surge (2020–2023 h = 3 bias −0.64pp).
See D14.

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
