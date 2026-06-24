"""Configuration management for Noema."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RiskConfig(BaseModel):
    risk_pct_per_trade: float = 0.25
    # Backward-compat aliases used by RiskManager and tests
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_weekly_loss: float = 0.08
    min_risk_reward: float = 2.0
    max_open_trades: int = 5
    max_concurrent_positions: int = 3
    max_per_symbol: int = 1
    daily_loss_limit_pct: float = 1.0
    max_spread_pips: float = 3.0
    atr_buffer_mult: float = 1.0
    sl_method: str = "atr"
    max_lot_size: float = 1.0  # Hard cap — NEVER exceed regardless of risk calc


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


# ── Phase 1: Architecture Settings ──────────────────────────────────

class ArchitectureSettings(BaseModel):
    """Architecture mode configuration for phased deployment."""
    mode: str = "flat"  # "flat" | "teams" | "actor_critic" | "nexus"
    teams_enabled: bool = False
    critic_team_enabled: bool = False
    parallel_critics: bool = True
    max_debate_rounds: int = 3
    communication_protocol: str = "both"  # "typed" | "legacy" | "both"


class BrokerSLASettings(BaseModel):
    """Broker disconnect SLA configuration."""
    disconnect_detect_seconds: int = 5   # Detect disconnect within 5s
    reconnect_attempt_seconds: int = 10  # Auto-reconnect attempt within 10s
    alarm_disconnect_seconds: int = 30   # Kill-switch + Telegram alert after 30s
    shutdown_seconds: int = 300          # Shutdown ALL trading after 5min
    max_reconnect_attempts: int = 5
    reconnect_base_delay: float = 1.0
    reconnect_max_delay: float = 30.0


# ═══════════════════════════════════════════════════
# COMPILE-TIME CONSTANTS — Cannot be changed without deploy
# ═══════════════════════════════════════════════════

# Max lot size HARD CAP — physical gate at broker boundary
# Intentionally defined here AND in broker/lot_protection.py
# Defense-in-depth: both barriers must agree
Noema_MAX_LOT_SIZE: float = 1.0
"""Maximum lot size per trade. COMPILE-TIME CONSTANT.

