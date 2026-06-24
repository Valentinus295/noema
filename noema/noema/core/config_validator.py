"""
Noema Configuration Validator — Startup validation of all environment/config values.

Validates ALL configuration on application startup, providing clear, actionable
error messages for any misconfiguration. Catches issues before they cause runtime
failures in production.

Design principles:
- Fail fast: Validate everything at startup, not lazily at runtime
- Clear errors: Every validation failure tells you exactly what's wrong and how to fix it
- Type-safe: Pydantic models provide automatic type coercion and validation
- Defense-in-depth: Critical values are range-checked, not just type-checked

Usage:
    from noema.core.config_validator import validate_config

    # Called at startup in main.py
    result = validate_config(settings, env_file=".env")
    if not result.is_valid:
        for error in result.errors:
            logger.critical(error)
        sys.exit(1)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# Validation Result
# ═══════════════════════════════════════════════════

class Severity(str, Enum):
    """Validation error severity."""
    FATAL = "fatal"       # Will prevent startup
    ERROR = "error"       # Should be fixed, but startup continues with warnings
    WARNING = "warning"   # Advisory — won't break anything


@dataclass
class ValidationError:
    """A single configuration validation failure."""
    field: str            # Config path (e.g., "settings.broker.mt5_login")
    message: str          # Human-readable error
    severity: Severity = Severity.ERROR
    current_value: Any = None


@dataclass
class ValidationResult:
    """Aggregate result of configuration validation."""
    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def fatal_errors(self) -> list[ValidationError]:
        return [e for e in self.errors if e.severity == Severity.FATAL]

    @property
    def all_issues(self) -> list[ValidationError]:
        return self.errors + self.warnings


# ═══════════════════════════════════════════════════
# Required Environment Variables
# ═══════════════════════════════════════════════════

# Fields that MUST be set (fatal if missing in production)
REQUIRED_ENV_VARS: dict[str, str] = {
    "NIM_API_KEY": "NVIDIA NIM API key for LLM agents. Get from https://build.nvidia.com/",
    "Noema_MT5_LOGIN": "MetaTrader 5 login (account number)",
    "Noema_MT5_PASSWORD": "MetaTrader 5 account password",
    "Noema_MT5_SERVER": "MetaTrader 5 server name (e.g., FxPesa-Demo, FBS-Real)",
}

# Fields that are required but have a default fallback (warning if missing)
RECOMMENDED_ENV_VARS: dict[str, str] = {
    "DATABASE_URL": "PostgreSQL connection URL. Falls back to SQLite if missing.",
    "REDIS_URL": "Redis connection URL. Caching and pub/sub disabled if missing.",
    "TELEGRAM_BOT_TOKEN": "Telegram bot token for alerting. Alerts disabled if missing.",
    "NOEMA_SECRET_KEY": "Secret key for dashboard auth + API shutdown endpoint.",
}

# Fields that must be non-empty in settings (even if loaded from YAML)
REQUIRED_SETTINGS_FIELDS: dict[str, str] = {
    "settings.trading.pairs": "At least one trading pair required",
    "settings.trading.timeframes.primary": "Primary timeframe required",
}


# ═══════════════════════════════════════════════════
# Range Checks
# ═══════════════════════════════════════════════════

# Format: (field_path, min, max, unit_description)
RANGE_CHECKS: list[tuple[str, float, float, str]] = [
    ("settings.risk.risk_pct_per_trade", 0.01, 5.0, "Percent of account per trade (0.01–5.0%)"),
    ("settings.risk.max_daily_loss", 0.005, 0.10, "Max daily loss as fraction (0.005–0.10)"),
    ("settings.risk.max_weekly_loss", 0.01, 0.20, "Max weekly loss as fraction (0.01–0.20)"),
    ("settings.risk.min_risk_reward", 1.0, 10.0, "Minimum risk-reward ratio (1.0–10.0)"),
    ("settings.risk.max_open_trades", 1, 20, "Max concurrent open trades (1–20)"),
    ("settings.risk.max_lot_size", 0.01, 10.0, "Max lot size per trade (0.01–10.0)"),
    ("settings.confluence.threshold", 0.3, 1.0, "Confluence threshold (0.3–1.0)"),
    ("settings.event.blackout_minutes", 5, 120, "News blackout window in minutes (5–120)"),
    ("settings.event.lead_minutes", 1, 60, "Pre-event blackout lead minutes (1–60)"),
    ("settings.event.trail_minutes", 1, 60, "Post-event blackout trail minutes (1–60)"),
    ("settings.broker_sla.disconnect_detect_seconds", 1, 30, "Disconnect detection timeout seconds"),
    ("settings.broker_sla.alarm_disconnect_seconds", 10, 120, "Alarm disconnect timeout seconds"),
    ("settings.architecture.max_debate_rounds", 1, 10, "Max debate rounds (1–10)"),
]

# Format: (field_path, list_allowed_values)
ENUM_CHECKS: list[tuple[str, list[str], str]] = [
    ("settings.broker_sla.calendar_failure_mode", ["conservative", "permissive"], "Event calendar failure mode"),
    ("settings.architecture.mode", ["flat", "teams", "actor_critic", "nexus"], "Architecture mode"),
    ("settings.architecture.communication_protocol", ["typed", "legacy", "both"], "Agent communication protocol"),
    ("settings.risk.sl_method", ["atr", "structure", "fixed", "volatility"], "Stop-loss method"),
    ("settings.log_level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], "Log level"),
]


# ═══════════════════════════════════════════════════
# Pattern Checks (regex-based)
# ═══════════════════════════════════════════════════

# Format: (field_path, pattern_compiled, human_description)
PATTERN_CHECKS: list[tuple[str, re.Pattern, str]] = [
    ("settings.database_url", re.compile(r"^(postgresql(\+asyncpg)?|sqlite(\+aiosqlite)?)://"), "Valid DB URL"),
    ("settings.broker.type", re.compile(r"^(paper|mt5|mt5_linux|fbs)$"), "Broker type (paper, mt5, mt5_linux, fbs)"),
]


# ═══════════════════════════════════════════════════
# Special Validators (custom logic)
# ═══════════════════════════════════════════════════

def _validate_api_key(settings: Any, result: ValidationResult) -> None:
    """Validate NIM API key format."""
    api_key = getattr(settings.nim, "api_key", "") or os.getenv("NIM_API_KEY", "")
    if not api_key:
        result.errors.append(ValidationError(
            field="NIM_API_KEY",
            message="NIM_API_KEY is not set. LLM agents will not function. Set in .env or export NIM_API_KEY=<your-key>",
            severity=Severity.WARNING,
        ))
    elif not api_key.startswith("nvapi-"):
        result.errors.append(ValidationError(
            field="NIM_API_KEY",
            message=f"NIM_API_KEY should start with 'nvapi-'. Current value starts with '{api_key[:8]}...'",
            severity=Severity.ERROR,
            current_value=api_key[:8] + "...",
        ))


def _validate_mt5_credentials(settings: Any, result: ValidationResult) -> None:
    """Validate MT5 broker credentials.

    Checks that login is numeric, password is set, server is not empty.
    Only fatal in live mode (paper mode can proceed without MT5).
    """
    broker = settings.broker
    is_paper = getattr(broker, "type", "paper") == "paper"

    login = broker.mt5_login or int(os.getenv("Noema_MT5_LOGIN", "0"))
    password = broker.mt5_password or os.getenv("Noema_MT5_PASSWORD", "")
    server = broker.mt5_server or os.getenv("Noema_MT5_SERVER", "")

    if login <= 0:
        msg = "MT5 login is not set or is zero. Set Noema_MT5_LOGIN in .env"
        if is_paper:
            result.warnings.append(ValidationError(field="Noema_MT5_LOGIN", message=msg, severity=Severity.WARNING))
        else:
            result.errors.append(ValidationError(field="Noema_MT5_LOGIN", message=msg, severity=Severity.FATAL, current_value=login))

    if not password:
        msg = "MT5 password is not set. Set Noema_MT5_PASSWORD in .env"
        if is_paper:
            result.warnings.append(ValidationError(field="Noema_MT5_PASSWORD", message=msg, severity=Severity.WARNING))
        else:
            result.errors.append(ValidationError(field="Noema_MT5_PASSWORD", message=msg, severity=Severity.FATAL))

    if not server:
        msg = "MT5 server is not set. Set Noema_MT5_SERVER in .env (e.g., FxPesa-Demo)"
        if is_paper:
            result.warnings.append(ValidationError(field="Noema_MT5_SERVER", message=msg, severity=Severity.WARNING))
        else:
            result.errors.append(ValidationError(field="Noema_MT5_SERVER", message=msg, severity=Severity.FATAL))


def _validate_secret_key(settings: Any, result: ValidationResult) -> None:
    """Validate NOEMA_SECRET_KEY strength."""
    secret = settings.noema_secret_key or os.getenv("NOEMA_SECRET_KEY", "")
    if not secret:
        result.warnings.append(ValidationError(
            field="NOEMA_SECRET_KEY",
            message="NOEMA_SECRET_KEY is not set. Dashboard API and shutdown endpoint will be unprotected. Generate with: openssl rand -hex 32",
            severity=Severity.WARNING,
        ))
    elif len(secret) < 16:
        result.warnings.append(ValidationError(
            field="NOEMA_SECRET_KEY",
            message=f"NOEMA_SECRET_KEY is too short ({len(secret)} chars). Use at least 32 hex chars for security.",
            severity=Severity.WARNING,
        ))


def _validate_duplicate_pairs(settings: Any, result: ValidationResult) -> None:
    """Check for duplicate trading pairs."""
    pairs = getattr(settings.trading, "pairs", [])
    seen = set()
    for pair in pairs:
        upper = pair.upper()
        if upper in seen:
            result.errors.append(ValidationError(
                field="settings.trading.pairs",
                message=f"Duplicate trading pair '{pair}' found. Each pair should appear only once.",
                severity=Severity.ERROR,
                current_value=pairs,
            ))
        seen.add(upper)

    # Validate pair format
    valid_pattern = re.compile(r"^[A-Z]{6}$|^XAUUSD$|^XAGUSD$|^US30$|^NAS100$")
    for pair in pairs:
        if not valid_pattern.match(pair.upper()):
            result.warnings.append(ValidationError(
                field="settings.trading.pairs",
                message=f"Trading pair '{pair}' has unexpected format. Standard forex pairs are 6 chars (EURUSD).",
                severity=Severity.WARNING,
                current_value=pair,
            ))


def _validate_event_settings(settings: Any, result: ValidationResult) -> None:
    """Validate event calendar settings consistency."""
    event = settings.event
    if event.lead_minutes + event.trail_minutes > event.max_blackout_minutes:
        result.warnings.append(ValidationError(
            field="settings.event.max_blackout_minutes",
            message=(
                f"lead_minutes ({event.lead_minutes}) + trail_minutes ({event.trail_minutes}) = "
                f"{event.lead_minutes + event.trail_minutes} exceeds max_blackout_minutes ({event.max_blackout_minutes}). "
                "Blackout watchdog may force-release before normal blackout ends."
            ),
            severity=Severity.WARNING,
        ))


def _validate_log_level(settings: Any, result: ValidationResult) -> None:
    """Validate log level is recognized."""
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    log_level = getattr(settings, "log_level", "INFO").upper()
    if log_level not in valid_levels:
        result.errors.append(ValidationError(
            field="settings.log_level",
            message=f"Invalid log level '{log_level}'. Must be one of: {', '.join(sorted(valid_levels))}",
            severity=Severity.ERROR,
            current_value=log_level,
        ))


# ═══════════════════════════════════════════════════
# Main Validator
# ═══════════════════════════════════════════════════

def validate_config(
    settings: Any,
    env_file: str | Path = ".env",
    mode: str = "production",
) -> ValidationResult:
    """Validate all Noema configuration at startup.

    Checks performed:
    1. Required environment variables present
    2. Required settings fields non-empty
    3. Numeric ranges on risk, trading, event config
    4. Enum values on broker type, architecture mode, etc.
    5. Pattern/format checks on URLs and IDs
    6. Special validators: API key format, MT5 creds, secret strength
    7. Cross-field consistency (e.g., event lead+trail vs max blackout)

    Args:
        settings: Settings instance from noema.core.settings
        env_file: Path to .env file for extra checks
        mode: "production" (fatal on missing critical config) or "development"

    Returns:
        ValidationResult with is_valid=False if any FATAL errors found
    """
    result = ValidationResult()
    is_dev = mode != "production"

    logger.info("config_validation_starting", mode=mode)

    # ── 1. Required environment variables ──────────────────────────
    for var_name, description in REQUIRED_ENV_VARS.items():
        value = os.getenv(var_name, "")
        if not value:
            msg = f"Required env var '{var_name}' is not set. {description}"
            if is_dev:
                result.warnings.append(ValidationError(field=var_name, message=msg, severity=Severity.WARNING))
            else:
                result.errors.append(ValidationError(field=var_name, message=msg, severity=Severity.FATAL))

    # ── 2. Recommended environment variables ───────────────────────
    for var_name, description in RECOMMENDED_ENV_VARS.items():
        value = os.getenv(var_name, "")
        if not value:
            result.warnings.append(ValidationError(
                field=var_name,
                message=f"Recommended env var '{var_name}' is not set. {description}",
                severity=Severity.WARNING,
            ))

    # ── 3. Check .env file existence ──────────────────────────────
    env_path = Path(env_file)
    if not env_path.exists():
        result.warnings.append(ValidationError(
            field=".env",
            message=f"No .env file found at {env_path.absolute()}. Create from .env.example: cp .env.example .env",
            severity=Severity.WARNING,
        ))
    else:
        logger.info("env_file_found", path=str(env_path.absolute()))

    # ── 4. Required settings fields (non-empty) ───────────────────
    for field_path, description in REQUIRED_SETTINGS_FIELDS.items():
        value = _get_nested(settings, field_path)
        if value is None or (isinstance(value, (list, str, dict)) and len(value) == 0):
            result.errors.append(ValidationError(
                field=field_path,
                message=f"Required setting '{field_path}' is empty. {description}",
                severity=Severity.ERROR,
            ))

    # ── 5. Numeric range checks ───────────────────────────────────
    for field_path, min_val, max_val, unit_desc in RANGE_CHECKS:
        value = _get_nested(settings, field_path)
        if value is None:
            continue  # Missing values caught above
        try:
            numeric = float(value)
            if numeric < min_val or numeric > max_val:
                result.errors.append(ValidationError(
                    field=field_path,
                    message=f"'{field_path}' = {numeric} is out of range. Expected {min_val}–{max_val}. {unit_desc}",
                    severity=Severity.ERROR,
                    current_value=numeric,
                ))
        except (TypeError, ValueError):
            result.errors.append(ValidationError(
                field=field_path,
                message=f"'{field_path}' = {value} is not a valid number. {unit_desc}",
                severity=Severity.ERROR,
                current_value=value,
            ))

    # ── 6. Enum checks ────────────────────────────────────────────
    for field_path, allowed, description in ENUM_CHECKS:
        value = _get_nested(settings, field_path)
        if value is None:
            continue
        value_str = str(value).lower().strip()
        allowed_lower = [a.lower() for a in allowed]
        if value_str not in allowed_lower:
            result.errors.append(ValidationError(
                field=field_path,
                message=f"'{field_path}' = '{value}' is invalid. Must be one of: {allowed}. {description}",
                severity=Severity.ERROR,
                current_value=value,
            ))

    # ── 7. Pattern checks ─────────────────────────────────────────
    for field_path, pattern, description in PATTERN_CHECKS:
        value = str(_get_nested(settings, field_path) or "")
        if value and not pattern.match(value):
            result.errors.append(ValidationError(
                field=field_path,
                message=f"'{field_path}' = '{value}' does not match expected format. {description}",
                severity=Severity.ERROR,
                current_value=value,
            ))

    # ── 8. Special validators ─────────────────────────────────────
    _validate_api_key(settings, result)
    _validate_mt5_credentials(settings, result)
    _validate_secret_key(settings, result)
    _validate_duplicate_pairs(settings, result)
    _validate_event_settings(settings, result)
    _validate_log_level(settings, result)

    # ── Post-validation: determine overall validity ───────────────
    result.is_valid = len(result.fatal_errors) == 0

    # ── Summary logging ──────────────────────────────────────────
    fatal_count = len(result.fatal_errors)
    error_count = len(result.errors) - fatal_count
    warn_count = len(result.warnings)

    if fatal_count > 0:
        logger.critical(
            "config_validation_failed",
            fatal=fatal_count,
            errors=error_count,
            warnings=warn_count,
            fatal_details=[e.message for e in result.fatal_errors],
        )
    elif error_count > 0 or warn_count > 0:
        logger.warning(
            "config_validation_warnings",
            errors=error_count,
            warnings=warn_count,
        )
    else:
        logger.info("config_validation_passed", status="clean")

    return result


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════

def _get_nested(obj: Any, dotted_path: str) -> Any:
    """Get a nested attribute using dot-separated path.

    Example: _get_nested(settings, "settings.risk.max_daily_loss")
    → settings.risk.max_daily_loss
    """
    parts = dotted_path.split(".")
    current = obj
    for part in parts:
        if current is None:
            return None
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def format_validation_errors(result: ValidationResult) -> str:
    """Format validation errors for human-readable display.

    Returns a multi-line string suitable for terminal output.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("Noema Configuration Validation Results")
    lines.append("=" * 60)

    if result.is_valid:
        lines.append("✅ Configuration is valid.")
        if result.warnings:
            lines.append(f"\n⚠️  {len(result.warnings)} warning(s):")
            for w in result.warnings:
                lines.append(f"   [{w.severity.value.upper()}] {w.field}: {w.message}")
        return "\n".join(lines)

    fatal = result.fatal_errors
    errors = [e for e in result.errors if e.severity != Severity.FATAL]
    warnings = result.warnings

    if fatal:
        lines.append(f"\n❌ {len(fatal)} FATAL error(s) — startup will be aborted:")
        for f in fatal:
            lines.append(f"   🔴 {f.field}: {f.message}")
    if errors:
        lines.append(f"\n⚠️  {len(errors)} error(s):")
        for e in errors:
            lines.append(f"   🟡 {e.field}: {e.message}")
    if warnings:
        lines.append(f"\n💡 {len(warnings)} warning(s):")
        for w in warnings:
            lines.append(f"   🔵 {w.field}: {w.message}")

    lines.append("\n" + "=" * 60)
    if fatal:
        lines.append("Fix the FATAL errors above and restart Noema.")
    lines.append("=" * 60)

    return "\n".join(lines)
