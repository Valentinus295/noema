"""Core framework for the Noema multi-agent system."""
from noema.core.agent import Agent, AgentState
from noema.core.platform import detect_platform, get_broker_class, PlatformInfo, check_prerequisites
from noema.core.message_bus import MessageBus, Message
from noema.core.state_machine import TradingPipeline, PipelineState
from noema.core.settings import Settings, load_settings
from noema.core.timeframe_manager import (
    TimeframeManager,
    MultiTimeframeResult,
    TimeframeAnalysis,
    TrendDirection,
    VolatilityRegime,
    TimeframeAlignment,
)
from noema.core.symbol_orchestrator import (
    SymbolOrchestrator,
    SymbolState,
    SymbolPnL,
    SymbolHealth,
)

# Phase 6: Production Hardening
try:
    from noema.core.shutdown import (
        ShutdownManager,
        ShutdownConfig,
        ShutdownPositionPolicy,
        load_shutdown_config_from_env,
    )
except ImportError:
    ShutdownManager = None  # type: ignore[assignment]
    ShutdownConfig = None  # type: ignore[assignment]
    ShutdownPositionPolicy = None  # type: ignore[assignment]
    load_shutdown_config_from_env = None  # type: ignore[assignment]

try:
    from noema.core.config_validator import validate_config, ValidationResult, format_validation_errors
except ImportError:
    validate_config = None  # type: ignore[assignment]
    ValidationResult = None  # type: ignore[assignment]
    format_validation_errors = None  # type: ignore[assignment]

try:
    from noema.core.logging_config import configure_logging, set_request_id, audit_secret_logging
except ImportError:
    configure_logging = None  # type: ignore[assignment]
    set_request_id = None  # type: ignore[assignment]
    audit_secret_logging = None  # type: ignore[assignment]

try:
    from noema.core.backup import BackupManager
except ImportError:
    BackupManager = None  # type: ignore[assignment]

# Backward-compatible alias
NoemaConfig = Settings

__all__ = [
    "Agent", "AgentState",
    "MessageBus", "Message",
    "TradingPipeline", "PipelineState",
    "Settings", "load_settings",
    "NoemaConfig",
    "TimeframeManager",
    "MultiTimeframeResult",
    "TimeframeAnalysis",
    "TrendDirection",
    "VolatilityRegime",
    "TimeframeAlignment",
    "SymbolOrchestrator",
    "SymbolState",
    "SymbolPnL",
    "SymbolHealth",
    # Phase 6: Production Hardening
    "ShutdownManager",
    "ShutdownConfig",
    "ShutdownPositionPolicy",
    "load_shutdown_config_from_env",
    "validate_config",
    "ValidationResult",
    "format_validation_errors",
    "configure_logging",
    "set_request_id",
    "audit_secret_logging",
    "BackupManager",
]
