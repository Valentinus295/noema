"""DEPRECATED: Use core.settings instead.

This module provides backward-compatible aliases.
All new code should import from noema.core.settings directly.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from noema.core.settings import Settings, load_settings, RiskConfig

warnings.warn(
    "noema.core.config is deprecated. Use noema.core.settings instead.",
    DeprecationWarning,
    stacklevel=2,
)


# Backward-compatible aliases
NoemaConfig = Settings


def load_config(path: str | Path | None = None) -> Settings:
    """Backward-compatible wrapper for load_settings."""
    if path is not None:
        path = Path(path)
    return load_settings(path)
