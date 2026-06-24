"""
Broker Status Tool — check MT5 connection and account state.

Provides real-time broker status information:
- Connection state (connected/disconnected/reconnecting)
- Account balance, equity, margin, free margin
- Current positions and P&L
- Server information

Pattern inspired by TradingAgents' data vendor abstraction:
agents get a single interface to broker state rather than dealing with
MT5 connection details directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from noema.tools import ToolDef

logger = logging.getLogger(__name__)


def get_broker_status() -> dict[str, Any]:
    """Check MT5 connection status and basic server info.

    Returns:
        dict with connection state, server info, and latency
    """
    status = {
        "connected": False,
        "server": None,
        "company": None,
        "latency_ms": None,
        "error": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5()
        connected = mt5.initialize()
        status["connected"] = connected

        if connected:
            terminal_info = mt5.terminal_info()
            if terminal_info:
                status["server"] = terminal_info.name if hasattr(terminal_info, "name") else "unknown"
                status["company"] = terminal_info.company if hasattr(terminal_info, "company") else "unknown"

            status["latency_ms"] = _measure_latency(mt5)

            mt5.shutdown()
        else:
            status["error"] = "MT5 initialization failed"
    except ImportError:
        status["error"] = "MT5 not installed (mt5linux package missing)"
    except Exception as e:
        status["error"] = str(e)

    return status


def get_account_state() -> dict[str, Any]:
    """Get current account state: balance, equity, margin, exposure.

    Returns:
        dict with account financials and risk metrics
    """
    state = {
        "connected": False,
        "balance": 0.0,
        "equity": 0.0,
        "margin": 0.0,
        "free_margin": 0.0,
        "margin_level": 0.0,
        "currency": "USD",
        "leverage": None,
        "error": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5()
        if mt5.initialize():
            account = mt5.account_info()
            if account:
                state["connected"] = True
                state["balance"] = float(account.balance)
                state["equity"] = float(account.equity)
                state["margin"] = float(account.margin)
                state["free_margin"] = float(account.margin_free)
                state["margin_level"] = (
                    float(account.margin_level) if account.margin > 0 else 0.0
                )
                state["leverage"] = account.leverage if hasattr(account, "leverage") else None
                state["currency"] = account.currency if hasattr(account, "currency") else "USD"

                # ── Risk calculations ────────────────────────────
                state["exposure_pct"] = (
                    round(state["margin"] / state["equity"] * 100, 1)
                    if state["equity"] > 0
                    else 0.0
                )
                state["drawdown_pct"] = (
                    round((1 - state["equity"] / state["balance"]) * 100, 2)
                    if state["balance"] > 0
                    else 0.0
                )
                state["risk_level"] = _assess_risk(state)

                # ── Positions ────────────────────────────────────
                positions = mt5.positions_get()
                if positions:
                    state["positions"] = []
                    total_pnl = 0.0
                    for pos in positions:
                        pnl = float(pos.profit)
                        total_pnl += pnl
                        state["positions"].append({
                            "symbol": pos.symbol,
                            "type": "BUY" if pos.type == 0 else "SELL",
                            "volume": float(pos.volume),
                            "open_price": float(pos.price_open),
                            "current_price": float(pos.price_current),
                            "sl": float(pos.sl) if pos.sl else None,
                            "tp": float(pos.tp) if pos.tp else None,
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl / state["balance"] * 100, 2) if state["balance"] else 0,
                        })
                    state["position_count"] = len(state["positions"])
                    state["total_pnl"] = round(total_pnl, 2)
                else:
                    state["positions"] = []
                    state["position_count"] = 0
                    state["total_pnl"] = 0.0

            mt5.shutdown()
        else:
            state["error"] = "MT5 initialization failed"
    except ImportError:
        state["error"] = "MT5 not installed"
    except Exception as e:
        state["error"] = str(e)

    return state


def _measure_latency(mt5) -> float | None:
    """Measure MT5 server round-trip latency."""
    try:
        import time
        start = time.monotonic()
        mt5.account_info()
        elapsed = (time.monotonic() - start) * 1000
        return round(elapsed, 1)
    except Exception:
        return None


def _assess_risk(account: dict[str, Any]) -> str:
    """Assess account risk level based on margin usage and drawdown."""
    margin_level = account.get("margin_level", 0)
    exposure = account.get("exposure_pct", 0)
    drawdown = account.get("drawdown_pct", 0)

    if margin_level < 200 or exposure > 80:
        return "CRITICAL"
    elif margin_level < 500 or exposure > 50 or drawdown > 10:
        return "HIGH"
    elif margin_level < 1000 or exposure > 30 or drawdown > 5:
        return "MODERATE"
    return "LOW"


# ── ToolDefs for registration ──────────────────────────────────────────

broker_status_tool = ToolDef(
    name="get_broker_status",
    description=(
        "Check MT5 broker connection status. Returns whether the broker is "
        "connected, the server name, and connection latency. Use this before "
        "attempting any order execution to verify the connection is healthy."
    ),
    func=get_broker_status,
    parameters={},
    tags=["broker", "connection", "mt5", "status"],
    category="broker",
    requires_broker=True,
)

account_state_tool = ToolDef(
    name="get_account_state",
    description=(
        "Get the full MT5 account state: balance, equity, margin, free margin, "
        "margin level, current drawdown, and all open positions with P&L. "
        "Use this to check if the account has sufficient margin for a trade "
        "and to assess overall risk exposure. Returns risk_level (LOW/MODERATE/HIGH/CRITICAL)."
    ),
    func=get_account_state,
    parameters={},
    tags=["broker", "account", "risk", "positions", "balance"],
    category="broker",
    requires_broker=True,
)
