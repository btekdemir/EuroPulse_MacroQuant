"""Access code for the paid routes (D45): enforced before any LLM call when HICP_ACCESS_CODE is set."""

import importlib.util
import json
import subprocess
import sys
import types

import pytest

from hicp.config import ROOT
from hicp.schemas import DraftAnswer

pytestmark = pytest.mark.skipif(not (ROOT / "outputs" / "ask_facts.json").exists(), reason="run `python run.py` first")


class Boom:
    """A client that fails the test if it is ever called."""
    def __init__(self):
        self.messages = types.SimpleNamespace(parse=self._no)

    def _no(self, **kw):
        raise AssertionError("the LLM was called without a valid access code")


class Ok:
    def __init__(self):
        self.messages = types.SimpleNamespace(parse=lambda **kw: types.SimpleNamespace(
            parsed_output=DraftAnswer(answerable=False, answer="Not covered.", citations=[], goto=None, goto_country=None,
                                      scenario_request=False, preset=None), stop_reason="end_turn"))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_fn_access", ROOT / "deploy" / "api" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def fns():
    subprocess.run([sys.executable, str(ROOT / "deploy" / "prepare.py")], check=True, capture_output=True)
    return _load("ask"), _load("scenario")


def test_code_required_when_set(fns, monkeypatch):
    ask, scen = fns
    monkeypatch.setenv("HICP_ACCESS_CODE", "correct-horse")
    for body in ({"question": "q"}, {"question": "q", "access_code": "wrong"}, {"question": "q", "access_code": 123}):
        status, out = ask.handle(json.dumps(body).encode(), f"ip-{body.get('access_code')}", client=Boom())
        assert status == 401 and json.loads(out)["code_required"] is True
    status, _ = scen.handle(json.dumps({"text": "gas +40%"}).encode(), "ip-s", client=Boom())
    assert status == 401
    status, out = ask.handle(json.dumps({"question": "q", "access_code": "correct-horse"}).encode(), "ip-ok", client=Ok())
    assert status == 200 and json.loads(out)["verified"]


def test_open_when_unset(fns, monkeypatch):
    ask, _ = fns
    monkeypatch.delenv("HICP_ACCESS_CODE", raising=False)
    status, _ = ask.handle(json.dumps({"question": "q"}).encode(), "ip-open", client=Ok())
    assert status == 200


def test_wrong_codes_are_rate_limited(fns, monkeypatch):
    ask, _ = fns
    monkeypatch.setenv("HICP_ACCESS_CODE", "correct-horse")
    codes = [ask.handle(json.dumps({"question": "q", "access_code": f"guess{i}"}).encode(), "ip-brute", client=Boom())[0]
             for i in range(ask.PER_MINUTE + 1)]
    assert codes[:-1] == [401] * ask.PER_MINUTE and codes[-1] == 429
