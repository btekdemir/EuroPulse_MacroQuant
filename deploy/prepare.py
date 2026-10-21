"""Copy the generated dashboard, shock basis, assistant facts and the four source modules into deploy/ for Vercel.

    python run.py && python deploy/prepare.py && cd deploy && vercel --prod

deploy/ has its own requirements.txt (anthropic + pydantic only): the main project's pandas/scipy would
exceed Vercel's function size limit, and the function does not need them.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "deploy"

(D / "public").mkdir(exist_ok=True)
shutil.copy(ROOT / "outputs" / "dashboard.html", D / "public" / "index.html")
lib = D / "api" / "_lib"
(lib / "hicp").mkdir(parents=True, exist_ok=True)
for name in ("shock_basis.json", "ask_facts.json"):
    shutil.copy(ROOT / "outputs" / name, lib / name)
for name in ("schemas.py", "nl_scenario.py", "numcheck.py", "ask.py", "access.py"):
    shutil.copy(ROOT / "src" / "hicp" / name, lib / "hicp" / name)
(lib / "hicp" / "__init__.py").write_text("")
# the "Beat the model" target: the forecast's three-month-ahead month and the model's own point (D51)
import json  # noqa: E402
fc = json.loads((ROOT / "outputs" / "forecast.json").read_text())
p3 = fc["points"][-1]
(lib / "guess_target.json").write_text(json.dumps({"target": p3["date"], "origin": fc["origin"], "model": p3["point"],
                                                   "band68": [p3["quantiles"]["q16"], p3["quantiles"]["q84"]]}))
print("deploy/ ready:", sorted(str(p.relative_to(D)) for p in D.rglob("*") if p.is_file() and "__pycache__" not in str(p)))
