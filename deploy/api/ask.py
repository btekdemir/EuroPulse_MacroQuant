"""Vercel serverless function: POST /api/ask  {"question": "...", "history": [...]}  ->  verified answer.

Answers only from ``ask_facts.json`` (built by run.py from the validated outputs); every number in an answer
is checked against the fact it cites (``hicp.numcheck``), and an answer that fails the check is not returned.
Same guards as /api/scenario: the Anthropic account's monthly spend limit (the hard cap), small inputs, a cheap
model, and a best-effort per-IP rate limit (instances do not share memory, so it only slows one client down).
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

from hicp.ask import MAX_QUESTION, answer, load_facts  # noqa: E402

PER_MINUTE = int(os.environ.get("HICP_ASK_PER_MINUTE", "6"))
PER_DAY_INSTANCE = int(os.environ.get("HICP_ASK_PER_DAY_INSTANCE", "300"))
MAX_BODY = 16384

_hits: dict[str, deque] = defaultdict(deque)
_day = deque()
_facts = None


def _facts_cached():
    global _facts
    if _facts is None:
        _facts = load_facts(os.path.join(HERE, "_lib", "ask_facts.json"))
    return _facts


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
        question, history = req.get("question", ""), req.get("history", [])
    except (ValueError, AttributeError):
        return respond(400, {"error": "Send JSON like {\"question\": \"Why is December higher?\"}."})
    if not isinstance(question, str) or not question.strip():
        return respond(400, {"error": "'question' must be a non-empty string."})
    if len(question) > MAX_QUESTION:
        return respond(400, {"error": f"Questions are limited to {MAX_QUESTION} characters."})
    if not isinstance(history, list):
        history = []
    if not allow(ip):
        return respond(429, {"error": "Too many requests. Wait a minute."})
    try:
        return respond(200, answer(question.strip(), _facts_cached(), client=client, history=history,
                                   chart=req.get("chart"), chart_state=req.get("chart_state"),
                                   chart_facts=req.get("chart_facts")))
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
