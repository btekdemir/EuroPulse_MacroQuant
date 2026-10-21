"""Dashboard assistant (D34): fact sheet, number check, retry, refusal and the HTTP handler (no API calls)."""

import importlib.util
import json
import re
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


def draft(text, *cites, answerable=True, goto=None, country=None, scenario=False, preset=None):
    return DraftAnswer(answerable=answerable, answer=text, citations=[NoteCitation(number=n, fact_id=f) for n, f in cites],
                       goto=goto, goto_country=country, scenario_request=scenario, preset=preset)


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
    assert fn.handle(b"x" * 17000, "1")[0] == 413
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


def test_malformed_output_is_retried(doc):
    class Broken(FakeClient):
        def _parse(self, **kw):
            self.calls.append(kw)
            if len(self.calls) == 1:
                raise ValueError("Invalid JSON: EOF while parsing")
            return types.SimpleNamespace(parsed_output=self.queue.pop(0), stop_reason="end_turn")
    c = Broken(draft("Not covered.", answerable=False))
    r = answer("q", doc, client=c, model="m")
    assert r["verified"] and r["attempts"] == 2


def test_goto_is_resolved_only_to_real_sections(doc):
    ok = draft("It is on the Countries tab.", goto="country_profile", country="DE")
    r = answer("Where are Germany's drivers?", doc, client=FakeClient(ok), model="m")
    assert r["goto"] == {"id": "country_profile", "tab": "countries", "target": "cp-card", "country": "DE"}
    r = answer("q", doc, client=FakeClient(draft("x", goto="secret_admin_page", country="DE")), model="m")
    assert r["goto"] is None
    r = answer("q", doc, client=FakeClient(draft("x", goto="backtest", country="DE")), model="m")
    assert r["goto"]["country"] is None  # a country only travels with the country profile


def test_every_section_target_exists_in_the_page():
    from hicp.ask import SECTIONS
    page = (ROOT / "dashboard" / "template.html").read_text()
    for sid, (tab, target, _) in SECTIONS.items():
        assert f'id="{target}"' in page, sid
        assert f'data-tab="{tab}"' in page, sid


def test_scenario_request_passes_through(doc):
    r = answer("What if gas rises 30% in Germany?", doc, model="m",
               client=FakeClient(draft("Building that scenario in the shock simulator.", goto="shock_result", scenario=True)))
    assert r["scenario_request"] and r["goto"]["id"] == "shock_result"
    r = answer("q", doc, model="m", client=FakeClient(draft("Not covered.", answerable=False, scenario=True)))
    assert not r["scenario_request"]  # never for an answer the sheet cannot support


def test_explain_chart_adds_context_and_page_facts(doc):
    good = draft("The peak impact is 0.41 pp.", ("0.41", "page_peak_pp"), goto="shock_result")
    c = FakeClient(good)
    pf = [{"id": "page_peak_pp", "label": "Peak impact of the current shock, pp", "value": 0.4088},
          {"id": "evil id", "label": "x", "value": 1}, {"id": "page_nan", "label": "x", "value": float("nan")},
          {"id": "page_flag", "label": "x", "value": True}]
    r = answer("Explain this chart", doc, client=c, model="m", chart="p-shock", chart_state="Gas DE +30%", chart_facts=pf)
    assert r["verified"] and r["numbers"][0]["fact_id"] == "page_peak_pp"
    msg = c.calls[0]["messages"][-1]["content"]
    assert "[Explain request]" in msg and "page_peak_pp" in msg and "Gas DE +30%" in msg
    assert "evil id" not in msg and "page_nan" not in msg and "page_flag" not in msg
    # without a known chart, page facts are ignored, so the same number cannot be verified
    r = answer("q", doc, model="m", chart="p-nope", chart_facts=pf, client=FakeClient(good, good))
    assert not r["verified"]
    r = answer("q", doc, model="m", chart=["p-shock"], chart_facts=pf, client=FakeClient(good, good))
    assert not r["verified"]


def test_every_chart_is_in_the_page_and_maps_to_a_section():
    from hicp.ask import CHARTS, SECTIONS
    page = (ROOT / "dashboard" / "template.html").read_text()
    for pid, (sec, _) in CHARTS.items():
        assert f'id="{pid}"' in page and sec in SECTIONS, pid
    plots = set(re.findall(r'class="plot[^"]*" id="([a-z0-9-]+)"', page))
    assert plots == set(CHARTS)
    from hicp.ask import TABLES
    for tid, (sec, _) in TABLES.items():
        assert f'id="{tid}"' in page and sec in SECTIONS, tid


def test_more_than_two_decimals_is_sent_back(doc):
    v = fact(doc, "forecast_h3").value
    long_, short = draft(f"December {v:.3f}%.", (f"{v:.3f}", "forecast_h3")), draft(f"December {v:.2f}%.", (f"{v:.2f}", "forecast_h3"))
    c = FakeClient(long_, short)
    r = answer("q", doc, client=c, model="m")
    assert r["verified"] and r["attempts"] == 2 and "two decimals" in c.calls[1]["messages"][-1]["content"]


def test_chart_traces_reach_the_model(doc):
    c = FakeClient(draft("x"))
    answer("q", doc, client=c, model="m", chart="p-headline", chart_traces=["dot line with markers: Forecast", 5, "x" * 500])
    msg = c.calls[0]["messages"][-1]["content"]
    assert "dot line with markers: Forecast" in msg and "x" * 61 not in msg


def test_preset_reference_is_resolved_and_bounded(doc):
    assert doc.presets and "Oil supply shock" in doc.presets[0]
    ok = draft("Running the oil supply shock scenario.", scenario=True, preset=0)
    assert answer("oil supply shock", doc, client=FakeClient(ok), model="m")["preset"] == 0
    for bad in (99, -1):
        r = answer("q", doc, client=FakeClient(draft("x", scenario=True, preset=bad)), model="m")
        assert r["preset"] is None
    assert answer("q", doc, client=FakeClient(draft("x", preset=0)), model="m")["preset"] is None  # not a what-if


def test_small_values_may_keep_three_decimals(doc):
    small = next(x for x in doc.facts if 0.001 < abs(x.value) < 0.1 and "p-value" in x.label)
    tok = f"{abs(small.value):.3f}"
    r = answer("q", doc, client=FakeClient(draft(f"p = {tok}.", (tok, small.id))), model="m")
    assert r["verified"] and r["attempts"] == 1
