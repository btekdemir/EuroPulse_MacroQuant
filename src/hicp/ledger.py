"""Forecast ledger: an append-only, hash-chained record of every forecast the pipeline publishes,
scored automatically when Eurostat releases the figure.

Each entry stores the forecast, the code version (git commit), the config hash and the sha256 of every
raw data pull it used, plus ``prev_hash`` (the previous entry's hash). Changing, deleting or reordering any
past entry breaks the chain, which ``verify`` detects.

What this does and does not prove: it makes after-the-fact edits *detectable* and ties every forecast to
the exact code and data. It is not tamper-proof (whoever controls the file could rebuild the whole chain)
and ``run_at`` is the machine clock. The independent evidence is the git history: commit the ledger and
push it, so a third party's clock (the remote's commit time) dates it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from hicp.clean import CleanData
from hicp.config import ROOT, Settings
from hicp.schemas import LedgerEntry, LedgerForecast, LedgerScoreRow, LedgerScores

log = logging.getLogger(__name__)
LEDGER_PATH = ROOT / "ledger" / "forecast_ledger.jsonl"
GENESIS = "GENESIS"


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def hash_entry(entry: dict) -> str:
    """sha256 of the entry without its own hash field."""
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k != "entry_hash"})).hexdigest()


def read(path: Path = LEDGER_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify(entries: list[dict]) -> list[str]:
    """Empty list = chain intact. Otherwise one message per problem found."""
    problems, prev = [], GENESIS
    for k, e in enumerate(entries, start=1):
        try:
            LedgerEntry.model_validate(e)
        except Exception as exc:  # schema violation counts as tampering or corruption
            problems.append(f"entry {k}: does not match the schema ({str(exc).splitlines()[0]})")
            continue
        if e["seq"] != k:
            problems.append(f"entry {k}: seq is {e['seq']} (entry removed or reordered)")
        if e["prev_hash"] != prev:
            problems.append(f"entry {k}: prev_hash does not match entry {k - 1} (chain broken)")
        if hash_entry(e) != e["entry_hash"]:
            problems.append(f"entry {k}: content does not match its hash (entry altered)")
        prev = e["entry_hash"]
    return problems


def fingerprint(origin: str, forecasts: list[dict], vintages: dict[str, str]) -> str:
    """What makes two runs 'the same forecast': origin, numbers (6 dp) and the data they used."""
    rounded = [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in f.items()} for f in forecasts]
    return hashlib.sha256(canonical({"origin": origin, "forecasts": rounded, "vintages": vintages})).hexdigest()


def make_entry(prev: dict | None, forecast: dict, vintages: dict[str, str], code_version: str, config_hash: str,
               now: datetime | None = None) -> dict:
    pts = forecast["points"]
    entry = {
        "seq": (prev["seq"] + 1) if prev else 1,
        "prev_hash": prev["entry_hash"] if prev else GENESIS,
        "run_at": (now or datetime.now(timezone.utc)).isoformat(),
        "code_version": code_version, "config_hash": config_hash, "origin": forecast["origin"],
        "last_actual_yoy": forecast["last_actual_yoy"],
        "forecasts": [{"target": p["date"], "h": p["horizon"], "point": p["point"], **{k: p["quantiles"][k] for k in ("q05", "q16", "q84", "q95")}}
                      for p in pts],
        "selected_models": forecast["selected_models"], "data_vintages": vintages,
    }
    entry["entry_hash"] = hash_entry(entry)
    LedgerEntry.model_validate(entry)
    return entry


def record(forecast: dict, vintages: dict[str, str], code_version: str, config_hash: str, dirty: bool,
           path: Path = LEDGER_PATH, now: datetime | None = None) -> tuple[dict | None, str]:
    """Append the forecast unless it is a repeat of the last recorded one or the code tree is dirty.
    Returns (entry or None, reason)."""
    entries = read(path)
    problems = verify(entries)
    if problems:
        return None, "refused: existing ledger is broken (" + problems[0] + ")"
    if dirty:
        return None, "not recorded: the code has uncommitted changes, so the commit hash would not identify it"
    # A repeat is the same origin with the same numbers (6 dp), whatever the data vintages: a revised
    # dataset that leaves the forecast unchanged is not a new forecast. (Until 20 Oct 2026 vintages were part
    # of the key, which is why entry 2 repeats entry 1's numbers; see D30.)
    fcs = [{"target": p["date"], "h": p["horizon"], "point": p["point"]} for p in forecast["points"]]
    fp = fingerprint(forecast["origin"], fcs, {})
    for e in entries:
        efc = [{"target": f["target"], "h": f["h"], "point": f["point"]} for f in e["forecasts"]]
        if fingerprint(e["origin"], efc, {}) == fp:
            return None, f"already recorded as entry {e['seq']} (same origin and numbers)"
    entry = make_entry(entries[-1] if entries else None, forecast, vintages, code_version, config_hash, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    return entry, f"recorded as entry {entry['seq']}"


def _observed(d: CleanData, s: Settings) -> tuple[pd.Series, pd.Series]:
    """(final y/y from the published index, flash y/y rate), both indexed by month start."""
    ix = d.index_wide(s.ea)[s.headline]
    final = 100 * (ix / ix.shift(12) - 1)
    fl = d.first_release[d.first_release.release == "FLS"].set_index("date")["value"]
    return final.dropna(), fl


def score(entries: list[dict], d: CleanData, s: Settings) -> list[LedgerScoreRow]:
    final, flash = _observed(d, s)
    rows = []
    for e in entries:
        for f in e["forecasts"]:
            t = pd.Timestamp(f["target"] + "-01")
            if t in final.index:
                status, obs = "final", float(final[t])
            elif t in flash.index:
                status, obs = "flash", float(flash[t])
            else:
                status, obs = "pending", None
            row = {**{k: f[k] for k in ("h", "point", "q05", "q16", "q84", "q95", "target")}, "seq": e["seq"],
                   "recorded_at": e["run_at"], "code_version": e["code_version"], "origin": e["origin"],
                   "random_walk": e["last_actual_yoy"], "status": status, "observed": obs}
            if obs is not None:
                row.update(error=obs - f["point"], random_walk_error=obs - e["last_actual_yoy"],
                           in68=f["q16"] <= obs <= f["q84"], in90=f["q05"] <= obs <= f["q95"])
            rows.append(LedgerScoreRow(**row))
    return rows


def scores_report(d: CleanData, s: Settings, path: Path = LEDGER_PATH) -> LedgerScores:
    entries = read(path)
    problems = verify(entries)
    return LedgerScores(verified=not problems, problems=problems, n_entries=len(entries),
                        head_hash=entries[-1]["entry_hash"] if entries else None,
                        rows=score(entries, d, s) if not problems else [])


if __name__ == "__main__":  # python -m hicp.ledger : verify the chain and print the scored track record
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from hicp.config import load_settings
    st = load_settings()
    rep = scores_report(CleanData.load(st), st)
    print("chain intact" if rep.verified else "CHAIN BROKEN: " + "; ".join(rep.problems), f"({rep.n_entries} entries)")
    for r in rep.rows:
        obs = f"{r.observed:.2f} ({r.status}), error {r.error:+.2f}" if r.observed is not None else "pending"
        print(f"  entry {r.seq} origin {r.origin} -> {r.target} (h={r.h}): forecast {r.point:.2f}, RW {r.random_walk:.2f}, observed {obs}")
    raise SystemExit(0 if rep.verified else 3)
