"""Configuration loading and path management."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path = ROOT

    # ---- convenience accessors -------------------------------------------
    @property
    def rsi_period(self) -> int:
        return int(self.raw["rsi"]["period"])

    @property
    def thresholds(self) -> dict[str, float]:
        return self.raw["thresholds"]

    @property
    def timezone(self) -> str:
        return self.raw.get("timezone", "Asia/Kolkata")

    def path(self, key: str) -> Path:
        p = self.root / self.raw["paths"][key]
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node


def load_config(path: str | os.PathLike | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    cfg = Config(raw=raw)
    # Ensure all data directories exist up front.
    for key in raw.get("paths", {}):
        cfg.path(key)
    return cfg
