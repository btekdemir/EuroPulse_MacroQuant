"""Country profiles: each country's component contributions add up to its own y/y."""

import json

import pytest

from hicp.config import ROOT

OUT = ROOT / "outputs" / "countries.json"
pytestmark = pytest.mark.skipif(not OUT.exists(), reason="run `python run.py` first")


@pytest.fixture(scope="module")
def view():
    return json.loads(OUT.read_text())


def test_every_member_has_a_profile(view):
    assert set(view["profiles"]) == set(view["yoy"]) and len(view["profiles"]) == 21


def test_contributions_add_up_to_each_countrys_yoy(view):
    gaps = {c: p["max_abs_gap_pp"] for c, p in view["profiles"].items()}
    assert all(g < 0.02 for c, g in gaps.items() if c != "IT"), gaps
    # Italy's published headline is not exactly the weighted sum of its published components (D33):
    # documented and flagged in the dashboard, pinned here so a change is noticed.
    assert 0.05 < gaps["IT"] < 0.2


def test_profile_index_reproduces_published_yoy(view):
    p, n = view["profiles"]["DE"], len(view["dates"]) - 1
    m = view["dates"][n]
    y0, m0 = int(m[:4]), int(m[5:])
    prev = f"{y0 - 1}-{m0:02d}"
    assert 100 * (p["index"][m] / p["index"][prev] - 1) == pytest.approx(view["yoy"]["DE"][n], abs=1e-9)
