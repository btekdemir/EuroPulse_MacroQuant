"""Optional access code for the paid API routes (/api/ask, /api/scenario).

If the environment variable HICP_ACCESS_CODE is set (on Vercel: a Secret), every request must carry the same
value in its JSON body as "access_code"; otherwise the route answers 401 before any paid call is made. Unset
(local runs, tests), the routes stay open. The comparison is constant-time, and wrong codes count against the
same per-IP rate limit as everything else, so guessing is slow.
"""

from __future__ import annotations

import hmac
import os

ENV = "HICP_ACCESS_CODE"
DENIED = {"error": "Access code required.", "code_required": True}


def allowed(req) -> bool:
    code = os.environ.get(ENV, "")
    if not code:
        return True
    given = req.get("access_code") if isinstance(req, dict) else None
    return isinstance(given, str) and hmac.compare_digest(given.encode(), code.encode())
