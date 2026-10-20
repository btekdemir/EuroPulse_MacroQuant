"""One command: ingest → clean → validate → (forecast → backtest → shocks → export → dashboard).

    python run.py              # live Eurostat pull (cached raw JSON is reused if the vintage is unchanged)
    python run.py --offline    # replay the latest cached vintage, no network

Stages after validation are added as they are built. A failed critical validation gate stops
the run before any forecast is produced.
"""

from __future__ import annotations

import argparse
import logging
import math
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hicp import backtest as bt  # noqa: E402
from hicp import ledger  # noqa: E402
from hicp.clean import clean_all  # noqa: E402
from hicp.config import ROOT, load_settings  # noqa: E402
from hicp.external import pull_external, pump_index  # noqa: E402
from hicp.ingest import pull_all  # noqa: E402
from hicp.export import country_view, track, write_shock_outputs  # noqa: E402
from hicp.outlook import build_outlook  # noqa: E402
from hicp.passthrough import estimate_all  # noqa: E402
from hicp.shocks import build_basis, make_presets  # noqa: E402
from hicp.schemas import (BacktestMetrics, DataVintage, Forecast, RunManifest, SelectionStep,  # noqa: E402
                          export_json_schemas, write_json)
from hicp.validate import run_all  # noqa: E402

log = logging.getLogger("run")


def git_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def tree_is_dirty() -> bool:
    """Uncommitted changes to anything except the generated folders (outputs/, ledger/, data/)."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", ".", ":!outputs", ":!ledger", ":!data"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        return bool(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="replay cached raw pulls, no network")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t0 = time.perf_counter()
    s = load_settings()
    out = s.outputs_dir

    log.info("1/6 ingest Eurostat (%s)", "offline" if args.offline else "live")
    raw, pulls = pull_all(s, offline=args.offline)
    log.info("2/6 ingest external energy data")
    ext, ext_pulls = pull_external(s, offline=args.offline)
    pulls += ext_pulls

    log.info("3/6 clean")
    data = clean_all(raw, s)
    data.save(s)

    log.info("4/6 validate")
    report = run_all(data, s, {p.name: p.updated for p in pulls})
    write_json(report, out / "validation_report.json")
    for g in report.gates:
        log.info("  %s %-4s %s", g.gate, g.status.value.upper(), g.message)

    if report.blocking:
        write_manifest(s, args, report, pulls, t0)
        log.error("critical validation gate(s) failed: %s. Stopping before the forecast.",
                  ", ".join(f"{g.gate} ({g.message})" for g in report.blocking))
        return 2

    log.info("5/6 backtest (walk-forward, origins from %s) and forecast", s.raw["backtest"]["first_origin"])
    cfg = s.raw["backtest"]
    inp = bt.make_inputs(data, s, pump_index(ext.pump))
    res = bt.run_backtest(inp, cfg["first_origin"], *cfg["selection_sample"], rolling=cfg["rolling_window"])
    outlook = build_outlook(inp, res)
    write_json(Forecast(**outlook), out / "forecast.json")
    write_json(BacktestMetrics(
        rule=RULE, first_origin=cfg["first_origin"], last_origin=f"{inp.index.index.max():%Y-%m}",
        selection_sample=tuple(cfg["selection_sample"]), selected_models=res.choice,
        selection_log=[SelectionStep(**_nan_to_none(r)) for r in res.selection.to_dict("records")],
        metrics=[_nan_to_none(r) for r in res.metrics.to_dict("records")], track=track(res.headline)),
        out / "backtest_metrics.json")
    res.headline.to_csv(out / "backtest_headline_forecasts.csv", index=False, date_format="%Y-%m")
    for r in res.metrics[(res.metrics.model == "bottom_up") & (res.metrics["sample"] == "full")].itertuples():
        log.info("  bottom-up h=%d: RMSE %.2fpp, ratio vs RW %.2f, DM p %.3f", r.h, r.rmse, r.rmse_ratio_vs_rw, r.dm_p)

    log.info("forecast ledger")
    code_version = git_version().removesuffix("-dirty")
    entry, why = ledger.record(outlook, {p.name: p.sha256 for p in pulls}, code_version, s.config_hash(), tree_is_dirty())
    log.info("  %s", why)
    scores = ledger.scores_report(data, s)
    write_json(scores, out / "ledger_scores.json")
    if not scores.verified:
        log.error("  LEDGER CHAIN BROKEN: %s", "; ".join(scores.problems))
    else:
        done = [r for r in scores.rows if r.status != "pending"]
        log.info("  chain intact (%d entries); %d forecasts scored, %d pending", scores.n_entries, len(done),
                 len(scores.rows) - len(done))

    log.info("6/6 shocks, countries and dashboard data")
    pt = estimate_all(inp.index, ext.brent_eur)
    presets = make_presets(data, s, pt, inp.index.index.max())
    basis = build_basis(data, s, outlook, pt, presets)
    for r in write_shock_outputs(basis, out):
        log.info("  preset %-42s peak %+.2fpp in %s", r.scenario.name, r.peak_pp, r.peak_month)
    write_json(country_view(data, s), out / "countries.json")
    try:
        from dashboard.build_dashboard import build
        log.info("  dashboard -> %s", build(out).relative_to(ROOT))
    except ImportError:
        log.warning("  dashboard builder not available")

    write_manifest(s, args, report, pulls, t0)
    log.info("validation %s; done in %.1fs", report.summary, time.perf_counter() - t0)
    return 0 if scores.verified else 3


RULE = ("Keep the simpler model (ladder SM -> AR1 -> richer) unless the richer model has lower MSE and a "
        "Diebold-Mariano p < 0.05 (two-sided, HLN-corrected, NW h-1 lags) on the cumulative 3-month log change, "
        "selection origins 2010-01..2019-12 only. Rolling 120m window only under the same rule.")


def _nan_to_none(r: dict) -> dict:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()}


def write_manifest(s, args, report, pulls, t0) -> None:
    manifest = RunManifest(
        run_at=datetime.now(timezone.utc), code_version=git_version(), config_hash=s.config_hash(),
        python=platform.python_version(), offline=args.offline, last_period=report.last_period,
        vintages=[DataVintage(name=p.name, dataset=p.dataset, updated=p.updated, sha256=p.sha256,
                              n_values=p.n_values, fetched_at=p.fetched_at, from_cache=p.from_cache,
                              raw_file=str(p.path.relative_to(ROOT))) for p in pulls],
        runtime_seconds=round(time.perf_counter() - t0, 1))
    write_json(manifest, s.outputs_dir / "run_manifest.json")
    export_json_schemas(s.outputs_dir / "schemas")


if __name__ == "__main__":
    raise SystemExit(main())
