"""The dashboard is one offline file built only from validated outputs."""

import json
import re

import pytest

from hicp.config import ROOT

OUT = ROOT / "outputs"
pytestmark = pytest.mark.skipif(not (OUT / "shock_basis.json").exists(), reason="run `python run.py` first")


@pytest.fixture(scope="module")
def html():
    import sys
    sys.path.insert(0, str(ROOT))
    from dashboard.build_dashboard import build
    return build(OUT).read_text()


def test_self_contained_no_external_resources(html):
    assert not re.search(r'<script[^>]+src=', html)
    assert not re.search(r'<link[^>]+href="https?:', html)
    assert "__DATA__" not in html and "__PLOTLY__" not in html and "__APP__" not in html


def test_embedded_data_is_the_validated_outputs(html):
    payload = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    data = json.loads(payload.replace("<\\/", "</"))
    forecast = json.loads((OUT / "forecast.json").read_text())
    assert data["forecast"]["points"][-1]["point"] == forecast["points"][-1]["point"]
    assert set(data) == {"forecast", "backtest", "validation", "manifest", "basis", "countries", "ledger", "nl_examples", "research_note", "round2", "i18n"}


def test_every_i18n_key_used_in_the_page_exists_in_both_languages():
    i18n = json.loads((ROOT / "dashboard" / "i18n.json").read_text())
    assert set(i18n["en"]) == set(i18n["fr"])
    src = (ROOT / "dashboard" / "template.html").read_text() + (ROOT / "dashboard" / "app.js").read_text()
    used = set(re.findall(r'data-i18n="([a-z0-9_]+)"', src)) | set(re.findall(r'\bt\("([a-z0-9_]+)"', src))
    static = {k for k in used if not k.endswith("_")}  # "c_" etc. are prefixes of dynamic keys
    assert static - set(i18n["en"]) == set()
    basis = json.loads((OUT / "shock_basis.json").read_text())
    dynamic = ({f"c_{c}" for c in basis["components"]} | {f"g_{g}" for g in basis["countries"] + ["EA"]}
               | {f"st_{s}" for s in ("pass", "warn", "fail")} | {f"regime_{r}" for r in basis["second_round"]}
               | {f"prof_{p}" for p in ("permanent", "decaying", "temporary", "ramp", "custom")}
               | {f"preset_{i}" for i in range(len(basis["presets"]))}
               | {f"sample_{s}" for s in ("full", "selection", "holdout", "2010-2019", "2020-2023", "2024-now")}
               | {f"m_{m}" for m in ("bottom_up", "bottom_up_SM", "direct_AR", "direct_SM", "RW")})
    assert dynamic - set(i18n["en"]) == set()
