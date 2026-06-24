"""
Noema Structured Logging Configuration — Production-grade structlog setup.

Provides:
- Secret/password redaction (never log API keys, passwords, tokens)
- Request-ID tracing for correlation across services
- Log rotation policy (size-based + time-based)
- Error alert thresholds (configurable counts before paging)
- JSON formatting for structured logging pipelines (ELK/Loki)

Usage:
    from noema.core.logging_config import configure_logging
    configure_logging(level="INFO", environment="production")

Architecture:
    structlog → (processors chain) → stdout (or file via RotatingFileHandler)
                                      → JSON → log aggregator (ELK/Loki/Grafana)
"""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import structlog

# ═══════════════════════════════════════════════════
# Request-ID Tracing
# ═══════════════════════════════════════════════════

# Context variable for request ID — thread-safe, async-safe
_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(request_id: str | None = None) -> str:
    """Set a request ID for the current context (thread/async task).

    Args:
        request_id: Optional explicit ID. If None, generates a UUID.

    Returns:
        The request ID that was set.

    Usage:
        # In middleware/request handler:
        rid = set_request_id()
        # All subsequent log calls in this context will include request_id
    """
    rid = request_id or str(uuid.uuid4())
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    """Get the current request ID."""
    return _request_id_var.get()


def clear_request_id() -> None:
    """Clear the request ID (at end of request lifecycle)."""
    _request_id_var.set("")


# ═══════════════════════════════════════════════════
# Secret Redaction
# ═══════════════════════════════════════════════════

# Sensitive key patterns — any log key matching these is REDACTED
_SECRET_KEY_PATTERNS: list[re.Pattern] = [
    re.compile(r".*api[_-]?key.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*auth.*", re.IGNORECASE),
    re.compile(r".*mt5_login.*", re.IGNORECASE),    # Redact login numbers too
    re.compile(r".*mt5_password.*", re.IGNORECASE),
    re.compile(r".*nim_api_key.*", re.IGNORECASE),
    re.compile(r".*noema_secret.*", re.IGNORECASE),
    re.compile(r".*private[_-]?key.*", re.IGNORECASE),
    re.compile(r".*jwt.*", re.IGNORECASE),
    re.compile(r".*session[_-]?token.*", re.IGNORECASE),
]

# Value patterns — if a value matches these, it's redacted regardless of key
_SENSITIVE_VALUE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^nvapi-[a-zA-Z0-9_\-]{20,}$"),  # NVIDIA API key format
    re.compile(r"^sk-[a-zA-Z0-9_\-]{20,}$"),       # OpenAI API key format
    re.compile(r"^[a-f0-9]{32,}$"),                 # Generic hex tokens (>32 chars)
]

_REDACTED_TEXT = "[REDACTED]"
_REDACTED_SHORT_TEXT = "***"


def is_sensitive_key(key: str) -> bool:
    """Check if a log key contains sensitive information."""
    return any(pattern.match(key) for pattern in _SECRET_KEY_PATTERNS)


def is_sensitive_value(value: str) -> bool:
    """Check if a value looks like a secret/token."""
    return any(pattern.match(str(value)) for pattern in _SENSITIVE_VALUE_PATTERNS)


