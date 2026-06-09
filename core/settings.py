"""Configuration management for VMPM."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RiskConfig(BaseModel):
    risk_pct_per_trade: float = 0.25
    max_concurrent_positions: int = 3
    max_per_symbol: int = 1
    daily_loss_limit_pct: float = 1.0
    max_spread_pips: float = 3.0
    atr_buffer_mult: float = 1.0
    sl_method: str = "atr"


class PortfolioConfig(BaseModel):
    correlation_cap_sum_abs: float = 1.5
    pca_factor_exposure_cap: float = 0.6
    cluster_max_concurrent: int = 1
    currency_strength_topN: int = 2


class ConfluenceConfig(BaseModel):
    threshold: float = 0.70
    llm_review_band: tuple[float, float] = (0.55, 0.70)
    llm_review_enabled: bool = False
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "trend": 0.25,
            "structure": 0.25,
            "retest": 0.15,
            "rsi": 0.15,
            "candle": 0.10,
            "fundamental": 0.10,
        }
    )


class Settings(BaseModel):
    risk: RiskConfig = Field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    confluence: ConfluenceConfig = Field(default_factory=ConfluenceConfig)
    symbols_whitelist: list[str] = Field(
        default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]
    )


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        path = Path("/home/valentinetech/vmpm/config/settings.yaml")

    with open(path) as f:
        data = yaml.safe_load(f)

    return Settings(
        risk=RiskConfig(**data.get("risk", {})),
        portfolio=PortfolioConfig(**data.get("portfolio", {})),
        confluence=ConfluenceConfig(**data.get("confluence", {})),
        symbols_whitelist=data.get("symbols", {}).get("whitelist", []),
    )
