"""Build ``outputs/dashboard.html``: one self-contained file, works offline, opens by double-click.

Inputs are only the pipeline's JSON outputs, each re-validated against its pydantic schema here,
so the dashboard can never show a number the schemas did not accept. Plotly is inlined from the
installed ``plotly`` Python package (no CDN).
"""

from __future__ import annotations

import json
from pathlib import Path

import plotly

from hicp.schemas import (BacktestMetrics, CalibrationReport, CountryView, RealtimeReport, Forecast, LedgerScores, NLExamples, ResearchNotes, Round2Report,
                          RunManifest, ShockBasis, ValidationReport, WhatChanged, CoreView, ReconciliationView, Round3Report, Round4Report)

HERE = Path(__file__).resolve().parent

INPUTS = {
    "forecast": ("forecast.json", Forecast),
    "backtest": ("backtest_metrics.json", BacktestMetrics),
    "validation": ("validation_report.json", ValidationReport),
    "manifest": ("run_manifest.json", RunManifest),
    "basis": ("shock_basis.json", ShockBasis),
    "countries": ("countries.json", CountryView),
    "ledger": ("ledger_scores.json", LedgerScores),
    "round2": ("round2.json", Round2Report),
    "calibration": ("calibration.json", CalibrationReport),
    "realtime": ("realtime.json", RealtimeReport),
    "changed": ("what_changed.json", WhatChanged),
    "core": ("core.json", CoreView),
    "recon": ("reconciliation.json", ReconciliationView),
    "round3": ("round3.json", Round3Report),
    "round4": ("round4.json", Round4Report),
}


def _inline_js(code: str) -> str:
    return code.replace("</script", "<\\/script")


def build(out_dir: Path) -> Path:
    data = {}
    for key, (fname, model) in INPUTS.items():
        data[key] = model.model_validate_json((out_dir / fname).read_text()).model_dump(mode="json")
    nl = out_dir / "nl_examples.json"  # optional: recorded outputs of the LLM builder (needs an API run)
    data["nl_examples"] = (NLExamples.model_validate_json(nl.read_text()).model_dump(mode="json")["examples"]
                           if nl.exists() else [])
    note = out_dir / "research_note.json"  # optional: generated on demand with `python -m hicp.note --generate`
    data["research_note"] = None
    if note.exists():
        from hicp.note import build_facts, facts_hash
        rn = ResearchNotes.model_validate_json(note.read_text()).model_dump(mode="json")
        rn["stale"] = rn["facts_hash"] != facts_hash(build_facts(out_dir))  # numbers changed since the note was written
        data["research_note"] = rn
    data["i18n"] = json.loads((HERE / "i18n.json").read_text())
    missing = set(data["i18n"]["en"]) ^ set(data["i18n"]["fr"])
    if missing:
        raise ValueError(f"i18n keys differ between EN and FR: {sorted(missing)}")
    plotly_js = (Path(plotly.__file__).parent / "package_data" / "plotly.min.js").read_text()
    html = (HERE / "template.html").read_text()
    payload = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    for marker, content in (("__DATA__", payload), ("__PLOTLY__", _inline_js(plotly_js)),
                            ("__ENGINE__", _inline_js((HERE / "shock_engine.js").read_text())),
                            ("__APP__", _inline_js((HERE / "app.js").read_text()))):
        html = html.replace(marker, content, 1)
    path = out_dir / "dashboard.html"
    path.write_text(html)
    return path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE.parent / "src"))
    print(build(HERE.parent / "outputs"))