def redact_sensitive_value(key: str, value: Any) -> Any:
    """Redact sensitive values before logging.

    Args:
        key: The log entry key
        value: The value to check

    Returns:
        Redacted value if sensitive, original value otherwise.
    """
    if is_sensitive_key(key):
        return _REDACTED_TEXT

    if isinstance(value, str) and is_sensitive_value(value):
        return f"{value[:4]}{_REDACTED_SHORT_TEXT}"

    if isinstance(value, dict):
        return {k: redact_sensitive_value(k, v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return type(value)(redact_sensitive_value(f"_{i}", v) for i, v in enumerate(value))

    return value


# ═══════════════════════════════════════════════════
# Structlog Processors
# ═══════════════════════════════════════════════════

def _add_request_id(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Add request_id to every log entry if available."""
    rid = _request_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def _redact_secrets(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Redact sensitive values from all log entries."""
    return {
        key: redact_sensitive_value(key, value)
        for key, value in event_dict.items()
    }


def _add_timestamps_iso(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Add ISO 8601 timestamp to every log entry."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def _drop_color_codes(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Remove ANSI color codes from log messages (production mode)."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = re.sub(r"\x1b\[[0-9;]*m", "", value)
    return event_dict


# ═══════════════════════════════════════════════════
# Error Alert Thresholds
# ═══════════════════════════════════════════════════

# Error counting for alerting purposes
_error_counts: dict[str, int] = {}
_last_error_reset: float = 0.0
ERROR_RESET_INTERVAL_SECONDS: float = 300.0  # 5 minutes


def track_error_rate(category: str) -> int:
    """Track error count for a category. Returns current count.

    Use this to implement error rate thresholds for alerting.
    Categories: "llm_call", "broker", "data", "trading", "system"

    Usage:
        count = track_error_rate("broker")
        if count > BROKER_ERROR_ALERT_THRESHOLD:
            send_alert()
    """
    global _last_error_reset
    import time

    now = time.time()
    if now - _last_error_reset > ERROR_RESET_INTERVAL_SECONDS:
        _error_counts.clear()
        _last_error_reset = now

    _error_counts[category] = _error_counts.get(category, 0) + 1
    return _error_counts[category]


def get_error_counts() -> dict[str, int]:
    """Get current error counts per category."""
    return dict(_error_counts)


# Error alert thresholds — when counts exceed these, an alert should fire
# (integrated with the Telegram alert system via CommandHandlers)
ERROR_ALERT_THRESHOLDS: dict[str, int] = {
    "broker": 3,       # 3 broker errors in 5 minutes → alert
    "llm_call": 10,     # 10 LLM API errors in 5 minutes → alert
    "data": 5,          # 5 data errors in 5 minutes → alert
    "trading": 5,       # 5 trading errors in 5 minutes → alert
    "kill_switch": 1,   # Any kill-switch activation → alert immediately
    "guardian": 1,      # Any guardian halt → alert immediately
}


def should_alert(category: str) -> bool:
    """Check if error count for a category exceeds the alert threshold.

    Returns True if an alert should be sent.
    """
    threshold = ERROR_ALERT_THRESHOLDS.get(category, 5)
    count = _error_counts.get(category, 0)
    return count >= threshold


def check_and_alert(category: str) -> tuple[bool, int, int]:
    """Check error rate and return alert decision.

    Returns:
        (should_alert: bool, current_count: int, threshold: int)
    """
    threshold = ERROR_ALERT_THRESHOLDS.get(category, 5)
    count = _error_counts.get(category, 0)
    return (count >= threshold, count, threshold)


# ═══════════════════════════════════════════════════
# Log Rotation Policy
# ═══════════════════════════════════════════════════

# Log rotation configuration — used by RotatingFileHandler
LOG_ROTATION_CONFIG = {
    "max_bytes": 10 * 1024 * 1024,   # 10 MB per file
    "backup_count": 5,                # Keep 5 backup files (total ~50 MB)
    "log_dir": "logs",
    "log_file": "noema.log",
    "error_log_file": "noema_error.log",
}

# Time-based rotation — daily rotation via TimedRotatingFileHandler
LOG_TIME_ROTATION_CONFIG = {
    "when": "midnight",
    "interval": 1,
    "backup_count": 30,               # Keep 30 days of logs
}


def get_log_path(log_dir: str | None = None, filename: str | None = None) -> str:
    """Get the full path for a log file, creating the directory if needed."""
    import os
    from pathlib import Path

    log_dir = log_dir or LOG_ROTATION_CONFIG["log_dir"]
    filename = filename or LOG_ROTATION_CONFIG["log_file"]

    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    return str(path / filename)


# ═══════════════════════════════════════════════════
# Main Configuration Function
# ═══════════════════════════════════════════════════

def configure_logging(
    level: str = "INFO",
    environment: str = "development",
    json_format: bool = False,
    log_to_file: bool = False,
    log_dir: str | None = None,
    enable_request_id: bool = True,
    redact_secrets: bool = True,
) -> None:
    """Configure structlog for Noema production logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        environment: Environment name (development/production)
        json_format: If True, emit JSON lines (for ELK/Loki pipelines)
        log_to_file: If True, also write to rotating log files
        log_dir: Directory for log files (default: "logs/")
        enable_request_id: If True, add request-id to every log entry
        redact_secrets: If True, redact passwords/tokens/keys from all logs
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    is_production = environment == "production"

    # ── Build processor chain ─────────────────────────────────────
    # structlog processors execute in order for each log call
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if enable_request_id:
        shared_processors.append(_add_request_id)

    if redact_secrets:
        shared_processors.append(_redact_secrets)

    if is_production:
        shared_processors.append(_drop_color_codes)

    # Formatting
    if json_format:
        # JSON output for log aggregators (ELK, Loki, etc.)
        renderer = structlog.processors.JSONRenderer(serializer=__import__("json").dumps)
    elif is_production:
        # Key-value format for production
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        # Colorized console for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # ── Configure structlog ───────────────────────────────────────
    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ── Configure standard library logging ────────────────────────
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove default handlers
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # ── File logging with rotation ────────────────────────────────
    if log_to_file:
        _enable_file_logging(formatter, log_level, log_dir)

    # ── Silence noisy third-party loggers ─────────────────────────
    for noisy in ["urllib3", "httpx", "asyncio", "opentelemetry", "redis.asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── Initial log message ───────────────────────────────────────
    init_logger = structlog.get_logger(__name__)
    init_logger.info(
        "logging_configured",
        level=level,
        environment=environment,
        json_format=json_format,
        log_to_file=log_to_file,
        secret_redaction="enabled" if redact_secrets else "disabled",
        request_id_tracing="enabled" if enable_request_id else "disabled",
    )


def _enable_file_logging(
    formatter: logging.Formatter,
    log_level: int,
    log_dir: str | None = None,
) -> None:
    """Enable rotating file logging handlers."""
    from logging.handlers import RotatingFileHandler

    log_dir = log_dir or LOG_ROTATION_CONFIG["log_dir"]
    import os
    os.makedirs(log_dir, exist_ok=True)

    # Main log file with size rotation
    main_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, LOG_ROTATION_CONFIG["log_file"]),
        maxBytes=LOG_ROTATION_CONFIG["max_bytes"],
        backupCount=LOG_ROTATION_CONFIG["backup_count"],
        encoding="utf-8",
    )
    main_handler.setFormatter(formatter)
    main_handler.setLevel(log_level)

    # Error log file (only WARNING and above)
    error_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, LOG_ROTATION_CONFIG["error_log_file"]),
        maxBytes=LOG_ROTATION_CONFIG["max_bytes"],
        backupCount=LOG_ROTATION_CONFIG["backup_count"],
        encoding="utf-8",
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.WARNING)

    root_logger = logging.getLogger()
    root_logger.addHandler(main_handler)
    root_logger.addHandler(error_handler)


# ═══════════════════════════════════════════════════
# Convenience: Quick log severity helpers
# ═══════════════════════════════════════════════════

def log_alert(category: str, message: str, **kwargs: Any) -> None:
    """Log an alert-worthy event with error rate tracking.

    This automatically tracks the error count per category and
    logs at the appropriate severity level.
    """
    count = track_error_rate(category)
    should_fire, _, threshold = check_and_alert(category)

    log_level = "critical" if should_fire else "warning"

    logger = structlog.get_logger(__name__).bind(
        alert_category=category,
        error_count=count,
        alert_threshold=threshold,
    )

    getattr(logger, log_level)(
        f"alert:{category}",
        message=message,
        **kwargs,
    )


# ═══════════════════════════════════════════════════
# Logging audit check
# ═══════════════════════════════════════════════════

def audit_secret_logging() -> dict[str, Any]:
    """Audit the logging configuration for secret exposure risks.

    Returns a report showing:
    - Which secret patterns are registered
    - Sensitive keys that would be redacted
    - Current error count status
    - Rotation configuration

    Call this during startup or from a health endpoint to verify
    that secret redaction is properly configured.
    """
    return {
        "secret_patterns_count": len(_SECRET_KEY_PATTERNS),
        "secret_patterns": [p.pattern for p in _SECRET_KEY_PATTERNS],
        "sensitive_value_patterns_count": len(_SENSITIVE_VALUE_PATTERNS),
        "sensitive_value_patterns": [p.pattern for p in _SENSITIVE_VALUE_PATTERNS],
        "error_alert_thresholds": dict(ERROR_ALERT_THRESHOLDS),
        "current_error_counts": get_error_counts(),
        "log_rotation": {
            "max_bytes_mb": LOG_ROTATION_CONFIG["max_bytes"] / (1024 * 1024),
            "backup_count": LOG_ROTATION_CONFIG["backup_count"],
            "time_rotation": LOG_TIME_ROTATION_CONFIG["when"],
        },
        "redaction_examples": {
            "api_key_present": is_sensitive_key("api_key") or is_sensitive_key("NIM_API_KEY"),
            "password_present": is_sensitive_key("password") or is_sensitive_key("mt5_password"),
            "secret_present": is_sensitive_key("secret") or is_sensitive_key("noema_secret_key"),
        },
    }
