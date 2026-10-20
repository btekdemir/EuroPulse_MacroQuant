"""What changed since last month (D39): the re-run equals the backtest, and the parts add up."""

import json

import pandas as pd
import pytest

from hicp.config import ROOT

OUT = ROOT / "outputs"
pytestmark = pytest.mark.skipif(not (OUT / "what_changed.json").exists(), reason="run `python run.py` first")


def test_previous_forecast_is_the_backtest_forecast_from_that_origin():
    wc = json.loads((OUT / "what_changed.json").read_text())
    bt = pd.read_csv(OUT / "backtest_headline_forecasts.csv")
    prev = bt[(bt.model == "bottom_up") & (bt.origin == wc["previous_origin"])].set_index("target").fc
    assert wc["surprise"]["forecast"] == pytest.approx(prev[wc["surprise"]["target"]], abs=1e-9)
    for r in wc["revisions"]:
        assert r["previous"] == pytest.approx(prev[r["target"]], abs=1e-9)


def test_components_add_up_and_current_matches_forecast():
    wc = json.loads((OUT / "what_changed.json").read_text())
    f = json.loads((OUT / "forecast.json").read_text())
    cur = {p["date"]: p["point"] for p in f["points"]}
    assert wc["surprise"]["actual"] == pytest.approx(f["last_actual_yoy"])
    for row in [wc["surprise"], *wc["revisions"]]:
        assert abs(sum(row["by_component"].values()) - row["total_pp"]) < 0.02
    for r in wc["revisions"]:
        assert r["current"] == pytest.approx(cur[r["target"]])
