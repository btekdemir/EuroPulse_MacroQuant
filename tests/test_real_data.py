"""Reconciliation against the real Eurostat data (skipped until `python run.py` has run once)."""

import pytest

from hicp.config import load_settings
from hicp.validate import GATES, run_all

s = load_settings()
pytestmark = pytest.mark.skipif(not (s.clean_dir / "index.parquet").exists(),
                                reason="no clean data yet: run `python run.py` first")


@pytest.fixture(scope="module")
def report():
    from hicp.clean import CleanData
    return run_all(CleanData.load(s), s, {})


def gate(report, code):
    return next(g for g in report.gates if g.gate == code)


def test_every_gate_ran(report):
    assert [g.gate for g in report.gates] == [f"V{i}" for i in range(1, len(GATES) + 2)]


def test_no_blocking_failures(report):
    assert report.blocking == [], [g.message for g in report.blocking]


def test_headline_rebuilt_from_components(report):
    m = gate(report, "V4").metrics
    assert m["yoy_max_abs_err_pp"] < 0.06 and m["n_months"] > 300


def test_contributions_match_official(report):
    m = gate(report, "V5").metrics
    assert m["max_abs_err_pp"] < 0.02 and m["n_obs"] > 1500


def test_countries_rebuild_euro_area(report):
    assert gate(report, "V6").metrics["yoy_max_abs_err_pp"] < 0.1


def test_membership_matches_accession_dates(report):
    assert gate(report, "V7").metrics["membership_mismatch_years"] == 0
