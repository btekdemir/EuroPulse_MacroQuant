"""Every number in the deck, read from the pipeline's validated outputs (D72).

    python deck/deck_data.py   ->  deck/deck_data.json   (then: node deck/build_deck.js)

Nothing is typed in by hand: the forecast, fan, drivers, backtest, validation, reconciliation and pre-registration
figures come from outputs/*.json, and the shock path is recomputed with the same engine the dashboard uses
(hicp.shocks.simulate on the preset in outputs/shock_basis.json). Re-run after `python run.py` and the deck follows.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hicp.outlook import prob_above  # noqa: E402
from hicp.schemas import ShockBasis  # noqa: E402
from hicp.shocks import simulate  # noqa: E402

OUT = ROOT / "outputs"
GAS = "European gas price spike"


def load(name: str) -> dict:
    return json.loads((OUT / name).read_text())


def main() -> None:
    f, bt, val, rc = load("forecast.json"), load("backtest_metrics.json"), load("validation_report.json"), load("reconciliation.json")
    r4, man, led = load("round4.json"), load("run_manifest.json"), load("ledger_scores.json")
    basis = ShockBasis.model_validate_json((OUT / "shock_basis.json").read_text())
    dec = f["points"][-1]
    m = {(x["model"], x["h"], x["sample"]): x for x in bt["metrics"]}
    cov = {(c["sample"], c["h"]): c for c in f["fan_coverage"]}
    june = next(x for x in bt["track"] if x["model"] == "bottom_up" and x["h"] == 3 and x["target"] == "2022-06")
    june_rw = next(x for x in bt["track"] if x["model"] == "RW" and x["h"] == 3 and x["target"] == "2022-06")
    gas = next(p for p in basis.presets if p.name == GAS)
    g = simulate(gas, basis)
    oil = simulate(basis.presets[0], basis)
    k_dec = g.months.index(dec["date"])
    gates = val["gates"]
    v8 = next(g_ for g_ in gates if g_["gate"] == "V8")
    holm = {d["name"]: d for d in r4["holm"]}
    adopted = holm[r4["adopted"]]
    n_tests = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True).stdout
    # pytest -q prints "file.py: N" per test file (this project's pytest config)
    n_tests = sum(int(line.rsplit(":", 1)[1]) for line in n_tests.splitlines() if line.startswith("tests/") and line.rsplit(":", 1)[1].strip().isdigit())

    data = {
        "origin": f["origin"], "target": dec["date"], "code_version": man["code_version"], "run_at": man["run_at"][:10],
        "forecast": {
            "point": dec["point"], "q05": dec["quantiles"]["q05"], "q16": dec["quantiles"]["q16"],
            "q84": dec["quantiles"]["q84"], "q95": dec["quantiles"]["q95"], "last_actual": f["last_actual_yoy"],
            "ecb_target": f["ecb_target"], "base_effect_pp": dec["base_effect_pp"], "momentum_pp": dec["momentum_pp"],
            "contrib_serv": dec["contributions"]["SERV"], "contrib_fuel": dec["contributions"]["FUEL"],
            "fuel_yoy": dec["component_yoy"]["FUEL"],
            "p_above_4": 100 * prob_above(dec["point"], f["error_samples"]["3"], 4.0),
            "path": [{"date": p["date"], "point": p["point"], **{q: p["quantiles"][q] for q in ("q05", "q16", "q84", "q95")}} for p in f["points"]],
            "history": [{"date": h["date"], "yoy": h["yoy"]} for h in f["history"][-24:]],
        },
        "validation": {"n_gates": len(gates), "n_pass": sum(g_["status"] == "pass" for g_ in gates),
                       "warn": [g_["gate"] for g_ in gates if g_["status"] == "warn"],
                       "fail": [g_["gate"] for g_ in gates if g_["status"] == "fail"]},
        "recon": {"n_months": int(rc["stats"]["n_months"]), "yoy_max_pp": rc["stats"]["yoy_max_abs_err_pp"],
                  "contrib_max_pp": rc["stats"]["contrib_max_abs_err_pp"], "match_1dp_share": 100 * rc["stats"]["match_official_1dp_share"]},
        "backtest": {
            "first_origin": bt["first_origin"], "last_origin": bt["last_origin"],
            "by_h": [{"h": h, "rmse": m[("bottom_up", h, "full")]["rmse"], "rmse_rw": m[("bottom_up", h, "full")]["rmse_rw"],
                      "ratio": m[("bottom_up", h, "full")]["rmse_ratio_vs_rw"], "dm_p": m[("bottom_up", h, "full")]["dm_p"]} for h in (1, 2, 3)],
            "n_origins_h3": m[("bottom_up", 3, "full")]["n"],
            "ratio_h3": {s: m[("bottom_up", 3, s)]["rmse_ratio_vs_rw"] for s in ("2010-2019", "2020-2023", "2024-now")},
            "bias_crisis_h3": m[("bottom_up", 3, "2020-2023")]["bias"],
            "in68_crisis_h3": 100 * cov[("2020-2023", 3)]["in68"], "in68_calm_h3": 100 * cov[("2010-2019", 3)]["in68"],
            "june2022": {"origin": june["origin"], "fc": june["fc"], "rw": june_rw["fc"], "actual": june["actual"]},
        },
        "rounds": {"n": 4, "adopted": r4["adopted"], "adopted_p": adopted["p"], "adopted_threshold": adopted["threshold"],
                   # Holm step-down: the smallest of m p-values is compared with alpha/m, so its adjusted p is m * p
                   "adopted_p_holm": min(1.0, len(r4["holm"]) * adopted["p"]), "n_tests_in_round": len(r4["holm"]),
                   # the frozen model's forecast for the target, first recorded in the ledger: where prospective scoring starts
                   "freeze_date": min(x["recorded_at"][:10] for x in led["rows"] if x["target"] == dec["date"] and abs(x["point"] - dec["point"]) < 1e-9)},
        "models": dict(f["selected_models"]),
        "v8": {"name": v8["name"], "message": v8["message"]},
        "shock": {
            "name": gas.name, "size_pct": gas.legs[0].size_pct, "ramp_months": gas.legs[0].profile.months, "start": gas.legs[0].start,
            "months": g.months, "first_round_pp": g.delta_first_round_pp, "total_pp": g.delta_yoy_pp,
            "peak_pp": g.peak_pp, "peak_month": g.peak_month, "dec_pp": g.delta_yoy_pp[k_dec], "dec_shocked": g.shocked_yoy[k_dec],
            "oil_peak_pp": oil.peak_pp, "oil_peak_month": oil.peak_month, "brent_elasticity": basis.fuel_brent_elasticity["total"],
            "brent_elasticity_se": basis.fuel_brent_elasticity["total_se"], "assumptions": list(basis.assumptions),
        },
        "n_python_tests": n_tests,
    }
    (ROOT / "deck" / "deck_data.json").write_text(json.dumps(data, indent=1))
    print("deck/deck_data.json written:", data["forecast"]["point"], data["shock"]["peak_pp"], n_tests, "tests")


if __name__ == "__main__":
    main()
