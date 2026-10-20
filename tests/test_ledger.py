"""Forecast ledger: chain integrity, tamper detection, idempotence and scoring. Uses temporary files only."""

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from hicp import ledger
from hicp.config import load_settings


def fake_forecast(origin="2026-09", base=3.7):
    qs = lambda p: {"q05": p - 0.4, "q16": p - 0.2, "q50": p, "q84": p + 0.3, "q95": p + 0.6}  # noqa: E731
    pts = [{"date": d, "horizon": h, "point": base + 0.05 * h, "quantiles": qs(base + 0.05 * h)}
           for h, d in enumerate(["2026-10", "2026-11", "2026-12"], 1)]
    return {"origin": origin, "last_actual_yoy": 3.77, "points": pts, "selected_models": {"FUEL": "PUMP"}}


VINT = {"index_ea": "a" * 64, "oil_bulletin": "b" * 64}
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def rec(path, forecast=None, vint=None, dirty=False):
    return ledger.record(forecast or fake_forecast(), vint or VINT, "abc1234", "cfg", dirty, path=path, now=NOW)


def test_chain_links_and_verifies(tmp_path):
    p = tmp_path / "l.jsonl"
    e1, _ = rec(p)
    e2, why = rec(p, fake_forecast(base=3.9))
    assert e1["prev_hash"] == "GENESIS" and e2["prev_hash"] == e1["entry_hash"] and e2["seq"] == 2
    assert ledger.verify(ledger.read(p)) == [] and "entry 2" in why


def test_identical_forecast_is_not_recorded_twice(tmp_path):
    p = tmp_path / "l.jsonl"
    rec(p)
    entry, why = rec(p)
    assert entry is None and "already recorded" in why and len(ledger.read(p)) == 1
    assert rec(p, vint={**VINT, "oil_bulletin": "c" * 64})[0] is None  # new vintage, same numbers: not a new forecast
    assert rec(p, fake_forecast(base=3.71))[0] is not None  # different numbers: recorded


def test_dirty_tree_is_refused(tmp_path):
    entry, why = rec(tmp_path / "l.jsonl", dirty=True)
    assert entry is None and "uncommitted" in why and not (tmp_path / "l.jsonl").exists()


def test_every_kind_of_tampering_is_detected(tmp_path):
    p = tmp_path / "l.jsonl"
    for b in (3.6, 3.7, 3.8):
        rec(p, fake_forecast(base=b))
    good = ledger.read(p)
    assert ledger.verify(good) == []

    edited = json.loads(json.dumps(good)); edited[1]["forecasts"][2]["point"] = 3.0  # change a past forecast
    assert any("altered" in m for m in ledger.verify(edited))

    removed = good[:1] + good[2:]  # delete the middle entry
    msgs = ledger.verify(removed)
    assert any("removed or reordered" in m for m in msgs) or any("chain broken" in m for m in msgs)

    swapped = [good[1], good[0], good[2]]
    assert ledger.verify(swapped) != []

    rehashed = json.loads(json.dumps(good)); rehashed[1]["forecasts"][2]["point"] = 3.0
    rehashed[1]["entry_hash"] = ledger.hash_entry(rehashed[1])  # fix its own hash...
    assert any("chain broken" in m for m in ledger.verify(rehashed))  # ...but entry 3 no longer links to it

    junk = json.loads(json.dumps(good)); junk[0]["unexpected"] = 1
    assert any("schema" in m for m in ledger.verify(junk))


def test_a_broken_ledger_refuses_new_records(tmp_path):
    p = tmp_path / "l.jsonl"
    rec(p)
    lines = p.read_text().replace("3.75", "9.99")
    p.write_text(lines)
    entry, why = rec(p, fake_forecast(base=4.5))
    assert entry is None and why.startswith("refused")


class FakeData:
    """Minimal CleanData stand-in: a published index and a flash table."""

    def __init__(self, final_months: int, flash_target: str | None = None, flash_value: float = 4.0):
        s = load_settings()
        idx = pd.date_range("2025-01-01", periods=final_months + 13, freq="MS")
        self.index = pd.DataFrame({"date": idx, "geo": s.ea, "coicop": s.headline, "unit": "I25",
                                   "value": 100 * 1.003 ** pd.RangeIndex(len(idx)), "status": None})
        rows = [] if flash_target is None else [{"date": pd.Timestamp(flash_target + "-01"), "release": "FLS", "value": flash_value}]
        self.first_release = pd.DataFrame(rows, columns=["date", "release", "value"])

    def index_wide(self, geo, unit="I25"):
        d = self.index[(self.index.geo == geo) & (self.index.unit == unit)]
        return d.pivot(index="date", columns="coicop", values="value").sort_index()


def test_scoring_statuses_pending_flash_final(tmp_path):
    s = load_settings()
    p = tmp_path / "l.jsonl"
    rec(p)
    entries = ledger.read(p)
    rows = ledger.score(entries, FakeData(final_months=0), s)  # index ends 2026-01 => nothing published
    assert {r.status for r in rows} == {"pending"} and all(r.observed is None for r in rows)

    rows = ledger.score(entries, FakeData(final_months=0, flash_target="2026-10", flash_value=3.9), s)
    oct_row = next(r for r in rows if r.target == "2026-10")
    assert oct_row.status == "flash" and oct_row.observed == 3.9 and oct_row.error == pytest.approx(3.9 - 3.75)
    assert oct_row.random_walk_error == pytest.approx(3.9 - 3.77) and oct_row.in68 is True

    d = FakeData(final_months=9)  # 22 monthly points from 2025-01: the index ends in 2026-10
    rows = ledger.score(entries, d, s)
    assert next(r for r in rows if r.target == "2026-10").status == "final"
    assert next(r for r in rows if r.target == "2026-12").status == "pending"


def test_scores_report_shape_and_broken_chain(tmp_path):
    s = load_settings()
    p = tmp_path / "l.jsonl"
    rec(p)
    ok = ledger.scores_report(FakeData(0), s, p)
    assert ok.verified and ok.n_entries == 1 and len(ok.rows) == 3 and ok.head_hash == ledger.read(p)[-1]["entry_hash"]
    p.write_text(p.read_text().replace("3.75", "3.76"))
    bad = ledger.scores_report(FakeData(0), s, p)
    assert not bad.verified and bad.rows == [] and bad.problems
