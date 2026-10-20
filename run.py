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
from hicp.round2 import run_round2  # noqa: E402
from hicp import calibration, realtime  # noqa: E402
from hicp.clean import clean_all  # noqa: E402
from hicp.config import ROOT, load_settings  # noqa: E402
from hicp.external import pull_external, pump_index  # noqa: E402
from hicp.ingest import pull_all  # noqa: E402
from hicp.export import country_view, track, write_shock_outputs  # noqa: E402
from hicp.outlook import build_outlook  # noqa: E402
from hicp.passthrough import estimate_all  # noqa: E402
from hicp.shocks import build_basis, make_presets  # noqa: E402
from hicp.schemas import (BacktestMetrics, CalibrationReport, DataVintage, Forecast, RealtimeReport,  # noqa: E402
                          Round2Report, RunManifest, SelectionStep,
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
    cal = calibration.build(res.headline[res.headline.model == "bottom_up"])
    adopt_b = cal["decision"]["adopt_B"]
    log.info("  fan calibration (D28): scaled fan pinball %.4f vs %.4f fixed, DM p %.3f -> %s",
             cal["decision"]["mean_loss_B"], cal["decision"]["mean_loss_A"], cal["decision"]["dm_p"],
             "ADOPT scaled fan" if adopt_b else "keep current fan")
    write_json(CalibrationReport(rule=CALIBRATION_RULE, decision=_nan_to_none(cal["decision"]),
                                 rows=cal["summary"], sigma=cal["sigma"], live_sigma=cal["live_sigma"],
                                 first_scored=cal["first_scored"]), out / "calibration.json")
    rt = realtime.evaluate(data, res)
    write_json(RealtimeReport(note=REALTIME_NOTE, rows=[_nan_to_none({**{k: v for k, v in r.items() if k not in ("from", "to")},
                                                                       "start": r["from"], "end": r["to"]}) for r in rt]),
               out / "realtime.json")
    for r in rt:
        if r["model"] == "bottom_up":
            log.info("  real time vs %s, h=%d: ratio %.3f (p %.3f); latest vintage %.3f (p %.3f)", r["target"], r["h"],
                     r["ratio"], r["dm_p"], r["ratio_latest_vintage"], r["dm_p_latest_vintage"])

    outlook = build_outlook(inp, res, {h: cal["live"][h]["B_errors"] for h in (1, 2, 3)} if adopt_b else None)
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

    log.info("round 2 (pre-registered, D27): can any candidate beat the random walk at h=3?")
    r2 = run_round2(inp, res, *cfg["selection_sample"])
    write_json(Round2Report(
        rule=ROUND2_RULE, gate={k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r2["gate"].items()},
        holm=r2["holm"], adopted=r2["adopted"],
        metrics=[_nan_to_none({k: r[k] for k in ("model", "h", "sample", "n", "rmse", "rmse_ratio_vs_rw", "dm_p",
                                                  "dm_p_vs_bottom_up", "bias")}) for r in r2["metrics"].to_dict("records")]),
        out / "round2.json")
    for d in r2["holm"]:
        log.info("  %-10s p=%s  Holm threshold %.4f  %s", d["name"], "gated" if d["p"] is None else f"{d['p']:.3f}",
                 d["threshold"], "PASS" if d["rejected"] else "no")
    log.info("  adopted: %s", r2["adopted"] or "none (current model stays, as the rule says)")

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


CALIBRATION_RULE = ("Pre-registered (D28, commit e0bfd11): recursive fans, A fixed width vs B scaled by the RMS of the "
                    "last 12 known one-month errors; h=3 pinball loss over q=.05/.16/.84/.95; adopt B if lower with DM p<0.05.")
REALTIME_NOTE = ("D29: forecasts (latest-vintage inputs) scored against first releases as published: legacy prc_hicp_fp "
                 "(ver.1, CP00) to Dec 2025, prc_hicp_fpd from Jan 2026; random walk = last print as first published.")

ROUND2_RULE = ("Pre-registered (D27, commit 0fb7156): C1 PPI-led ELC_GAS (gated by the D9 rule), C2 equal-weight "
               "bottom-up + direct AR, C3 intercept correction (mean of last 3 known 1-month errors). Family = current "
               "bottom-up + C1..C3, DM vs random walk at h=3 on all origins, Holm at 5%. Adopt the lowest-MSE passing "
               "candidate; otherwise keep the current model.")

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
