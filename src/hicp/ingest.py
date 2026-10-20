"""Eurostat ingestion: JSON-stat 2.0 over the dissemination API, with a raw cache.

Every request is cached as gzipped JSON under ``data/raw/<dataset>/``. The file name holds a hash
of the query and Eurostat's own ``updated`` timestamp (the dataset vintage), so:

* re-running on the same vintage rewrites nothing (idempotent);
* a new Eurostat release produces a new file next to the old one (vintages are kept);
* ``offline=True`` replays the latest cached vintage of each query without network access.

No manual CSV anywhere: the clean layer (``clean.py``) is built only from these raw payloads.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from hicp.config import Settings

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """A source could not be fetched or parsed."""


@dataclass(frozen=True)
class Pull:
    """One cached API response: the dataset vintage and where it lives on disk."""

    name: str
    dataset: str
    updated: str          # Eurostat's "updated" field: the dataset vintage
    path: Path
    sha256: str
    n_values: int
    fetched_at: str
    from_cache: bool


def build_session(retries: int = 5) -> requests.Session:
    retry = Retry(total=retries, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}), respect_retry_after_header=True)
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def parse_jsonstat(payload: dict[str, Any]) -> pd.DataFrame:
    """Flatten a JSON-stat 2.0 dataset into a long frame: one column per dimension + value + status.

    JSON-stat stores values in a sparse dict keyed by the row-major flat index over all
    dimensions (``size``), so each key decodes to one category per dimension via strides.
    """
    try:
        dim_ids: list[str] = payload["id"]
        sizes: list[int] = payload["size"]
        dims = payload["dimension"]
        values = payload.get("value", {}) or {}
        status = payload.get("status", {}) or {}
    except (KeyError, TypeError) as exc:
        raise SourceError(f"payload is not JSON-stat 2.0: {exc}") from exc
    if isinstance(values, list):  # JSON-stat also allows a dense array
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    if isinstance(status, list):
        status = {str(i): v for i, v in enumerate(status) if v}

    codes_by_dim = []
    for d in dim_ids:
        index = dims[d]["category"]["index"]
        codes = np.empty(len(index), dtype=object)
        for code, pos in index.items():
            codes[pos] = code
        codes_by_dim.append(codes)

    keys = list(values.keys())
    flat = np.fromiter((int(k) for k in keys), dtype=np.int64, count=len(keys))
    strides = np.cumprod([1] + sizes[::-1][:-1])[::-1]
    out: dict[str, Any] = {}
    remainder = flat
    for d, stride, codes in zip(dim_ids, strides, codes_by_dim, strict=True):
        pos, remainder = np.divmod(remainder, stride)
        out[d] = codes[pos]
    out["value"] = np.fromiter((np.nan if values[k] is None else values[k] for k in keys),
                               dtype=float, count=len(keys))
    out["status"] = [status.get(k) for k in keys]
    return pd.DataFrame(out)


def _query_hash(dataset: str, params: list[tuple[str, str]]) -> str:
    canon = dataset + "?" + "&".join(f"{k}={v}" for k, v in sorted(params))
    return hashlib.sha256(canon.encode()).hexdigest()[:12]


def _latest_cached(folder: Path, qhash: str) -> Path | None:
    files = sorted(folder.glob(f"{qhash}__*.json.gz"))
    return files[-1] if files else None


def fetch(settings: Settings, name: str, dataset: str, params: list[tuple[str, str]],
          *, offline: bool = False, session: requests.Session | None = None) -> tuple[pd.DataFrame, Pull]:
    """Fetch one Eurostat query (or replay it from cache) and return the parsed long frame."""
    folder = settings.raw_dir / dataset
    folder.mkdir(parents=True, exist_ok=True)
    qhash = _query_hash(dataset, params)

    if offline:
        path = _latest_cached(folder, qhash)
        if path is None:
            raise SourceError(f"[{name}] offline mode but no cached pull for {dataset} ({qhash})")
        raw_bytes = gzip.decompress(path.read_bytes())
        payload = json.loads(raw_bytes)
        from_cache = True
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    else:
        session = session or build_session()
        url = f"{settings.raw['eurostat']['base_url']}/{dataset}"
        t0 = time.perf_counter()
        try:
            resp = session.get(url, params=params + [("format", "JSON"), ("lang", "EN")],
                               timeout=settings.raw["eurostat"]["timeout_seconds"])
        except requests.RequestException as exc:
            raise SourceError(f"[{name}] request failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(f"[{name}] HTTP {resp.status_code}: {resp.text[:300]}")
        raw_bytes = resp.content
        payload = resp.json()
        if "error" in payload:
            raise SourceError(f"[{name}] Eurostat API error: {payload['error']}")
        log.info("[%s] %s: %.1f MB in %.1fs (updated %s)", name, dataset, len(raw_bytes) / 1e6,
                 time.perf_counter() - t0, payload.get("updated"))
        from_cache = False
        fetched_at = datetime.now(timezone.utc).isoformat()

    updated = str(payload.get("updated", "unknown"))
    stamp = updated.replace(":", "").replace("+", "p")
    sha = hashlib.sha256(raw_bytes).hexdigest()
    if not from_cache:
        path = folder / f"{qhash}__{stamp}.json.gz"
        if not path.exists():  # same vintage already cached -> nothing to write
            path.write_bytes(gzip.compress(raw_bytes, mtime=0))
    df = parse_jsonstat(payload)
    if df.empty:
        raise SourceError(f"[{name}] {dataset} returned zero observations")
    pull = Pull(name=name, dataset=dataset, updated=updated, path=path, sha256=sha,
                n_values=len(df), fetched_at=fetched_at, from_cache=from_cache)
    return df, pull


def pull_all(settings: Settings, offline: bool = False) -> tuple[dict[str, pd.DataFrame], list[Pull]]:
    """All Eurostat pulls the pipeline needs. Returns raw long frames keyed by name."""
    cfg = settings.raw
    ds = cfg["eurostat"]["datasets"]
    dim = cfg["eurostat"]["coicop_dimension"]
    ea = settings.ea
    codes = [settings.headline] + settings.components + cfg["aggregates"]
    since = [("sinceTimePeriod", cfg["eurostat"]["start_period"])]
    geo_c = [("geo", g) for g in settings.countries]

    queries = {
        "index_ea": (ds["index"], [("geo", ea)] + [(dim, c) for c in codes]
                     + [("unit", u) for u in cfg["units"]] + since),
        "index_countries": (ds["index"], geo_c + [(dim, c) for c in [settings.headline] + settings.components]
                            + [("unit", "I25")] + since),
        "item_weights": (ds["item_weights"], [("geo", ea)] + geo_c
                         + [(dim, c) for c in codes + cfg.get("extra_weight_codes", [])]),
        "country_weights": (ds["country_weights"], [("statinfo", cfg["country_weights_statinfo"])]),
        "contributions": (ds["contributions"], [("geo", ea)]
                          + [(dim, c) for c in settings.components + cfg["aggregates"]]),
        "ppi_energy": (ds["producer_prices"], [("geo", cfg["ppi"]["geo"]), ("nace_r2", cfg["ppi"]["nace_r2"]),
                                              ("unit", "I21"), ("s_adj", "NSA"), ("indic_bt", "PRC_PRR_DOM")]),
        # Legacy ECOICOP ver.1 first releases: what was actually published at the time, up to Dec 2025 (D29).
        "first_release_legacy": (ds["first_release_legacy"], [("geo", ea), ("coicop", "CP00"), ("unit", "RCH_A")]),
        "first_release": (ds["first_release"], [("geo", ea), (dim, settings.headline),
                                                ("unit", "RCH_A"), ("sinceTimePeriod", "2017-01")]),
    }
    session = None if offline else build_session()
    frames, pulls = {}, []
    for name, (dataset, params) in queries.items():
        df, pull = fetch(settings, name, dataset, params, offline=offline, session=session)
        frames[name] = df
        pulls.append(pull)
    return frames, pulls
