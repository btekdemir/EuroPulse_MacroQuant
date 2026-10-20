"""Number check shared by the research note and the dashboard assistant.

Every number token in a text must be a year, or be cited and equal the cited fact at the precision written.
Pure Python (re + pydantic schemas): it runs in the Vercel function, which has no pandas.
"""

from __future__ import annotations

import re

from hicp.schemas import VerifiedNumber

NUM = re.compile(r"(?<![\w.,])[−\-]?\d+(?:[.,]\d+)?")


def _parse(tok: str) -> tuple[float, int]:
    """Value (absolute) and number of decimals as written."""
    s = tok.replace("−", "-").lstrip("-").replace(",", ".")
    return float(s), (len(s.split(".")[1]) if "." in s else 0)


def matches(tok: str, value: float) -> bool:
    """The written number equals the fact's value rounded to the precision written (sign-insensitive: the
    words carry the direction, which this check does not verify)."""
    v, dec = _parse(tok)
    return abs(round(abs(value), dec) - v) < 1e-9


def is_year(tok: str) -> bool:
    return re.fullmatch(r"20\d\d", tok) is not None


def verify(body: str, citations: list, facts: list) -> tuple[list[VerifiedNumber], list[str]]:
    """Every number token in ``body`` must be a year, or be cited and equal the cited fact."""
    by_id = {x.id: x for x in facts}
    cited: dict[str, str] = {}
    for c in citations:
        cited.setdefault(c.number.strip().replace("−", "-").lstrip("-"), c.fact_id)
    nums, problems = [], []
    for m in NUM.finditer(body):
        tok = m.group(0)
        if is_year(tok):
            continue
        key = tok.replace("−", "-").lstrip("-")
        fid = cited.get(key)
        if fid is None:
            nums.append(VerifiedNumber(token=tok, fact_id=None, fact_label=None, fact_value=None, ok=False))
            problems.append(f"'{tok}' is in the text but cites no fact")
        elif fid not in by_id:
            nums.append(VerifiedNumber(token=tok, fact_id=fid, fact_label=None, fact_value=None, ok=False))
            problems.append(f"'{tok}' cites '{fid}', which is not in the fact sheet")
        else:
            ok = matches(tok, by_id[fid].value)
            nums.append(VerifiedNumber(token=tok, fact_id=fid, fact_label=by_id[fid].label, fact_value=by_id[fid].value, ok=ok))
            if not ok:
                problems.append(f"'{tok}' does not equal fact '{fid}' ({by_id[fid].value:.4g}) at that precision")
    return nums, problems
