"""Load ``config/settings.yaml`` and expose project paths."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any]
    path: Path

    @property
    def components(self) -> list[str]:
        return list(self.raw["components"])

    @property
    def countries(self) -> list[str]:
        return list(self.raw["countries"])

    @property
    def headline(self) -> str:
        return self.raw["headline"]

    @property
    def ea(self) -> str:
        return self.raw["euro_area_geo"]

    @property
    def val(self) -> dict[str, Any]:
        return self.raw["validation"]

    @property
    def raw_dir(self) -> Path:
        return ROOT / "data" / "raw"

    @property
    def clean_dir(self) -> Path:
        return ROOT / "data" / "clean"

    @property
    def outputs_dir(self) -> Path:
        return ROOT / "outputs"

    def config_hash(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()[:16]


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config" / "settings.yaml"
    with path.open() as fh:
        return Settings(raw=yaml.safe_load(fh), path=path)
