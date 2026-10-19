"""JSON-stat parsing, raw-cache idempotence, and schema enforcement."""

import gzip
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from hicp import ingest
from hicp.config import load_settings
from hicp.schemas import GateResult, Status, ValidationReport, write_json

PAYLOAD = {
    "version": "2.0", "class": "dataset", "updated": "2026-10-16T23:00:00+0200",
    "id": ["geo", "coicop18", "time"], "size": [1, 2, 3],
    "dimension": {
        "geo": {"category": {"index": {"EA": 0}}},
        "coicop18": {"category": {"index": {"TOTAL": 0, "NRG": 1}}},
        "time": {"category": {"index": {"2026-07": 0, "2026-08": 1, "2026-09": 2}}},
    },
    # flat index = coicop*3 + time; position 4 (NRG, 2026-08) is missing on purpose
    "value": {"0": 100.0, "1": 100.5, "2": 101.0, "3": 90.0, "5": 92.0},
    "status": {"3": "d"},
}


def test_parse_jsonstat_decodes_row_major_strides():
    df = ingest.parse_jsonstat(PAYLOAD)
    assert len(df) == 5
    row = df[(df.coicop18 == "NRG") & (df.time == "2026-09")].iloc[0]
    assert row.value == 92.0
    assert df[(df.coicop18 == "NRG") & (df.time == "2026-07")].status.iloc[0] == "d"
    assert not ((df.coicop18 == "NRG") & (df.time == "2026-08")).any()


def test_parse_jsonstat_rejects_garbage():
    with pytest.raises(ingest.SourceError):
        ingest.parse_jsonstat({"foo": 1})


class FakeResp:
    status_code = 200

    def __init__(self, payload):
        self.content = json.dumps(payload).encode()
        self._p = payload
        self.text = ""

    def json(self):
        return self._p


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, *a, **k):
        self.calls += 1
        return FakeResp(PAYLOAD)


def test_cache_is_idempotent_and_replays_offline(tmp_path, monkeypatch):
    s = load_settings()
    monkeypatch.setattr(type(s), "raw_dir", property(lambda self: tmp_path))
    sess = FakeSession()
    df1, p1 = ingest.fetch(s, "t", "prc_x", [("geo", "EA")], session=sess)
    df2, p2 = ingest.fetch(s, "t", "prc_x", [("geo", "EA")], session=sess)
    files = list((tmp_path / "prc_x").glob("*.json.gz"))
    assert len(files) == 1 and p1.path == p2.path  # same vintage -> one file
    assert json.loads(gzip.decompress(files[0].read_bytes()))["updated"] == PAYLOAD["updated"]
    df3, p3 = ingest.fetch(s, "t", "prc_x", [("geo", "EA")], offline=True)
    assert p3.from_cache and sess.calls == 2 and df3.equals(df1)


def test_offline_without_cache_fails_loudly(tmp_path, monkeypatch):
    s = load_settings()
    monkeypatch.setattr(type(s), "raw_dir", property(lambda self: tmp_path))
    with pytest.raises(ingest.SourceError, match="offline"):
        ingest.fetch(s, "t", "prc_x", [("geo", "EA")], offline=True)


def test_gate_schema_rejects_bad_values():
    with pytest.raises(ValidationError):
        GateResult(gate="X1", name="n", status=Status.PASS, critical=True, message="m")
    with pytest.raises(ValidationError):
        GateResult(gate="V1", name="n", status=Status.PASS, critical=True, message="m",
                   metrics={"x": float("nan")})
    with pytest.raises(ValidationError):
        GateResult(gate="V1", name="n", status="maybe", critical=True, message="m")


def test_report_blocking_and_write(tmp_path):
    gates = [GateResult(gate="V1", name="a", status=Status.FAIL, critical=True, message="m"),
             GateResult(gate="V8", name="b", status=Status.FAIL, critical=False, message="m")]
    rep = ValidationReport(run_at=datetime.now(timezone.utc), last_period="2026-09", gates=gates)
    assert [g.gate for g in rep.blocking] == ["V1"]
    path = write_json(rep, tmp_path / "r.json")
    assert ValidationReport.model_validate_json(path.read_text()).summary == {"pass": 0, "warn": 0, "fail": 2}
