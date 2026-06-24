"""Demo Account Verification — CRITICAL SAFETY CHECK.

Ensures Noema is connected to a DEMO account before allowing live trading.
This is the HARD BARRIER that prevents trading real money by accident.
"""

from __future__ import annotations

import os
import socket
import sys
from typing import Tuple


def _port_is_open(host: str = "127.0.0.1", port: int = 18812, timeout: float = 2.0) -> bool:
    """Check if the MT5 RPyC bridge port is accepting connections."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def verify_demo_account(host: str = "127.0.0.1", port: int = 18812) -> Tuple[bool, str]:
    """Verify MT5 is connected to a DEMO server.

    Returns:
        Tuple of (is_demo: bool, server_name: str)
    """
    # Emergency override — DO NOT USE CASUALLY
    if os.getenv("Noema_ALLOW_LIVE_ACCOUNT", "").lower() in ("true", "1", "yes"):
        return True, "LIVE (override active — EMERGENCY MODE)"

    if not _port_is_open(host, port):
        return False, f"Cannot connect to MT5 on {host}:{port}"

    try:
        from mt5linux import MetaTrader5
        mt5 = MetaTrader5(host=host, port=port)
        if not mt5.initialize():
            return False, "MT5 initialize() failed — check credentials"
        info = mt5.account_info()
        mt5.shutdown()
        if info is None:
            return False, "account_info() returned None — check login"
        server = info.server
        is_demo = "demo" in server.lower()
        return is_demo, server
    except ImportError:
        return False, "mt5linux package not installed (pip install mt5linux)"
    except Exception as exc:
        return False, f"Verification error: {exc}"


def get_account_details(host: str = "127.0.0.1", port: int = 18812) -> dict | None:
    """Get full account details for display/dashboard."""
    if not _port_is_open(host, port):
        return None
    try:
        from mt5linux import MetaTrader5
        mt5 = MetaTrader5(host=host, port=port)
        if not mt5.initialize():
            return None
        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            return None
        details = {
            "login": info.login,
            "server": info.server,
            "balance": float(info.balance),
            "equity": float(info.equity),
            "margin": float(getattr(info, "margin", 0)),
            "margin_free": float(getattr(info, "margin_free", 0)),
            "margin_level": float(getattr(info, "margin_level", 0)),
            "leverage": info.leverage,
            "currency": info.currency,
            "is_demo": "demo" in info.server.lower(),
        }
        try:
            positions = mt5.positions_get()
            details["open_positions"] = len(positions) if positions else 0
            if positions:
                details["positions"] = []
                for p in positions[:10]:
                    details["positions"].append({
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "type": "buy" if p.type == 0 else "sell",
                        "volume": float(p.volume),
                        "open_price": float(p.price_open),
                        "current_price": float(p.price_current),
                        "profit": float(p.profit),
                    })
        except Exception:
            details["open_positions"] = -1
        mt5.shutdown()
        return details
    except Exception:
        return None
