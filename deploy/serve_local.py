"""Run the dashboard AND the live /api/scenario and /api/ask locally, no Vercel needed.

    python deploy/serve_local.py        # then open http://127.0.0.1:8812

Reads ANTHROPIC_API_KEY from the environment or from .env in the project root (never printed).
Uses exactly the same handler code as the Vercel functions (deploy/api/*.py).
"""

import importlib.util
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("PORT", "8812"))


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env(ROOT / ".env")
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTRHOPIC_API_KEY"):
    print("note: .env has 'ANTRHOPIC_API_KEY' (typo); using it. Rename it to ANTHROPIC_API_KEY.")
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTRHOPIC_API_KEY"]
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("warning: no ANTHROPIC_API_KEY found; the page works but live interpretation will fail.")

subprocess.run([sys.executable, str(ROOT / "deploy" / "prepare.py")], check=True, capture_output=True)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_fn", ROOT / "deploy" / "api" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ROUTES = {"/api/scenario": _load("scenario"), "/api/ask": _load("ask")}
PAGE_FILE = ROOT / "outputs" / "dashboard.html"  # read on every request: always the latest build


class Local(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] in ("/", "/index.html", "/dashboard.html"):
            self._send(200, PAGE_FILE.read_bytes(), "text/html; charset=utf-8")
        elif self.path in ROUTES:
            self._send(405, b'{"error":"POST only."}')  # same as Vercel: tells the page the route exists
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):  # noqa: N802
        fn = ROUTES.get(self.path)
        if fn is None:
            return self._send(404, b'{"error":"not found"}')
        n = min(int(self.headers.get("content-length") or 0), fn.MAX_BODY + 1)
        self._send(*fn.handle(self.rfile.read(n), self.client_address[0]))

    def log_message(self, *a):  # keep the terminal quiet (and free of request bodies)
        pass


print(f"dashboard + live API on http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
HTTPServer(("127.0.0.1", PORT), Local).serve_forever()
