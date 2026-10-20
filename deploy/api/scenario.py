"""Vercel serverless function: POST /api/scenario  {"text": "..."}  ->  {scenario, interpretation, intent, model}.

The API key lives only in the ANTHROPIC_API_KEY environment variable of the Vercel project, never in
the page. Guards, in order of strength:
  1. A monthly spend limit set on the Anthropic account (the hard cap, enforced outside this code).
  2. Input limit (300 characters), small max_tokens, a cheap model.
  3. A best-effort per-IP rate limit below. Serverless instances do not share memory, so this only
     slows a single client down; it is not a guarantee, which is why (1) matters.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_lib"))

from hicp import access  # noqa: E402
from hicp.nl_scenario import NLError, load_basis, parse_request  # noqa: E402

PER_MINUTE = int(os.environ.get("HICP_NL_PER_MINUTE", "6"))
PER_DAY_INSTANCE = int(os.environ.get("HICP_NL_PER_DAY_INSTANCE", "200"))
MAX_BODY = 4096

_hits: dict[str, deque] = defaultdict(deque)
_day = deque()
_basis = None


def _basis_cached():
    global _basis
    if _basis is None:
        _basis = load_basis(os.path.join(HERE, "_lib", "shock_basis.json"))
    return _basis


def allow(ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    while _day and now - _day[0] > 86400:
        _day.popleft()
    if len(q) >= PER_MINUTE or len(_day) >= PER_DAY_INSTANCE:
        return False
    q.append(now)
    _day.append(now)
    return True


def respond(status: int, body: dict) -> tuple[int, bytes]:
    return status, json.dumps(body, ensure_ascii=False).encode()


def handle(raw_body: bytes, ip: str, client=None) -> tuple[int, bytes]:
    """Pure function of the request (testable without a server)."""
    if len(raw_body) > MAX_BODY:
        return respond(413, {"error": "Request too large."})
    try:
        req = json.loads(raw_body or b"{}")
        text = req.get("text", "")
    except (ValueError, AttributeError):
        return respond(400, {"error": "Send JSON like {\"text\": \"gas +40% in Germany\"}."})
    if not isinstance(text, str):
        return respond(400, {"error": "'text' must be a string."})
    if not allow(ip):
        return respond(429, {"error": "Too many requests. Wait a minute."})
    if not access.allowed(req):  # before any paid call; wrong codes are rate-limited like any request
        return respond(401, access.DENIED)
    try:
        return respond(200, parse_request(text, _basis_cached(), client=client))
    except NLError as exc:
        return respond(exc.status, {"error": str(exc)})
    except Exception:  # never leak internals (or keys) to the page
        return respond(500, {"error": "Unexpected error."})


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):  # noqa: N802
        length = min(int(self.headers.get("content-length") or 0), MAX_BODY + 1)
        ip = (self.headers.get("x-forwarded-for") or self.client_address[0]).split(",")[0].strip()
        self._send(*handle(self.rfile.read(length), ip))

    def do_GET(self):  # noqa: N802
        self._send(405, json.dumps({"error": "POST only."}).encode())
