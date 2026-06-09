"""Configuration loader for VMPM.

Loads YAML configuration with sensible defaults for all trading parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BrokerConfig:
    """Broker connection settings."""
    type: str = "paper"                    # mt5, paper
    mt5_path: str = ""                     # Path to MT5 terminal
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    magic_number: int = 20260609
    slippage: int = 20


@dataclass
class RiskConfig:
    """Risk management parameters."""
    risk_per_trade: float = 0.01           # 1% per trade
    max_daily_loss: float = 0.03           # 3% daily max loss
    max_weekly_loss: float = 0.08          # 8% weekly max loss
    min_risk_reward: float = 2.0           # Minimum 1:2 RR
    preferred_risk_reward: float = 3.0     # Preferred 1:3 RR
    max_open_trades: int = 5
    max_correlated_trades: int = 2


@dataclass
class TradingConfig:
    """Trading pipeline settings."""
    pairs: list[str] = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "NZDUSD", "USDCAD",
    ])
    timeframes: dict[str, str] = field(default_factory=lambda: {
        "primary": "D1",
        "secondary": "H4",
        "entry": "H1",
        "confirmation": "M15",
    })
    asian_session_start: str = "00:00"     # Kenyan time (EAT)
    asian_session_end: str = "09:00"
    ema_fast: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    candlestick_lookback: int = 5


@dataclass
class EconometricsConfig:
    """Econometric analysis parameters — leveraging your statistics background."""
    # Time series
    arima_max_order: tuple[int, int, int] = (3, 2, 3)
    garch_order: tuple[int, int] = (1, 1)
    var_lag_max: int = 10
    cointegration_significance: float = 0.05

    # Hypothesis testing
    significance_level: float = 0.05
    confidence_level: float = 0.95

    # Regime detection
    regime_lookback: int = 60              # Days for regime classification
    volatility_regime_threshold: float = 1.5  # Std devs from mean

    # Multivariate
    pca_components: int = 5
    factor_lookback: int = 90


@dataclass
class VMPMConfig:
    """Top-level VMPM configuration."""
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    econometrics: EconometricsConfig = field(default_factory=EconometricsConfig)
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///vmpm.db"
    dashboard_port: int = 8080


def load_config(path: str | Path | None = None) -> VMPMConfig:
    """Load configuration from YAML file, falling back to defaults."""
    config = VMPMConfig()

    if path is None:
        path = Path("config/default.yaml")
    else:
        path = Path(path)

    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        # Apply overrides
        if "broker" in raw:
            for k, v in raw["broker"].items():
                if hasattr(config.broker, k):
                    setattr(config.broker, k, v)

        if "risk" in raw:
            for k, v in raw["risk"].items():
                if hasattr(config.risk, k):
                    setattr(config.risk, k, v)

        if "trading" in raw:
            for k, v in raw["trading"].items():
                if hasattr(config.trading, k):
                    setattr(config.trading, k, v)

        if "econometrics" in raw:
            for k, v in raw["econometrics"].items():
                if hasattr(config.econometrics, k):
                    setattr(config.econometrics, k, v)

        for k in ("log_level", "database_url", "dashboard_port"):
            if k in raw:
                setattr(config, k, raw[k])

    # Environment overrides
    if mt5_login := os.getenv("VMPM_MT5_LOGIN"):
        config.broker.mt5_login = int(mt5_login)
    if mt5_pass := os.getenv("VMPM_MT5_PASSWORD"):
        config.broker.mt5_password = mt5_pass
    if mt5_server := os.getenv("VMPM_MT5_SERVER"):
        config.broker.mt5_server = mt5_server

    return config
