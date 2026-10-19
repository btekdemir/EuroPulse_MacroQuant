"""One command: ingest → clean → validate → (forecast → backtest → shocks → export → dashboard).

    python run.py              # live Eurostat pull (cached raw JSON is reused if the vintage is unchanged)
    python run.py --offline    # replay the latest cached vintage, no network

Stages after validation are added as they are built. A failed critical validation gate stops
the run before any forecast is produced.
"""

from __future__ import annotations

import argparse
import logging
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from hicp.clean import clean_all  # noqa: E402
from hicp.config import ROOT, load_settings  # noqa: E402
from hicp.ingest import pull_all  # noqa: E402
from hicp.schemas import DataVintage, RunManifest, export_json_schemas, write_json  # noqa: E402
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="replay cached raw pulls, no network")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t0 = time.perf_counter()
    s = load_settings()
    out = s.outputs_dir

    log.info("1/3 ingest (%s)", "offline" if args.offline else "live")
    raw, pulls = pull_all(s, offline=args.offline)

    log.info("2/3 clean")
    data = clean_all(raw, s)
    data.save(s)

    log.info("3/3 validate")
    report = run_all(data, s, {p.name: p.updated for p in pulls})
    write_json(report, out / "validation_report.json")
    for g in report.gates:
        log.info("  %s %-4s %s", g.gate, g.status.value.upper(), g.message)

    manifest = RunManifest(
        run_at=datetime.now(timezone.utc), code_version=git_version(), config_hash=s.config_hash(),
        python=platform.python_version(), offline=args.offline, last_period=report.last_period,
        vintages=[DataVintage(name=p.name, dataset=p.dataset, updated=p.updated, sha256=p.sha256,
                              n_values=p.n_values, fetched_at=p.fetched_at, from_cache=p.from_cache,
                              raw_file=str(p.path.relative_to(ROOT))) for p in pulls],
        runtime_seconds=round(time.perf_counter() - t0, 1))
    write_json(manifest, out / "run_manifest.json")
    export_json_schemas(out / "schemas")

    if report.blocking:
        log.error("critical validation gate(s) failed: %s. Stopping before the forecast.",
                  ", ".join(f"{g.gate} ({g.message})" for g in report.blocking))
        return 2
    log.info("validation %s; done in %.1fs", report.summary, time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
