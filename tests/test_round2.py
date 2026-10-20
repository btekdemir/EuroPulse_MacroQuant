"""Round-2 machinery: Holm step-down and the information set of the intercept correction."""

import pandas as pd
import pytest

from hicp.round2 import holm


def test_holm_step_down():
    d = {x["name"]: x for x in holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5})}
    # sorted p: 0.01 (thr .0125) rejected, 0.03 (thr .0167) not -> stop
    assert d["a"]["rejected"] and not d["c"]["rejected"] and not d["b"]["rejected"] and not d["d"]["rejected"]
    assert d["a"]["threshold"] == pytest.approx(0.05 / 4) and d["c"]["threshold"] == pytest.approx(0.05 / 3)


def test_holm_all_rejected_when_all_small():
    assert all(x["rejected"] for x in holm({"a": 0.001, "b": 0.002, "c": 0.003, "d": 0.004}))


def test_holm_gated_candidate_counts_as_p_one():
    out = {x["name"]: x for x in holm({"a": 0.01, "gated": None})}
    assert out["gated"]["p"] is None and not out["gated"]["rejected"] and out["a"]["threshold"] == pytest.approx(0.025)


def test_intercept_correction_uses_only_errors_known_at_the_origin():
    """Mirror of the selection rule inside intercept_corrected: targets <= origin, last three."""
    err = pd.Series([1.0, 2.0, 3.0, 4.0], index=pd.date_range("2020-01-01", periods=4, freq="MS"))
    t = pd.Timestamp("2020-03-01")
    known = err[err.index <= t].dropna().sort_index().iloc[-3:]
    assert list(known) == [1.0, 2.0, 3.0] and known.mean() == 2.0  # April's error is not used
