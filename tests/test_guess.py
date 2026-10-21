"""'Beat the model' guesses (D51): validation, shared store via Upstash REST (faked), access code, no store."""

import importlib.util
import json
import subprocess
import sys

import pytest

from hicp.config import ROOT


@pytest.fixture()
def fn(monkeypatch):
    subprocess.run([sys.executable, str(ROOT / "deploy" / "prepare.py")], check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location("guess_fn", ROOT / "deploy" / "api" / "guess.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    store = {}

    def fake_kv(*cmd):
        op, key = cmd[0], cmd[1]
        lst = store.setdefault(key, [])
        if op == "LPUSH":
            lst.insert(0, cmd[2]); return len(lst)
        if op == "LTRIM":
            del lst[cmd[3] + 1:]; return "OK"
        if op == "LRANGE":
            return lst[cmd[2]:cmd[3] + 1]
        raise AssertionError(op)
    monkeypatch.setattr(m, "kv", fake_kv)
    monkeypatch.delenv("HICP_ACCESS_CODE", raising=False)
    m.store = store
    return m


def post(fn, body, ip="1.1.1.1"):
    status, out = fn.handle_post(json.dumps(body).encode(), ip)
    return status, json.loads(out)


def test_target_is_the_forecast_month(fn):
    f = json.loads((ROOT / "outputs" / "forecast.json").read_text())
    status, out = fn.handle_get()
    body = json.loads(out)
    assert status == 200 and body["shared"] and body["target"] == f["points"][-1]["date"]
    assert body["model"] == pytest.approx(f["points"][-1]["point"])


def test_post_then_read(fn):
    s, out = post(fn, {"name": "  Axel\x07 ", "value": 3.94321})
    assert s == 200 and out["guess"]["name"] == "Axel" and out["guess"]["value"] == 3.94
    g = json.loads(fn.handle_get()[1])["guesses"]
    assert g[0]["name"] == "Axel" and g[0]["value"] == 3.94


@pytest.mark.parametrize("body", [{"value": 3.9}, {"name": "", "value": 3.9}, {"name": "x", "value": "3.9"},
                                  {"name": "x", "value": True}, {"name": "x", "value": 99}, {"name": "x", "value": -6}])
def test_bad_guesses_are_refused(fn, body):
    assert post(fn, body, ip=f"ip-{json.dumps(body)}")[0] == 400


def test_access_code_and_rate_limit(fn, monkeypatch):
    monkeypatch.setenv("HICP_ACCESS_CODE", "secret-code-1")
    assert post(fn, {"name": "B", "value": 3.5}, ip="ip-c")[0] == 401
    assert post(fn, {"name": "B", "value": 3.5, "access_code": "secret-code-1"}, ip="ip-c")[0] == 200
    assert fn.handle_get()[0] == 200  # reading stays open
    codes = [post(fn, {"name": "C", "value": 3.5, "access_code": "secret-code-1"}, ip="ip-r")[0] for _ in range(fn.PER_MINUTE + 1)]
    assert codes[-1] == 429


def test_no_store_means_browser_only(fn, monkeypatch):
    monkeypatch.setattr(fn, "kv", lambda *c: None)
    assert json.loads(fn.handle_get()[1])["shared"] is False
    s, out = post(fn, {"name": "D", "value": 3.7}, ip="ip-n")
    assert s == 503 and out["shared"] is False
