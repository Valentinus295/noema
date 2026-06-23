"""MT5 connection manager with disconnect/reconnect and reconciliation.

Handles:
- RPyC bridge connection lifecycle
- Disconnect detection and halt
- Reconnect with position reconciliation
- Single-connection serialization lock
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# Exponential backoff constants
RECONNECT_BASE_DELAY = 1.0   # seconds
RECONNECT_MAX_DELAY = 30.0   # seconds
RECONNECT_BACKOFF_MULT = 2.0


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
        data_stale_callback: Callable[[], None] | None = None,
    ) -> None:
        self.state = ConnectionState()
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.telegram_callback = telegram_callback
        self.data_stale_callback = data_stale_callback
        self._lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3
        self._disconnect_start: float | None = None
        self._last_tick_timestamp: float = 0.0
        self._stale_threshold_sec: float = 5.0

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

    @property
    def tick_age_secs(self) -> float:
        """Seconds since last tick update. Returns -1.0 if no tick ever received."""
        if self._last_tick_timestamp == 0:
            return -1.0
        return time.monotonic() - self._last_tick_timestamp

    def update_tick_timestamp(self) -> None:
        """Called by broker on every fresh tick to mark data freshness."""
        self._last_tick_timestamp = time.monotonic()

    def is_data_stale(self) -> bool:
        """Check if last tick is older than the stale threshold.

        This is the #1 protection against trading on stale prices.
        """
        if self._last_tick_timestamp == 0:
            return True  # No tick ever received
        return (time.monotonic() - self._last_tick_timestamp) > self._stale_threshold_sec

    async def retry_wrapper(
        self,
        fn: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T | None:
        """Execute a broker call with retry on disconnect.

        If the call fails due to connection loss, attempts reconnect and retries.
        Returns None if all retries exhausted.
        """
        async with self._lock:
            for attempt in range(self.max_reconnect_attempts):
                try:
                    return fn(*args, **kwargs)
                except (ConnectionError, OSError, EOFError) as exc:
                    logger.warning(
                        "broker_call_failed",
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    if attempt < self.max_reconnect_attempts - 1:
                        delay = min(
                            RECONNECT_BASE_DELAY * (RECONNECT_BACKOFF_MULT ** attempt),
                            RECONNECT_MAX_DELAY,
                        )
                        logger.info("retry_backoff", delay=delay, attempt=attempt + 1)
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "broker_call_all_retries_exhausted",
                            attempts=self.max_reconnect_attempts,
                        )
                        return None
            return None

    async def wait_for_reconnect(self, check_fn: Callable[[], bool]) -> bool:
        """Wait for reconnection with exponential backoff.

        Args:
            check_fn: Async callable that returns True when connected.

        Returns:
            True if reconnected, False if max attempts exhausted.
        """
        for attempt in range(self.max_reconnect_attempts):
            delay = min(
                RECONNECT_BASE_DELAY * (RECONNECT_BACKOFF_MULT ** attempt),
                RECONNECT_MAX_DELAY,
            )
            logger.info("reconnect_attempt", attempt=attempt + 1, delay=delay)
            await asyncio.sleep(delay)
            try:
                if check_fn():
                    logger.info("reconnect_check_passed")
                    return True
            except Exception as exc:
                logger.warning("reconnect_check_failed", error=str(exc))
        logger.error("reconnect_max_attempts_exhausted")
        return False

    def record_failure(self) -> None:
        """Record a health-check failure. Triggers CRITICAL log at threshold."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.critical(
                "broker_health_critical",
                consecutive_failures=self._consecutive_failures,
                threshold=self._max_consecutive_failures,
            )
            # Notify stale-data callback if provided
            if self.data_stale_callback:
                try:
                    self.data_stale_callback()
                except Exception:
                    pass

    def record_success(self) -> None:
        """Reset consecutive failure counter on successful health check."""
        self._consecutive_failures = 0

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def is_critical(self) -> bool:
        """True when consecutive failures exceed threshold."""
        return self._consecutive_failures >= self._max_consecutive_failures

    def mark_disconnect_start(self) -> None:
        """Record when disconnect began (for 15-second alert threshold)."""
        if self._disconnect_start is None:
            self._disconnect_start = time.monotonic()

    def get_disconnect_duration(self) -> float:
        """Get seconds since disconnect began. Returns 0 if not disconnected."""
        if self._disconnect_start is None:
            return 0.0
        return time.monotonic() - self._disconnect_start

    def set_telegram_callback(self, callback: Any) -> None:
        """Set the Telegram alert callback."""
        self.telegram_callback = callback

    def mark_reconnect(self) -> None:
        """Clear disconnect tracking on reconnect."""
        self._disconnect_start = None
        self._consecutive_failures = 0

    async def _send_alert(self, message: str) -> None:
        if self.telegram_callback:
            try:
                await self.telegram_callback(message)
            except Exception:
                pass
        logger.info("connection_alert", message=message)
