"""The Vercel handler, end to end over HTTP, with a fake LLM client. No network, no API key."""

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from hicp.config import ROOT

pytestmark = pytest.mark.skipif(not (ROOT / "outputs" / "shock_basis.json").exists(), reason="run run.py first")


@pytest.fixture(scope="module")
def fn(tmp_path_factory):
    import subprocess
    import sys
    subprocess.run([sys.executable, str(ROOT / "deploy" / "prepare.py")], check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location("scenario_fn", ROOT / "deploy" / "api" / "scenario.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake(fn):
    from tests.test_nl_scenario import FakeClient, intent
    return FakeClient(parsed=intent(size_pct=12.0, components=["FUEL"], countries=["NL"]))


def test_handle_happy_path_and_errors(fn):
    fn._hits.clear(); fn._day.clear()
    status, body = fn.handle(json.dumps({"text": "petrol +12% in NL"}).encode(), "1.1.1.1", client=_fake(fn))
    out = json.loads(body)
    leg = out["scenario"]["legs"][0]
    assert status == 200 and leg["countries"] == ["NL"] and leg["size_pct"] == 12.0
    assert fn.handle(b"not json", "1.1.1.1")[0] == 400
    assert fn.handle(json.dumps({"text": 5}).encode(), "1.1.1.1")[0] == 400
    assert fn.handle(json.dumps({"text": "x" * 400}).encode(), "1.1.1.1")[0] == 400
    assert fn.handle(b"{" + b" " * 5000 + b"}", "1.1.1.1")[0] == 413


def test_rate_limit_per_ip(fn):
    fn._hits.clear(); fn._day.clear()
    codes = [fn.handle(json.dumps({"text": "gas +5%"}).encode(), "9.9.9.9", client=_fake(fn))[0] for _ in range(fn.PER_MINUTE + 2)]
    assert codes[:fn.PER_MINUTE] == [200] * fn.PER_MINUTE and codes[-1] == 429
    assert fn.handle(json.dumps({"text": "gas +5%"}).encode(), "8.8.8.8", client=_fake(fn))[0] == 200  # other IP unaffected


def test_internal_errors_do_not_leak(fn):
    fn._hits.clear(); fn._day.clear()

    class Boom:
        class messages:
            @staticmethod
            def parse(**kw):
                raise RuntimeError("sk-ant-SECRET-KEY-123 leaked")

    status, body = fn.handle(json.dumps({"text": "gas +5%"}).encode(), "2.2.2.2", client=Boom())
    assert status == 500 and b"SECRET" not in body


def test_real_http_server_roundtrip(fn, monkeypatch):
    fn._hits.clear(); fn._day.clear()
    monkeypatch.setattr(fn, "parse_request",
                        lambda text, basis, client=None, model=None: {"scenario": {}, "interpretation": [text], "intent": {}, "model": "fake"})
    srv = HTTPServer(("127.0.0.1", 0), fn.handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/api/scenario"
        req = urllib.request.Request(url, data=json.dumps({"text": "hello"}).encode(), method="POST")
        with urllib.request.urlopen(req) as r:
            assert r.status == 200 and json.loads(r.read())["interpretation"] == ["hello"]
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url)
        assert e.value.code == 405
    finally:
        srv.shutdown()
