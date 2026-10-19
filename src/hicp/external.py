"""External energy data: EC Weekly Oil Bulletin pump prices, Brent (FRED), EUR/USD (ECB).

All three are public and scriptable (no key). Raw downloads are kept byte-for-byte under
``data/raw/<source>/<sha12>.<ext>``; identical content is never rewritten.

* Weekly Oil Bulletin: price-history workbook, sheet "Prices with taxes", euro area weighted
  average (``EUR_price_with_tax_*``), EUR per 1,000 litres, dated on the Monday the price refers
  to. Published a few days later; prices are not revised.
* Brent: FRED ``DCOILBRENTEU`` (Europe Brent spot FOB, USD/bbl, daily), public CSV endpoint.
* EUR/USD: ECB reference rate ``EXR.D.USD.EUR.SP00.A`` (USD per EUR, daily).
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from hicp.config import Settings
from hicp.ingest import Pull, SourceError, build_session

log = logging.getLogger(__name__)

WOB_PRODUCTS = ("euro95", "diesel", "heating_oil")
WOB_COL = re.compile(r"^EUR_price_with_tax_(euro95|diesel|heating_oil)$")


@dataclass
class ExternalData:
    pump: pd.DataFrame     # date (Monday), product, value (EUR / 1000 l)
    brent_eur: pd.Series   # daily Brent in EUR/bbl


def _download(settings: Settings, name: str, url: str, ext: str, offline: bool,
              session: requests.Session | None) -> tuple[bytes, Path, bool]:
    folder = settings.raw_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    if offline:
        files = sorted(folder.glob(f"*.{ext}"), key=lambda p: p.stat().st_mtime)
        if not files:
            raise SourceError(f"[{name}] offline mode but nothing cached")
        return files[-1].read_bytes(), files[-1], True
    resp = (session or build_session()).get(url, timeout=180)
    if resp.status_code != 200:
        raise SourceError(f"[{name}] HTTP {resp.status_code} for {url}")
    content = resp.content
    path = folder / f"{hashlib.sha256(content).hexdigest()[:12]}.{ext}"
    if not path.exists():
        path.write_bytes(content)
    else:
        path.touch()  # mark as the latest vintage for offline replay
    return content, path, False


def parse_wob(content: bytes) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(content), sheet_name="Prices with taxes", header=None)
    cols = {i: WOB_COL.match(c).group(1) for i, c in enumerate(raw.iloc[0])
            if isinstance(c, str) and WOB_COL.match(c)}
    if set(cols.values()) != set(WOB_PRODUCTS):
        raise SourceError(f"[oil_bulletin] euro area columns missing: {set(WOB_PRODUCTS) - set(cols.values())}")
    body = raw.iloc[3:, [0, *cols]]
    body.columns = ["date", *cols.values()]
    body = body.assign(date=pd.to_datetime(body["date"], errors="coerce")).dropna(subset=["date"])
    long = body.melt(id_vars="date", var_name="product", value_name="value")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])
    if not (long["date"].dt.dayofweek == 0).all():
        raise SourceError("[oil_bulletin] expected Monday price dates only")
    return long.sort_values(["product", "date"]).reset_index(drop=True)


def _pull(name: str, dataset: str, path: Path, content: bytes, n: int, last: str, cached: bool) -> Pull:
    return Pull(name=name, dataset=dataset, updated=f"last observation {last}", path=path,
                sha256=hashlib.sha256(content).hexdigest(), n_values=n,
                fetched_at=datetime.now(timezone.utc).isoformat(), from_cache=cached)


def pull_external(settings: Settings, offline: bool = False) -> tuple[ExternalData, list[Pull]]:
    cfg = settings.raw["external"]
    session = None if offline else build_session()

    c, p, cached = _download(settings, "oil_bulletin", cfg["oil_bulletin_url"], "xlsx", offline, session)
    pump = parse_wob(c)
    pulls = [_pull("oil_bulletin", "EC Weekly Oil Bulletin", p, c, len(pump), f"{pump.date.max():%Y-%m-%d}", cached)]

    c, p, cached = _download(settings, "brent", cfg["brent_url"], "csv", offline, session)
    b = pd.read_csv(io.BytesIO(c))
    b.columns = ["date", "usd"]
    b = b.assign(date=pd.to_datetime(b.date), usd=pd.to_numeric(b.usd, errors="coerce")).dropna()
    pulls.append(_pull("brent", "FRED DCOILBRENTEU", p, c, len(b), f"{b.date.max():%Y-%m-%d}", cached))

    c, p, cached = _download(settings, "eurusd", cfg["eurusd_url"], "csv", offline, session)
    fx = pd.read_csv(io.BytesIO(c), usecols=["TIME_PERIOD", "OBS_VALUE"])
    fx = fx.assign(date=pd.to_datetime(fx.TIME_PERIOD), rate=pd.to_numeric(fx.OBS_VALUE, errors="coerce")).dropna()
    pulls.append(_pull("eurusd", "ECB EXR.D.USD.EUR.SP00.A", p, c, len(fx), f"{fx.date.max():%Y-%m-%d}", cached))

    # Brent in EUR: divide by USD-per-EUR; forward-fill the rate over ECB holidays only.
    rate = fx.set_index("date")["rate"].sort_index()
    usd = b.set_index("date")["usd"].sort_index()
    rate = rate.reindex(usd.index.union(rate.index)).ffill(limit=5).reindex(usd.index)
    brent_eur = (usd / rate).dropna().rename("brent_eur")
    return ExternalData(pump=pump, brent_eur=brent_eur), pulls


# --------------------------------------------------------------------------- pump-price features
def pump_index(pump: pd.DataFrame) -> pd.Series:
    """Weekly composite: equal-weight geometric mean of euro95, diesel and heating oil (EUR/1000 l).
    The fuel equation's coefficient absorbs the scale, so equal weights only fix the mix."""
    w = pump.pivot(index="date", columns="product", values="value")[list(WOB_PRODUCTS)].dropna()
    return np.exp(np.log(w).mean(axis=1)).rename("pump").sort_index()


def release_date(month: pd.Timestamp, day: int) -> pd.Timestamp:
    """Assumed HICP full-release date for reference ``month``: day ``day`` of the following month."""
    return (month + pd.offsets.MonthBegin(1)).replace(day=day)


def pump_monthly_known(pump_w: pd.Series, origin: pd.Timestamp, horizon: int, release_day: int,
                       lag_days: int) -> pd.Series:
    """Monthly-average pump index for months origin-24 .. origin+horizon, using only bulletins
    known at the origin's release date (Monday + ``lag_days`` <= release date).

    Past months average the Mondays that have a bulletin (holiday weeks are skipped, not filled).
    Mondays after the cutoff are unknown and held flat at the last known price: a no-change
    assumption for future pump prices.
    """
    cutoff = release_date(origin, release_day) - pd.Timedelta(days=lag_days)
    known = pump_w[pump_w.index <= cutoff]
    last = float(known.iloc[-1])
    months = pd.date_range(origin - pd.DateOffset(months=24), origin + pd.DateOffset(months=horizon), freq="MS")
    out = {}
    for m in months:
        mondays = pd.date_range(m, m + pd.offsets.MonthEnd(0), freq="W-MON")
        vals = [float(known[d]) for d in mondays if d in known.index]
        vals += [last] * sum(d > cutoff for d in mondays)
        out[m] = sum(vals) / len(vals) if vals else np.nan
    return pd.Series(out, name="pump_m")
