"""Copy the generated dashboard, shock basis and the two source modules into deploy/ for Vercel.

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
shutil.copy(ROOT / "outputs" / "shock_basis.json", lib / "shock_basis.json")
for name in ("schemas.py", "nl_scenario.py"):
    shutil.copy(ROOT / "src" / "hicp" / name, lib / "hicp" / name)
(lib / "hicp" / "__init__.py").write_text("")
print("deploy/ ready:", sorted(str(p.relative_to(D)) for p in D.rglob("*") if p.is_file() and "__pycache__" not in str(p)))
