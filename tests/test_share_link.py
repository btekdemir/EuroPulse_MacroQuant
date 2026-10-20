"""Shareable scenario links (#s=...): round trip, and untrusted links are rejected or sanitised."""

import json
import shutil
import subprocess

import pytest

from hicp.config import ROOT
from hicp.schemas import Scenario, ShockBasis
from hicp.shocks import simulate

BASIS = ROOT / "outputs" / "shock_basis.json"
pytestmark = [pytest.mark.skipif(shutil.which("node") is None, reason="node not installed"),
              pytest.mark.skipif(not BASIS.exists(), reason="run `python run.py` first")]


def node(script: str, payload) -> object:
    js = f"""
      const E = require({json.dumps(str(ROOT / 'dashboard' / 'shock_engine.js'))});
      const basis = JSON.parse(require('fs').readFileSync({json.dumps(str(BASIS))}, 'utf8'));
      const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      {script}
    """
    out = subprocess.run(["node", "-e", js], input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_presets_round_trip_and_simulate_identically():
    basis = ShockBasis.model_validate_json(BASIS.read_text())
    scs = [p.model_dump(mode="json") for p in basis.presets]
    back = node("process.stdout.write(JSON.stringify(input.map(s => E.decodeScenario(E.encodeScenario(s), basis))))", scs)
    for sc, res in zip(scs, back, strict=True):
        dec = Scenario.model_validate(res["scenario"])  # still a valid scenario for the Python schema
        assert simulate(dec, basis).delta_yoy_pp == simulate(Scenario.model_validate(sc), basis).delta_yoy_pp


def test_unicode_survives():
    sc = ShockBasis.model_validate_json(BASIS.read_text()).presets[0].model_dump(mode="json")
    sc["rationale"] = "Électricité +40 % — scénario « test » " * 2
    r = node("process.stdout.write(JSON.stringify(E.decodeScenario(E.encodeScenario(input), basis)))", sc)
    assert r["scenario"]["rationale"] == sc["rationale"]


@pytest.mark.parametrize("mutate", [
    lambda s: s["legs"][0].update(size_pct=500),
    lambda s: s["legs"][0].update(components=["NOT_A_COMPONENT"]),
    lambda s: s["legs"][0].update(countries=["XX"]),
    lambda s: s["legs"][0].update(start="1999-01"),
    lambda s: s["legs"][0].update(profile={"kind": "temporary", "months": 99}),
    lambda s: s.update(legs=[]),
    lambda s: s.update(legs=s["legs"] * 7),
    lambda s: s.update(legs=[None]),  # used to throw during page start-up (code review)
    lambda s: s["legs"][0].update(profile={"kind": "custom", "fractions": [1000]}),  # would bypass the size limit
])
def test_bad_links_are_rejected(mutate):
    sc = ShockBasis.model_validate_json(BASIS.read_text()).presets[0].model_dump(mode="json")
    mutate(sc)
    r = node("process.stdout.write(JSON.stringify(E.decodeScenario(E.encodeScenario(input), basis)))", sc)
    assert "error" in r and "scenario" not in r


def test_garbage_and_extra_fields():
    sc = ShockBasis.model_validate_json(BASIS.read_text()).presets[0].model_dump(mode="json")
    sc["evil"] = "<script>"
    sc["legs"][0]["extra"] = 1
    r = node("""process.stdout.write(JSON.stringify([E.decodeScenario('%%%not-base64', basis),
                                                     E.decodeScenario(E.encodeScenario(input), basis)]))""", sc)
    assert r[0] == {"error": "unreadable"}
    Scenario.model_validate(r[1]["scenario"])  # extra fields dropped (the schema forbids extras)
