"""Max-Lot Hardware Barrier — Compile-Time Lot Size Protection.

Provides a HARD, COMPILE-TIME limit on position sizes that cannot be
overridden by ANY agent, ANY LLM, ANY config file. This is a physical
gate at the order boundary — the last line of defense before any
order reaches the broker.

The Committee's single most non-negotiable requirement:
"Noema_MAX_LOT_SIZE compile-time constant and BrokerGateway check MUST
be implemented and tested before ANY live trading."

Architecture:
    ORDER REQUEST → [MAX_LOT_SIZE CHECK] → OrderRejectedError OR → Broker

Defense-in-depth:
    1. Guardian (logical check) — can be configured
    2. BrokerGateway lot_protection (physical check) — COMPILE-TIME CONSTANT
    Both must agree before any order reaches MT5.

Implements AC1.8, AC1.9, AC1.10 from the Noema Blueprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ═══════════════════════════════════════════════════
# COMPILE-TIME CONSTANT — CANNOT BE CHANGED AT RUNTIME
# ═══════════════════════════════════════════════════

# This is intentionally defined at module level as a simple constant.
# No config override. No env var. No LLM can touch this.
# To change: edit this file and redeploy.
Noema_MAX_LOT_SIZE: float = 1.0
"""Maximum lot size per trade. COMPILE-TIME CONSTANT.

Cannot be overridden by ANY agent, ANY LLM, ANY config change 
without a code deploy. This is the physical gate before any order
reaches the broker.

The Guardian also checks max lot size (defense-in-depth). Both
barriers must agree for an order to execute.
"""

# ═══════════════════════════════════════════════════
# Exception Types
# ═══════════════════════════════════════════════════


class OrderRejectedError(Exception):
    """Order rejected by the max-lot hardware barrier.

    Raised BEFORE any broker call when a position size exceeds
    Noema_MAX_LOT_SIZE. This is intentionally raised BEFORE any
    MT5 API call — the order never leaves the process.
    """

    def __init__(
        self,
        message: str = "",
        lot_size: float = 0.0,
        max_allowed: float = Noema_MAX_LOT_SIZE,
        symbol: str = "",
        source: str = "lot_protection",
    ):
        self.lot_size = lot_size
        self.max_allowed = max_allowed
        self.symbol = symbol
        self.source = source
        full_msg = (
            f"OrderRejectedError: lot_size={lot_size} exceeds "
            f"Noema_MAX_LOT_SIZE={max_allowed}. Symbol={symbol}. "
            f"Source={source}. {message}"
        )
        super().__init__(full_msg)


# ═══════════════════════════════════════════════════
# Max-Lot Protection Gate
# ═══════════════════════════════════════════════════


@dataclass
class LotCheckResult:
    """Result of a max-lot check.

    Attributes:
        passed: True if the lot size is within limits.
        lot_size: The requested lot size.
        max_allowed: The maximum allowed lot size.
        message: Human-readable result message.
    """
    passed: bool
    lot_size: float
    max_allowed: float
    message: str = ""


def check_max_lot(
    lot_size: float,
    symbol: str = "",
    raise_on_fail: bool = True,
) -> LotCheckResult:
    """Check if a lot size is within the hardware limit.

    This is the PHYSICAL gate. Call this BEFORE any broker operation.
    If the check fails, the order MUST NOT be sent to the broker.

    Priority:
    1. Environment override `Noema_MAX_LOT_SIZE` (e.g., 0.01 for first run)
    2. Compile-time constant `Noema_MAX_LOT_SIZE` (1.0 default)
    The LOWER of the two is used — defense-in-depth.

    Args:
        lot_size: The requested position size in lots.
        symbol: Trading symbol (for error messages).
        raise_on_fail: If True, raises OrderRejectedError on failure.

    Returns:
        LotCheckResult indicating pass/fail.

    Raises:
        OrderRejectedError: If raise_on_fail=True and check fails.
    """
    import os
    # Allow env override to REDUCE max lot (e.g., first-run micro-lot mode)
    # The env override can only LOWER the cap, never raise it above the compile-time constant
    env_max = os.getenv("Noema_MAX_LOT_SIZE", "")
    compile_max = Noema_MAX_LOT_SIZE
    if env_max:
        try:
            env_val = float(env_max)
            # Use the LOWER of env override and compile-time constant
            max_lot = min(env_val, compile_max)
        except ValueError:
            max_lot = compile_max
    else:
        max_lot = compile_max

    passed = lot_size <= max_lot

    if passed:
        message = f"Lot check passed: {lot_size} <= {max_lot}"
    else:
        message = (
            f"LOT SIZE {lot_size} EXCEEDS HARD CAP {max_lot}! "
            f"Symbol={symbol}. ORDER BLOCKED before broker."
        )

    result = LotCheckResult(
        passed=passed,
        lot_size=lot_size,
        max_allowed=max_lot,
        message=message,
    )

    if not passed and raise_on_fail:
        raise OrderRejectedError(
            message=message,
            lot_size=lot_size,
            max_allowed=max_lot,
            symbol=symbol,
        )

    return result


def reject_order_if_exceeds_max_lot(
    lot_size: float,
    symbol: str = "",
) -> None:
    """Convenience function: rejects order if lot exceeds max.

    Use this as a guard clause at the beginning of any broker
    place_order() method:

        reject_order_if_exceeds_max_lot(lot_size, symbol)

    Always uses the compile-time constant Noema_MAX_LOT_SIZE.
    Callers CANNOT override the limit.

    The OrderRejectedError should be caught at the execution layer
    and logged as an execution.rejected event.

    Args:
        lot_size: Requested lot size.
        symbol: Trading symbol.

    Raises:
        OrderRejectedError: If lot exceeds Noema_MAX_LOT_SIZE.
    """
    check_max_lot(lot_size, symbol=symbol, raise_on_fail=True)


def validate_total_exposure(
    positions: list[dict[str, Any]],
    new_lot_size: float,
    max_total_lots: float = 5.0,
) -> LotCheckResult:
    """Check that total exposure doesn't exceed the system limit.

    Sums all open position lot sizes + the new lot and checks
    against max_total_lots. Additional safety beyond per-trade max.

    Args:
        positions: List of open positions with 'volume' key.
        new_lot_size: Proposed new position size.
        max_total_lots: Maximum total lots across all positions.

    Returns:
        LotCheckResult.
    """
    total_existing = sum(pos.get("volume", 0.0) for pos in positions)
    total_after = total_existing + new_lot_size
    passed = total_after <= max_total_lots

    if passed:
        message = f"Total exposure check passed: {total_after} <= {max_total_lots}"
    else:
        message = (
            f"TOTAL EXPOSURE {total_after} EXCEEDS CAP {max_total_lots}! "
            f"Existing: {total_existing}, New: {new_lot_size}. ORDER BLOCKED."
        )

    return LotCheckResult(
        passed=passed,
        lot_size=new_lot_size,
        max_allowed=max_total_lots,
        message=message,
    )
