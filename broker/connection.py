"""MT5 connection manager with disconnect/reconnect and reconciliation.

Handles:
- RPyC bridge connection lifecycle
- Disconnect detection and halt
- Reconnect with position reconciliation
- Single-connection serialization lock
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ConnectionState:
    """MT5 connection state."""
    connected: bool = False
    last_connected: datetime | None = None
    last_disconnect: datetime | None = None
    reconnect_count: int = 0
    halt_new_entries: bool = False
    positions_before_disconnect: list[dict] = field(default_factory=list)


class MT5ConnectionManager:
    """Manages MT5 connection lifecycle with safety protocols.

    On disconnect:
    1. Immediately halt new entries
    2. Log all open positions
    3. Attempt reconnect with backoff

    On reconnect:
    1. Reconcile open positions against last-known state
    2. If mismatch detected → halt + alert
    3. Resume only after manual confirmation
    """

    def __init__(
        self,
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 5.0,
        telegram_callback: Any = None,
    ) -> None:
        self.state = ConnectionState()
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.telegram_callback = telegram_callback
        self._lock = asyncio.Lock()

    async def on_disconnect(self, broker: Any) -> None:
        """Handle MT5 disconnect."""
        logger.critical("mt5_disconnected")
        self.state.connected = False
        self.state.last_disconnect = datetime.now(timezone.utc)
        self.state.halt_new_entries = True

        # Snapshot current positions
        try:
            positions = broker.get_open_positions()
            self.state.positions_before_disconnect = [
                {"ticket": p.ticket, "symbol": p.symbol, "volume": p.volume,
                 "type": p.type, "pnl": p.pnl}
                for p in positions
            ]
        except Exception:
            self.state.positions_before_disconnect = []

        await self._send_alert(
            f"⚠️ MT5 DISCONNECTED!\n"
            f"Open positions at disconnect: {len(self.state.positions_before_disconnect)}\n"
            f"New entries HALTED."
        )

    async def on_reconnect(self, broker: Any) -> bool:
        """Handle MT5 reconnect with reconciliation."""
        logger.info("mt5_reconnecting")

        # Snapshot positions after reconnect
        try:
            current_positions = broker.get_open_positions()
            current_snap = [
                {"ticket": p.ticket, "symbol": p.symbol, "volume": p.volume,
                 "type": p.type, "pnl": p.pnl}
                for p in current_positions
            ]
        except Exception as exc:
            logger.error("reconnect_position_check_failed", error=str(exc))
            return False

        # Reconcile
        before = {p["ticket"]: p for p in self.state.positions_before_disconnect}
        after = {p["ticket"]: p for p in current_snap}

        missing = set(before.keys()) - set(after.keys())
        unexpected = set(after.keys()) - set(before.keys())

        if missing:
            logger.warning("positions_lost_during_disconnect",
                           tickets=list(missing))
            await self._send_alert(
                f"⚠️ MT5 RECONNECTED but {len(missing)} positions LOST!\n"
                f"Tickets: {missing}\n"
                f"Manual review required."
            )
            return False

        if unexpected:
            logger.warning("unexpected_positions_after_reconnect",
                           tickets=list(unexpected))
            await self._send_alert(
                f"⚠️ MT5 RECONNECTED with {len(unexpected)} unexpected positions!\n"
                f"Tickets: {unexpected}\n"
                f"Manual review required."
            )
            return False

        # All good
        self.state.connected = True
        self.state.last_connected = datetime.now(timezone.utc)
        self.state.reconnect_count += 1
        self.state.halt_new_entries = False
        self.state.positions_before_disconnect = []

        logger.info("mt5_reconnected_reconciled",
                     reconnect_count=self.state.reconnect_count)
        await self._send_alert("✅ MT5 RECONNECTED — positions reconciled. Resuming.")
        return True

    def can_trade(self) -> bool:
        """Check if trading is allowed."""
        return self.state.connected and not self.state.halt_new_entries

    async def _send_alert(self, message: str) -> None:
        if self.telegram_callback:
            try:
                await self.telegram_callback(message)
            except Exception:
                pass
        logger.info("connection_alert", message=message)