Cannot be overridden by ANY agent, ANY LLM, ANY config change
without a code deploy. This is the physical gate before any order
reaches the broker."""

# Actor agent max consecutive rejections before silenced
Noema_ACTOR_MAX_REJECTIONS: int = 50
"""Number of consecutive proposal rejections before an actor agent
is silenced until human review (Guardian kill-switch #15)."""

# Learning freeze drawdown threshold
Noema_LEARNING_FREEZE_DRAWDOWN: float = 0.10
"""Real-time drawdown threshold (10%) at which ALL learning is
frozen by Guardian kill-switch #16. Checked EVERY TRADE."""

# ═══════════════════════════════════════════════════
# Phase 1.5: Event Calendar & News Blackout Settings
# ═══════════════════════════════════════════════════

Noema_EVENT_BLACKOUT_MINUTES: int = 30
"""Total blackout window around high-impact events.
Default 30 = 15 minutes before + 15 minutes after.
Overridable via env: Noema_EVENT_BLACKOUT_MINUTES."""

Noema_EVENT_POLL_INTERVAL_SECONDS: int = 300
"""Interval between economic calendar polls.
Default 300 = check every 5 minutes.
Overridable via env: Noema_EVENT_POLL_INTERVAL_SECONDS."""

Noema_EVENT_HIGH_IMPACT_ONLY: bool = True
"""Only blackout for high-impact (red) events. Medium/low = informational only.
Set to False to also blackout on medium-impact events.
Overridable via env: Noema_EVENT_HIGH_IMPACT_ONLY."""

Noema_EVENT_MAX_BLACKOUT_MINUTES: int = 60
"""Hard timeout for any single blackout — prevents permanent freeze.
COO condition #1. After this limit, blackout is force-released and
an alert is logged. Overridable via env: Noema_EVENT_MAX_BLACKOUT_MINUTES."""

Noema_EVENT_CALENDAR_FAILURE_MODE: str = "conservative"
"""Behavior when calendar API is unavailable.
'conservative' = assume high-impact events → activate blackout
'permissive'   = assume no events → proceed normally
COO condition #2. Overridable via env: Noema_EVENT_CALENDAR_FAILURE_MODE."""

Noema_EVENT_REDUCED_SIZE_PCT: float = 0.50
"""Position size multiplier during medium-impact events or conservative mode.
Default 0.50 = trade at 50% of normal size.
Overridable via env: Noema_EVENT_REDUCED_SIZE_PCT."""

Noema_EVENT_LEAD_MINUTES: int = 15
"""Minutes before an event to activate blackout.
Overridable via env: Noema_EVENT_LEAD_MINUTES."""

Noema_EVENT_TRAIL_MINUTES: int = 15
"""Minutes after an event to deactivate blackout (if vol normalized).
Overridable via env: Noema_EVENT_TRAIL_MINUTES."""

# Max disconnect seconds (BrokerHealthMonitor)
max_disconnect_seconds: int = 30
"""Maximum seconds of broker disconnection before kill-switch
data_stale is triggered by the HealthChecker→Guardian bridge."""

# ═══════════════════════════════════════════════════
# Telegram Integration Settings
# ═══════════════════════════════════════════════════

Noema_TELEGRAM_RATE_LIMIT: int = 10
"""Maximum Telegram messages per minute per chat.
Default 10/min. Overridable via env: Noema_TELEGRAM_RATE_LIMIT."""

Noema_TELEGRAM_DAILY_SUMMARY_TIME: str = "21:00"
"""UTC time to send daily summary (HH:MM format).
Default 21:00 UTC. Overridable via env: Noema_TELEGRAM_DAILY_SUMMARY_TIME."""


# ═══════════════════════════════════════════════════

class EventConfig(BaseModel):
    """Event calendar and news blackout configuration (Phase 1.5)."""
    blackout_minutes: int = 30         # Total window: 15 before + 15 after
    lead_minutes: int = 15             # Minutes before event to activate
    trail_minutes: int = 15            # Minutes after event to deactivate (if normalized)
    poll_interval_seconds: int = 300   # Check calendar every 5 min
    high_impact_only: bool = True      # Only blackout for red events
    max_blackout_minutes: int = 60     # Hard watchdog timeout
    calendar_failure_mode: str = "conservative"  # "conservative" | "permissive"
    reduced_size_pct: float = 0.50     # Position size during medium impact / conservative mode


# ── Phase 5: Institutional Features ──────────────────────────────

class MultiBrokerConfig(BaseModel):
    """Multi-broker gateway configuration."""
    enabled: bool = True
    primary_broker: str = ""              # Auto-detected from first registered broker
    routing_policy: str = "best_liquidity"  # "best_price" | "best_liquidity" | "round_robin" | "failover"
    health_check_interval: float = 5.0     # seconds between broker health checks
    failover_enabled: bool = True


class FIXConfig(BaseModel):
    """FIX protocol configuration (stub)."""
    enabled: bool = False                  # Disabled by default — FIX is a stub
    sender_comp_id: str = "NOEMA"
    target_comp_id: str = "BROKER"
    host: str = "localhost"
    port: int = 9880
    heartbeat_interval: int = 30           # seconds
    username: str = ""
    password: str = ""
    account: str = ""


class ReconciliationConfig(BaseModel):
    """Position reconciliation configuration."""
    enabled: bool = True
    run_on_startup: bool = True
    run_every_n_cycles: int = 5            # Run reconciliation every N decision cycles
    auto_correct_enabled: bool = False     # Auto-correct minor drifts
    price_tolerance_pips: float = 5.0      # Pips tolerance before flagging price drift
    volume_tolerance_pct: float = 0.05     # 5% volume drift tolerance
    sl_tp_tolerance_pips: float = 10.0     # Pips tolerance for SL/TP drift
    auto_correct_max_volume_pct: float = 0.10  # Max 10% auto-correct
    critical_drift_threshold_pct: float = 0.10  # >10% = CRITICAL


class RiskReportingConfig(BaseModel):
    """Risk reporting configuration."""
    enabled: bool = True
    output_dir: str = "reports/"
    risk_free_rate: float = 0.02           # Annualized risk-free rate for Sharpe
    var_window_days: int = 90
    daily_report_config: bool = True
    weekly_report_config: bool = True
    monthly_report_config: bool = True
    export_format: str = "json"            # "json" | "html" | "both"


class ComplianceConfig(BaseModel):
    """Regulatory compliance configuration."""
    enabled: bool = True
    audit_trail_enabled: bool = True
    audit_trail_path: str = "data/audit_trail.jsonl"
    audit_retention_days: int = 2555       # 7 years (MiCA/SEC requirement)
    position_limit_enforcement: bool = True
    max_position_lot: float = 1.0
    max_exposure_pct: float = 300.0
    max_single_pair_pct: float = 50.0
    pre_trade_compliance_check: bool = True
    jurisdiction: str = "internal"          # "EU" | "US" | "UK" | "AU" | "internal"
    active_regulations: list[str] = ["internal"]  # "internal", "mica", "sec", etc.


class ModeSettingsConfig(BaseModel):
    """Demo/Live mode configuration."""
    default_mode: str = "demo"              # "demo" | "live"
    demo_validation_days: int = 14          # Profitable days before live suggestion
    live_requires_confirmation: bool = True


class MicroModeConfig(BaseModel):
    """Micro account auto-scaling ($10-$500)."""
    risk_pct_per_trade: float = 0.02        # 2% of capital
    daily_drawdown_pct: float = 0.15        # 15% of capital
    min_lot_size: float = 0.01              # Micro lot
    max_lot_size_under_100: float = 0.01    # Cap for accounts < $100
    pip_value_per_lot: float = 10.0         # USD per pip per standard lot (forex)


class Settings(BaseModel):
    risk: RiskConfig = Field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    confluence: ConfluenceConfig = Field(default_factory=ConfluenceConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    nim: NIMConfig = Field(default_factory=NIMConfig)
    architecture: ArchitectureSettings = Field(default_factory=ArchitectureSettings)
    broker_sla: BrokerSLASettings = Field(default_factory=BrokerSLASettings)
    event: EventConfig = Field(default_factory=EventConfig)
    multi_broker: MultiBrokerConfig = Field(default_factory=MultiBrokerConfig)
    fix: FIXConfig = Field(default_factory=FIXConfig)
    reconciliation: ReconciliationConfig = Field(default_factory=ReconciliationConfig)
    risk_reporting: RiskReportingConfig = Field(default_factory=RiskReportingConfig)
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)
    mode_settings: ModeSettingsConfig = Field(default_factory=ModeSettingsConfig)
    micro_mode: MicroModeConfig = Field(default_factory=MicroModeConfig)
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///noema.db"
    redis_url: str = ""
    noema_secret_key: str = ""  # Used for JWT signing, session tokens, dashboard auth
    symbols_whitelist: list[str] = Field(
        default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]
    )


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        # Resolve relative to the noema package root
        path = Path(__file__).parent.parent / "config" / "settings.yaml"

    if not path.exists():
        return Settings()

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    settings = Settings(
        broker=BrokerConfig(**data.get("broker", {})),
        risk=RiskConfig(**data.get("risk", {})),
        portfolio=PortfolioConfig(**data.get("portfolio", {})),
        confluence=ConfluenceConfig(**data.get("confluence", {})),
        trading=TradingConfig(**data.get("trading", {})),
        nim=NIMConfig(**data.get("nim", {})),
        architecture=ArchitectureSettings(**data.get("architecture", {})),
        broker_sla=BrokerSLASettings(**data.get("broker_sla", {})),
        event=EventConfig(**data.get("event", {})),
        multi_broker=MultiBrokerConfig(**data.get("multi_broker", {})),
        fix=FIXConfig(**data.get("fix", {})),
        reconciliation=ReconciliationConfig(**data.get("reconciliation", {})),
        risk_reporting=RiskReportingConfig(**data.get("risk_reporting", {})),
        compliance=ComplianceConfig(**data.get("compliance", {})),
        mode_settings=ModeSettingsConfig(**data.get("mode", {})),
        micro_mode=MicroModeConfig(**data.get("micro_mode", {})),
        log_level=data.get("log_level", "INFO"),
        database_url=data.get("database_url", "sqlite+aiosqlite:///noema.db"),
        redis_url=data.get("redis_url", ""),
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

    if secret := os.getenv("NOEMA_SECRET_KEY"):
        settings.noema_secret_key = secret

    # ── Phase 1.5: Event calendar env overrides ──
    if blk := os.getenv("Noema_EVENT_BLACKOUT_MINUTES"):
        settings.event.blackout_minutes = int(blk)
    if poll := os.getenv("Noema_EVENT_POLL_INTERVAL_SECONDS"):
        settings.event.poll_interval_seconds = int(poll)
    if high := os.getenv("Noema_EVENT_HIGH_IMPACT_ONLY"):
        settings.event.high_impact_only = high.lower() in ("true", "1", "yes")
    if max_blk := os.getenv("Noema_EVENT_MAX_BLACKOUT_MINUTES"):
        settings.event.max_blackout_minutes = int(max_blk)
    if fail_mode := os.getenv("Noema_EVENT_CALENDAR_FAILURE_MODE"):
        settings.event.calendar_failure_mode = fail_mode
    if lead := os.getenv("Noema_EVENT_LEAD_MINUTES"):
        settings.event.lead_minutes = int(lead)
    if trail := os.getenv("Noema_EVENT_TRAIL_MINUTES"):
        settings.event.trail_minutes = int(trail)
