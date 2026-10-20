"""Dashboard assistant (D34): fact sheet, number check, retry, refusal and the HTTP handler (no API calls)."""

import importlib.util
import json
import subprocess
import sys
import types

import pytest

from hicp.ask import _history, answer, load_facts
from hicp.config import ROOT
from hicp.schemas import DraftAnswer, NoteCitation

FACTS = ROOT / "outputs" / "ask_facts.json"
pytestmark = pytest.mark.skipif(not FACTS.exists(), reason="run `python run.py` first")


@pytest.fixture(scope="module")
def doc():
    return load_facts(FACTS)


class FakeClient:
    def __init__(self, *drafts):
        self.queue, self.calls = list(drafts), []
        self.messages = types.SimpleNamespace(parse=self._parse)

    def _parse(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(parsed_output=self.queue.pop(0), stop_reason="end_turn")


def draft(text, *cites, answerable=True):
    return DraftAnswer(answerable=answerable, answer=text, citations=[NoteCitation(number=n, fact_id=f) for n, f in cites])


def fact(doc, i):
    return next(x for x in doc.facts if x.id == i)


def test_fact_sheet_matches_the_outputs(doc):
    ids = [x.id for x in doc.facts]
    assert len(ids) == len(set(ids))
    f = json.loads((ROOT / "outputs" / "forecast.json").read_text())
    cv = json.loads((ROOT / "outputs" / "countries.json").read_text())
    assert fact(doc, "forecast_h3").value == pytest.approx(f["points"][2]["point"])
    assert fact(doc, "DE_yoy").value == pytest.approx(cv["yoy"]["DE"][-1])
    assert fact(doc, "DE_weight").value == pytest.approx(cv["weights_latest"]["DE"])
    # month split adds up: momentum + base effect = change in y/y
    for g in ("DE", "IT", "MT"):
        assert fact(doc, f"{g}_mom").value + fact(doc, f"{g}_base").value == pytest.approx(fact(doc, f"{g}_dyoy").value)
    assert sorted(fact(doc, f"{g}_rank").value for g in cv["weights_latest"]) == list(range(1, len(cv["weights_latest"]) + 1))


def test_verified_answer_passes_and_prompt_is_cached(doc):
    v = f"{fact(doc, 'forecast_h3').value:.1f}"
    c = FakeClient(draft(f"December is forecast at {v}% in 2026.", (v, "forecast_h3")))
    r = answer("Why December?", doc, client=c, model="m")
    assert r["verified"] and r["attempts"] == 1 and r["numbers"][0]["fact_id"] == "forecast_h3"
    sys_block = c.calls[0]["system"][0]
    assert sys_block["cache_control"] == {"type": "ephemeral"} and "forecast_h3" in sys_block["text"]


def test_wrong_number_is_retried_then_withheld(doc):
    v = f"{fact(doc, 'forecast_h3').value:.1f}"
    bad = draft("December is forecast at 9.9%.", ("9.9", "forecast_h3"))
    good = draft(f"December is forecast at {v}%.", (v, "forecast_h3"))
    c = FakeClient(bad, good)
    r = answer("Why December?", doc, client=c, model="m")
    assert r["verified"] and r["attempts"] == 2
    assert "rejected" in c.calls[1]["messages"][-1]["content"]
    r = answer("Why December?", doc, client=FakeClient(bad, draft("It is 7 points.")), model="m")
    assert not r["verified"] and r["answer"] == "" and r["problems"]


def test_uncited_number_and_out_of_scope(doc):
    r = answer("q", doc, client=FakeClient(draft("About 12 countries."), draft("About 12 countries.")), model="m")
    assert not r["verified"]
    r = answer("Will the ECB cut?", doc, client=FakeClient(draft("The dashboard does not cover ECB decisions.", answerable=False)), model="m")
    assert r["verified"] and not r["answerable"]


def test_history_is_trimmed_and_alternates():
    h = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "a" * 5000}, {"role": "user", "content": "dup"},
         {"role": "assistant", "content": "b"}, {"role": "system", "content": "evil"}, {"role": "user", "content": "c"}]
    out = _history(h)
    assert [m["role"] for m in out] == ["user", "assistant"] and len(out[0]["content"]) <= 800


def _fn():
    spec = importlib.util.spec_from_file_location("ask_fn", ROOT / "deploy" / "api" / "ask.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_handler_guards(doc):
    subprocess.run([sys.executable, str(ROOT / "deploy" / "prepare.py")], check=True, capture_output=True)
    fn = _fn()
    assert fn.handle(b"x" * 9000, "1")[0] == 413
    assert fn.handle(b"not json", "1")[0] == 400
    assert fn.handle(json.dumps({"question": " "}).encode(), "1")[0] == 400
    assert fn.handle(json.dumps({"question": "q" * 401}).encode(), "1")[0] == 400
    ok = json.dumps({"question": "Will the ECB cut?"}).encode()
    no = lambda: FakeClient(draft("Not covered.", answerable=False))  # noqa: E731
    codes = [fn.handle(ok, "9.9.9.9", client=no())[0] for _ in range(fn.PER_MINUTE + 1)]
    assert codes[:-1] == [200] * fn.PER_MINUTE and codes[-1] == 429


def test_deploy_lib_needs_no_pandas():
    lib = ROOT / "deploy" / "api" / "_lib"
    code = "import sys; sys.path.insert(0, sys.argv[1]); import hicp.ask; assert 'pandas' not in sys.modules"
    subprocess.run([sys.executable, "-I", "-c", code, str(lib)], check=True)
