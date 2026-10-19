# Euro Area HICP: Bottom-up Forecast, Shock Simulation & Dashboard

> Work in progress (19 Oct 2026): data, validation and chain-linking are done. Forecast, backtest,
> shocks, dashboard and deck are next.

## Quickstart

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py            # live Eurostat pull, then clean and validate (~3 min, mostly Eurostat latency)
.venv/bin/python run.py --offline  # replay the cached vintage (~3 s)
.venv/bin/python -m pytest         # tests
```

Outputs, all schema-validated: `outputs/validation_report.json`, `outputs/run_manifest.json`,
and JSON Schemas in `outputs/schemas/`.

## Data sources (verified against the live API, 19 Oct 2026)

Base URL: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<dataset>` (JSON-stat 2.0).

| Dataset | Content | Key dimensions used | Coverage seen |
|---|---|---|---|
| `prc_hicp_minr` | Monthly HICP index and rates, ECOICOP ver.2 | `coicop18`, `unit` = `I25` / `RCH_A` / `RCH_M`, `geo` | 1996-01 → 2026-09 |
| `prc_hicp_iw` | Item weights, ‰ | `coicop18`, `geo` | 1996 → 2026 |
| `prc_hicp_cw` | Country weights, ‰ of euro area\* | `statinfo=COWEA`, `geo` | 1996 → 2026 (BG from 2026) |
| `prc_hicp_ctr` | Official contributions to EA annual inflation, pp | `coicop18` (NRG, FOOD, FOOD_P, FOOD_NP, IGD_NNRG, SERV) | 2002-01 → 2026-09 |
| `prc_hicp_fpd` | Flash (`FLS`) and first full (`FIN`) releases | `release` | flash to 2026-09 |

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
