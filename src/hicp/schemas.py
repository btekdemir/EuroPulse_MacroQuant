"""Pydantic schemas for every JSON the pipeline writes.

Rule: nothing reaches ``outputs/`` without passing through one of these models
(``write_json`` below). The dashboard and the Power BI pack read only these validated files.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- validation
class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class GateResult(Strict):
    gate: str = Field(pattern=r"^V\d+$")
    name: str
    status: Status
    critical: bool = Field(description="A failed critical gate stops the forecast step")
    message: str
    metrics: dict[str, float | int | str | None] = Field(default_factory=dict)
    details: list[dict[str, Any]] = Field(default_factory=list, description="Flagged rows, capped")

    @field_validator("metrics")
    @classmethod
    def finite(cls, v: dict) -> dict:
        for k, x in v.items():
            if isinstance(x, float) and not math.isfinite(x):
                raise ValueError(f"metric {k} is not finite: {x}")
        return v


class ValidationReport(Strict):
    run_at: datetime
    last_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    gates: list[GateResult]

    @property
    def blocking(self) -> list[GateResult]:
        return [g for g in self.gates if g.critical and g.status is Status.FAIL]

    @property
    def summary(self) -> dict[str, int]:
        return {s.value: sum(g.status is s for g in self.gates) for s in Status}


# --------------------------------------------------------------------------- provenance
class DataVintage(Strict):
    name: str
    dataset: str
    updated: str = Field(description="Eurostat's own 'updated' timestamp for the dataset")
    sha256: str
    n_values: int = Field(gt=0)
    fetched_at: str
    from_cache: bool
    raw_file: str


class RunManifest(Strict):
    run_at: datetime
    code_version: str = Field(description="git commit (with -dirty if the tree has changes)")
    config_hash: str
    python: str
    offline: bool
    vintages: list[DataVintage]
    last_period: str
    runtime_seconds: float | None = None


# --------------------------------------------------------------------------- forecast
class ForecastPoint(Strict):
    date: str = Field(pattern=r"^\d{4}-\d{2}$")
    horizon: int = Field(ge=1, le=3)
    point: float = Field(description="Headline HICP YoY, %")
    quantiles: dict[str, float] = Field(description="q05..q95: point + empirical OOS error quantiles")
    base_effect_pp: float = Field(description="Change in YoY since the origin due to m/m a year earlier (known)")
    momentum_pp: float = Field(description="Change in YoY since the origin due to new m/m (forecast)")
    contributions: dict[str, float] = Field(description="Exact contributions to headline YoY, pp")
    component_yoy: dict[str, float]
    component_mom: dict[str, float] = Field(description="Forecast 100·Δln, %")

    @field_validator("quantiles")
    @classmethod
    def ordered(cls, v: dict[str, float]) -> dict[str, float]:
        vals = [v[k] for k in sorted(v)]
        if vals != sorted(vals):
            raise ValueError("quantiles must be non-decreasing")
        return v


class HistoryPoint(Strict):
    date: str = Field(pattern=r"^\d{4}-\d{2}$")
    yoy: float
    contributions: dict[str, float]


class Forecast(Strict):
    origin: str = Field(pattern=r"^\d{4}-\d{2}$")
    last_actual_yoy: float
    ecb_target: float
    points: list[ForecastPoint] = Field(min_length=3, max_length=3)
    history: list[HistoryPoint]
    selected_models: dict[str, str]
    effective_weights: dict[str, float]
    official_weights: dict[str, float]
    pump_mom_assumed: dict[str, float]
    assumptions: list[str]


# --------------------------------------------------------------------------- backtest
class MetricRow(Strict):
    model: str
    h: int = Field(ge=1, le=3)
    sample: str
    n: int = Field(gt=0)
    rmse: float = Field(ge=0)
    mae: float = Field(ge=0)
    rmse_rw: float = Field(ge=0)
    rmse_ratio_vs_rw: float = Field(ge=0)
    dm_stat: float | None
    dm_p: float | None = Field(default=None, ge=0, le=1)
    dm_p_vs_direct_AR: float | None = Field(default=None, ge=0, le=1)
    bias: float = Field(description="mean(forecast − actual), pp")
    direction_accuracy: float = Field(ge=0, le=1)


class SelectionStep(Strict):
    coicop: str
    candidate: str
    vs: str
    mse_candidate: float | None = None
    mse_current: float | None = None
    dm_stat: float | None = None
    dm_p: float | None = None
    accepted: bool
    n: int | None = None


class TrackPoint(Strict):
    model: str
    origin: str
    h: int = Field(ge=1, le=3)
    target: str
    fc: float
    actual: float | None


class BacktestMetrics(Strict):
    rule: str = Field(description="The pre-committed model-selection rule (docs/DECISIONS.md D9)")
    first_origin: str
    last_origin: str
    selection_sample: tuple[str, str]
    selected_models: dict[str, str]
    selection_log: list[SelectionStep]
    metrics: list[MetricRow]
    track: list[TrackPoint] = Field(description="Out-of-sample headline YoY forecasts vs actual")


class CountryView(Strict):
    """Country contributions to euro area* headline YoY (exact, chain-linked with country weights)."""
    dates: list[str]
    contributions: dict[str, list[float | None]]
    yoy: dict[str, list[float | None]]
    ea_yoy: list[float]
    weights_latest: dict[str, float] = Field(description="Country weight in the euro area*, per mille")
    weights_year: int
    max_abs_gap_pp: float = Field(description="max |Σ country contributions − EA YoY| over the window")


# --------------------------------------------------------------------------- shocks
from typing import Literal  # noqa: E402

from pydantic import model_validator  # noqa: E402

COMPONENTS = ("FUEL", "ELC_GAS", "FOOD_P", "FOOD_NP", "IGD_NNRG", "SERV")
COUNTRIES = ("AT", "BE", "BG", "CY", "DE", "EE", "EL", "ES", "FI", "FR", "HR", "IE", "IT", "LT", "LU",
             "LV", "MT", "NL", "PT", "SI", "SK")


class Profile(Strict):
    """How the price-level shock evolves after the start month (fraction of the full size)."""
    kind: Literal["permanent", "decaying", "temporary", "ramp", "custom"]
    half_life_months: float | None = Field(default=None, gt=0, description="decaying only")
    months: int | None = Field(default=None, ge=1, le=24, description="temporary: duration; ramp: months to full size")
    fractions: list[float] | None = Field(default=None, description="custom: fraction per month, last value held")

    @model_validator(mode="after")
    def params(self) -> "Profile":
        need = {"decaying": "half_life_months", "temporary": "months", "ramp": "months", "custom": "fractions"}
        if self.kind in need and getattr(self, need[self.kind]) is None:
            raise ValueError(f"profile {self.kind} needs {need[self.kind]}")
        return self


class Scenario(Strict):
    name: str = Field(min_length=3)
    components: list[Literal[COMPONENTS]] = Field(min_length=1)  # type: ignore[valid-type]
    countries: list[Literal[COUNTRIES]] = Field(default_factory=list,  # type: ignore[valid-type]
                                                description="empty = euro area-wide")
    size_pct: float = Field(gt=-50, lt=200, description="shock to the consumer price LEVEL, %")
    profile: Profile
    start: str = Field(pattern=r"^\d{4}-\d{2}$")
    second_round: bool = False
    second_round_regime: Literal["post2020", "pre2020"] = "post2020"
    rationale: str = Field(min_length=40, description="Mandatory: why this size, profile and mapping")
    sources: list[str] = Field(min_length=1)
    mapping: str | None = Field(default=None, description="How an external shock maps to the HICP component")

    @field_validator("components", "countries")
    @classmethod
    def unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicates")
        return v


class ShockResult(Strict):
    scenario: Scenario
    months: list[str]
    delta_yoy_pp: list[float]
    delta_first_round_pp: list[float]
    delta_second_round_pp: list[float]
    delta_total_low_pp: list[float] = Field(description="Total with the second-round 95% lower bound")
    delta_total_high_pp: list[float]
    baseline_yoy: list[float | None]
    shocked_yoy: list[float | None]
    peak_pp: float
    peak_month: str


class ShockBasis(Strict):
    """Everything the in-browser simulator needs. The JS engine mirrors hicp.shocks.simulate."""
    origin: str
    months: list[str]
    components: list[str]
    countries: list[str]
    weight_matrix: dict[str, dict[str, float]] = Field(description="country -> component -> share of EA headline")
    ea_effective_weights: dict[str, float]
    baseline_yoy: list[float | None]
    growth_factor: list[float] = Field(description="1 + baseline YoY/100 used to scale the YoY impact")
    core_share: float
    energy_components: list[str]
    second_round: dict[str, dict[str, Any]]
    fuel_brent_elasticity: dict[str, Any]
    aggregation_check_max_abs: float = Field(description="max |Σ_c W_c,i − EA w_eff_i|")
    presets: list[Scenario]
    assumptions: list[str]


# --------------------------------------------------------------------------- writing
def _default(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    raise TypeError(type(o))


def write_json(model: BaseModel, path: Path) -> Path:
    """Validate (round-trip through the schema) and write. Raises if the model is invalid."""
    data = model.model_dump(mode="json")
    type(model).model_validate(data)  # round trip: what we write is what the schema accepts
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=_default, allow_nan=False) + "\n")
    return path


def export_json_schemas(folder: Path) -> None:
    """Write the JSON Schema of each output model, so consumers can validate independently."""
    folder.mkdir(parents=True, exist_ok=True)
    for model in (ValidationReport, RunManifest, Forecast, BacktestMetrics, Scenario, ShockResult, ShockBasis,
                  CountryView):
        (folder / f"{model.__name__}.schema.json").write_text(
            json.dumps(model.model_json_schema(), indent=2) + "\n")
