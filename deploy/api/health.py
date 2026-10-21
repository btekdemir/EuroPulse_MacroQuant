"""Vercel serverless function: GET /api/health (D61).

The page calls it once on load to learn whether the live routes exist and whether they need the access code.
It always answers 200, so a reader who opens the browser console sees no error. It reveals nothing secret:
only whether an access code and an API key are configured, never their values. No paid call.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler


def handle_get() -> tuple[int, bytes]:
    body = {"ok": True, "live": True, "code_required": bool(os.environ.get("HICP_ACCESS_CODE")),
            "assistant": bool(os.environ.get("ANTHROPIC_API_KEY"))}
    return 200, json.dumps(body).encode()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        status, payload = handle_get()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
