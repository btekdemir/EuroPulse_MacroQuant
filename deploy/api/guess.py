"""Vercel serverless function: "Beat the model" guesses for the December headline print (D51).

    GET  /api/guess                          -> {shared, target, model, guesses: [{name, value, at}]}
    POST /api/guess {name, value, access_code?} -> {ok, guess}

Guesses are kept in a Redis list through the Upstash REST API when KV_REST_API_URL and KV_REST_API_TOKEN are set
(Vercel → Storage → Upstash Redis adds them). Without them the route answers shared=false and the page keeps the
reader's own guess in the browser only. No LLM is involved, so no paid API call. The access code (D45), if set,
is required to post (reading stays open). Names are trimmed to 40 printable characters; values must be a y/y rate
between -5 and 15.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_lib"))

from hicp import access  # noqa: E402

KEY_PREFIX = "hicp:guesses:"
MAX_KEEP = 500
MAX_BODY = 1024
PER_MINUTE = int(os.environ.get("HICP_GUESS_PER_MINUTE", "3"))
_hits: dict[str, deque] = defaultdict(deque)
_target = None


def target() -> dict:
    global _target
    if _target is None:
        with open(os.path.join(HERE, "_lib", "guess_target.json")) as f:
            _target = json.load(f)
    return _target


def kv(*cmd):
    """One Redis command over the Upstash REST API; None when no store is configured."""
    url, token = os.environ.get("KV_REST_API_URL"), os.environ.get("KV_REST_API_TOKEN")
    if not url or not token:
        return None
    req = urllib.request.Request(url, data=json.dumps(list(cmd)).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())["result"]


def allow(ip: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= PER_MINUTE:
        return False
    q.append(now)
    return True


def respond(status: int, body: dict) -> tuple[int, bytes]:
    return status, json.dumps(body, ensure_ascii=False).encode()


def clean_name(name) -> str | None:
    if not isinstance(name, str):
        return None
    s = "".join(ch for ch in name if ch.isprintable()).strip()[:40]
    return s or None


def handle_get() -> tuple[int, bytes]:
    tg = target()
    try:
        raw = kv("LRANGE", KEY_PREFIX + tg["target"], 0, MAX_KEEP - 1)
    except Exception:
        return respond(502, {"error": "The shared store did not answer.", "shared": False, **tg, "guesses": []})
    if raw is None:
        return respond(200, {"shared": False, **tg, "guesses": []})
    guesses = []
    for item in raw:
        try:
            g = json.loads(item)
            guesses.append({"name": str(g["name"])[:40], "value": float(g["value"]), "at": str(g.get("at", ""))[:20]})
        except (ValueError, KeyError, TypeError):
            continue
    return respond(200, {"shared": True, **tg, "guesses": guesses})


def handle_post(raw_body: bytes, ip: str) -> tuple[int, bytes]:
    if len(raw_body) > MAX_BODY:
        return respond(413, {"error": "Request too large."})
    try:
        req = json.loads(raw_body or b"{}")
        name, value = clean_name(req.get("name")), req.get("value")
    except (ValueError, AttributeError):
        return respond(400, {"error": "Send JSON like {\"name\": \"Axel\", \"value\": 3.9}."})
    if name is None:
        return respond(400, {"error": "Give a name (up to 40 characters)."})
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -5 <= value <= 15:
        return respond(400, {"error": "The guess must be a y/y rate between -5 and 15."})
    if not allow(ip):
        return respond(429, {"error": "Too many guesses. Wait a minute."})
    if not access.allowed(req):
        return respond(401, access.DENIED)
    tg = target()
    guess = {"name": name, "value": round(float(value), 2), "at": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())}
    try:
        stored = kv("LPUSH", KEY_PREFIX + tg["target"], json.dumps(guess, ensure_ascii=False))
        if stored is not None:
            kv("LTRIM", KEY_PREFIX + tg["target"], 0, MAX_KEEP - 1)
    except Exception:
        return respond(502, {"error": "The shared store did not answer; your guess is kept in this browser only."})
    if stored is None:
        return respond(503, {"error": "No shared store on this site; your guess is kept in this browser only.", "shared": False})
    return respond(200, {"ok": True, "shared": True, "guess": guess})


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        self._send(*handle_get())

    def do_POST(self):  # noqa: N802
        length = min(int(self.headers.get("content-length") or 0), MAX_BODY + 1)
        ip = (self.headers.get("x-forwarded-for") or self.client_address[0]).split(",")[0].strip()
        self._send(*handle_post(self.rfile.read(length), ip))
