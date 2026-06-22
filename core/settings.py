"""Configuration management for Noema."""

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




class BrokerConfig(BaseModel):
    """Broker connection settings."""
    type: str = "paper"
    mt5_path: str = ""
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    magic_number: int = 20260609
    slippage: int = 20


class TradingConfig(BaseModel):
    """Trading pipeline settings."""
    pairs: list[str] = Field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD",
    ])
    timeframes: dict[str, str] = Field(default_factory=lambda: {
        "primary": "D1", "secondary": "H4", "entry": "H1", "confirmation": "M15",
    })
    ema_fast: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0

class NIMConfig(BaseModel):
    """NVIDIA NIM API settings."""
    api_key: str = ""
    base_url: str = "https://integrate.api.nvidia.com/v1"
    default_tier: str = "standard"  # fast, standard, heavy
    cache_ttl: int = 60
    cache_enabled: bool = True
    max_retries: int = 3
    rpm_limit: int = 40


class Settings(BaseModel):
    risk: RiskConfig = Field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    confluence: ConfluenceConfig = Field(default_factory=ConfluenceConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    nim: NIMConfig = Field(default_factory=NIMConfig)
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///noema.db"
    redis_url: str = ""
    symbols_whitelist: list[str] = Field(
        default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]
    )


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        path = Path("config/settings.yaml")

    if not path.exists():
        return Settings()

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    settings = Settings(
        risk=RiskConfig(**data.get("risk", {})),
        portfolio=PortfolioConfig(**data.get("portfolio", {})),
        confluence=ConfluenceConfig(**data.get("confluence", {})),
        symbols_whitelist=data.get("symbols", {}).get("whitelist", []),
    )
    # Environment overrides
    import os
    if mt5_login := os.getenv("Noema_MT5_LOGIN"):
        settings.broker.mt5_login = int(mt5_login)
    if mt5_pass := os.getenv("Noema_MT5_PASSWORD"):
        settings.broker.mt5_password = mt5_pass
    if mt5_server := os.getenv("Noema_MT5_SERVER"):
        settings.broker.mt5_server = mt5_server
    if nim_key := os.getenv("NIM_API_KEY"):
        settings.nim.api_key = nim_key
    if db_url := os.getenv("DATABASE_URL"):
        settings.database_url = db_url
    if redis_url := os.getenv("REDIS_URL"):
        settings.redis_url = redis_url

    return settings
