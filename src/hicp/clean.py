"""Raw Eurostat long frames -> typed, tidy tables, saved to ``data/clean/*.parquet``.

Cleaning is deliberately thin: rename, type, drop empty cells, sort. Nothing is imputed or
dropped for being unusual (outliers are flagged by validation gate V8, not removed here).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from hicp.config import Settings


@dataclass
class CleanData:
    index: pd.DataFrame            # date, geo, coicop, unit, value, status
    item_weights: pd.DataFrame     # year, geo, coicop, weight (per mille)
    country_weights: pd.DataFrame  # year, geo, weight (per mille of the euro area*)
    contributions: pd.DataFrame    # date, coicop, value (pp)
    first_release: pd.DataFrame    # date, release, value (YoY %)
    ppi: pd.DataFrame              # date, value (index 2021=100), status: producer prices D35, EA21
    first_release_legacy: pd.DataFrame  # date, release, value: ver.1 first releases as published (to 2025-12)

    TABLES = ("index", "item_weights", "country_weights", "contributions", "first_release", "ppi",
              "first_release_legacy")

    # --- convenience views -------------------------------------------------------------
    def index_wide(self, geo: str, unit: str = "I25") -> pd.DataFrame:
        d = self.index[(self.index.geo == geo) & (self.index.unit == unit)]
        return d.pivot(index="date", columns="coicop", values="value").sort_index()

    def weights_wide(self, geo: str) -> pd.DataFrame:
        d = self.item_weights[self.item_weights.geo == geo]
        return d.pivot(index="year", columns="coicop", values="weight").sort_index()

    def country_index(self, coicop: str = "TOTAL") -> pd.DataFrame:
        d = self.index[(self.index.coicop == coicop) & (self.index.unit == "I25")]
        return d.pivot(index="date", columns="geo", values="value").sort_index()

    def country_weights_wide(self) -> pd.DataFrame:
        return self.country_weights.pivot(index="year", columns="geo", values="weight").sort_index()

    def save(self, settings: Settings) -> None:
        settings.clean_dir.mkdir(parents=True, exist_ok=True)
        for name in self.TABLES:
            getattr(self, name).to_parquet(settings.clean_dir / f"{name}.parquet", index=False)

    @classmethod
    def load(cls, settings: Settings) -> "CleanData":
        return cls(**{n: pd.read_parquet(settings.clean_dir / f"{n}.parquet") for n in cls.TABLES})


def _month(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str) + "-01", format="%Y-%m-%d")


def clean_all(raw: dict[str, pd.DataFrame], settings: Settings) -> CleanData:
    dim = settings.raw["eurostat"]["coicop_dimension"]

    idx = pd.concat([raw["index_ea"], raw["index_countries"]], ignore_index=True)
    index = pd.DataFrame({
        "date": _month(idx["time"]),
        "geo": idx["geo"].astype(str),
        "coicop": idx[dim].astype(str),
        "unit": idx["unit"].astype(str),
        "value": idx["value"].astype("float64"),
        "status": idx["status"].astype("string"),
    }).dropna(subset=["value"])
    index = index.sort_values(["geo", "coicop", "unit", "date"]).reset_index(drop=True)

    w = raw["item_weights"]
    item_weights = pd.DataFrame({
        "year": w["time"].astype(int),
        "geo": w["geo"].astype(str),
        "coicop": w[dim].astype(str),
        "weight": w["value"].astype("float64"),
    }).dropna(subset=["weight"]).sort_values(["geo", "coicop", "year"]).reset_index(drop=True)

    cw = raw["country_weights"]
    cw = cw[cw["statinfo"] == settings.raw["country_weights_statinfo"]]
    country_weights = pd.DataFrame({
        "year": cw["time"].astype(int),
        "geo": cw["geo"].astype(str),
        "weight": cw["value"].astype("float64"),
    }).dropna(subset=["weight"])
    # The aggregate's own row (EA = 1000) is not a country.
    country_weights = country_weights[country_weights.geo.isin(settings.countries)]
    country_weights = country_weights.sort_values(["year", "geo"]).reset_index(drop=True)

    c = raw["contributions"]
    contributions = pd.DataFrame({
        "date": _month(c["time"]),
        "coicop": c[dim].astype(str),
        "value": c["value"].astype("float64"),
    }).dropna(subset=["value"]).sort_values(["coicop", "date"]).reset_index(drop=True)

    f = raw["first_release"]
    first_release = pd.DataFrame({
        "date": _month(f["time"]),
        "release": f["release"].astype(str),
        "value": f["value"].astype("float64"),
    }).dropna(subset=["value"]).sort_values(["release", "date"]).reset_index(drop=True)

    q = raw["ppi_energy"]
    ppi = pd.DataFrame({
        "date": _month(q["time"]),
        "value": q["value"].astype("float64"),
        "status": q["status"].astype("string"),
    }).dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

    g = raw["first_release_legacy"]
    first_release_legacy = pd.DataFrame({
        "date": _month(g["time"]),
        "release": g["release"].astype(str),
        "value": g["value"].astype("float64"),
    }).dropna(subset=["value"]).sort_values(["release", "date"]).reset_index(drop=True)

    return CleanData(index=index, item_weights=item_weights, country_weights=country_weights,
                     contributions=contributions, first_release=first_release, ppi=ppi,
                     first_release_legacy=first_release_legacy)
