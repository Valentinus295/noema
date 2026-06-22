"""
Noema Rust Bridge
=================

Import PyO3-compiled Rust modules with graceful fallback when
the Rust extension hasn't been compiled yet.

Usage:
    from noema.rust_bridge import smc, data, backtest

    # SMC indicators (fast path)
    fvgs = smc.detect_fvgs(highs, lows)

    # Data aggregation
    aggregator = data.OhlcvAggregator("H1")

    # Backtesting
    engine = backtest.BacktestEngine(initial_balance=10_000)

All modules return stub objects when Rust isn't available,
so the rest of Noema won't crash — it'll just log a warning
and fall back to Python implementations.
"""

from __future__ import annotations

import logging
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)

_RUST_AVAILABLE: bool = False
_IMPORT_ERRORS: dict[str, str] = {}


def _try_import_rust(module_name: str) -> ModuleType:
    """Try to import a Rust PyO3 module."""
    try:
        mod = __import__(module_name)
        return mod
    except ImportError as e:
        _IMPORT_ERRORS[module_name] = str(e)
        raise


def _stub_module(name: str, reason: str) -> ModuleType:
    """Create a stub module that warns and returns None/empty values."""
    stub = ModuleType(name)
    stub.__doc__ = f"STUB: Rust module `{name}` not compiled. {reason}"

    def _stub_call(*args: Any, **kwargs: Any) -> Any:
        logger.debug(
            f"Rust module `{name}` not available. "
            f"Call to stub function ignored."
        )
        return None

    # Make the stub callable and attribute-accessible
    stub.__call__ = _stub_call

    class _StubAttr:
        def __getattr__(self, _attr: str) -> Any:
            logger.debug(
                f"Rust module `{name}` not available. "
                f"Accessing `{_attr}` on stub."
            )
            return _stub_call

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return _stub_call(*args, **kwargs)

    stub.__class__ = type(
        "_StubModule",
        (ModuleType,),
        {"__getattr__": _StubAttr.__getattr__, "__call__": _stub_call},
    )
    return stub


# ── SMC Module ────────────────────────────────────────────────

try:
    smc = _try_import_rust("noema_smc")
    _RUST_AVAILABLE = True
    logger.info("Rust SMC module loaded successfully.")
except ImportError:
    smc = _stub_module(
        "noema_smc",
        "Build with: cd rust && maturin develop --release -m noema-smc/Cargo.toml",
    )
    logger.warning(
        "Rust SMC module not available. Install with: "
        "`cd rust/noema-smc && maturin develop --release`"
    )

# ── Data Module ───────────────────────────────────────────────

try:
    data = _try_import_rust("noema_data")
    logger.info("Rust data module loaded successfully.")
except ImportError:
    data = _stub_module(
        "noema_data",
        "Build with: cd rust && maturin develop --release -m noema-data/Cargo.toml",
    )
    logger.warning(
        "Rust data module not available. Install with: "
        "`cd rust/noema-data && maturin develop --release`"
    )

# ── Backtest Module ───────────────────────────────────────────

try:
    backtest = _try_import_rust("noema_backtest")
    logger.info("Rust backtest module loaded successfully.")
except ImportError:
    backtest = _stub_module(
        "noema_backtest",
        "Build with: cd rust && maturin develop --release -m noema-backtest/Cargo.toml",
    )
    logger.warning(
        "Rust backtest module not available. Install with: "
        "`cd rust/noema-backtest && maturin develop --release`"
    )


def is_rust_available() -> bool:
    """Check if at least one Rust module loaded successfully."""
    return _RUST_AVAILABLE


def rust_status() -> dict[str, bool | dict[str, str]]:
    """Get the status of all Rust modules."""
    return {
        "available": _RUST_AVAILABLE,
        "import_errors": dict(_IMPORT_ERRORS),
        "modules": {
            "smc": not isinstance(smc, ModuleType) or "STUB" not in (smc.__doc__ or ""),
            "data": not isinstance(data, ModuleType) or "STUB" not in (data.__doc__ or ""),
            "backtest": not isinstance(backtest, ModuleType) or "STUB" not in (backtest.__doc__ or ""),
        },
        "python_version": sys.version,
        "build_instructions": (
            "cd rust && maturin develop --release "
            "-m noema-smc/Cargo.toml "
            "-m noema-data/Cargo.toml "
            "-m noema-backtest/Cargo.toml"
        ),
    }


__all__ = ["smc", "data", "backtest", "is_rust_available", "rust_status"]
