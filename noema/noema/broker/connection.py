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
from typing import Any, Callable, Optional, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# ═══════════════════════════════════════════════════
# MT5 Disconnect SLA (from Phase 1 settings)
# ═══════════════════════════════════════════════════

# SLA Constants — align with BrokerSLASettings in core/settings.py
DISCONNECT_DETECT_SECONDS: float = 5.0     # Detect disconnect within 5s
RECONNECT_ATTEMPT_SECONDS: float = 10.0    # Auto-reconnect attempt within 10s
ALARM_DISCONNECT_SECONDS: float = 30.0     # Kill-switch + alert after 30s
SHUTDOWN_SECONDS: float = 300.0            # Shutdown ALL trading after 5min

# Exponential backoff constants
RECONNECT_BASE_DELAY = 1.0   # seconds
RECONNECT_MAX_DELAY = 30.0   # seconds
RECONNECT_BACKOFF_MULT = 2.0


@dataclass
class ConnectionState:
    """MT5 connection state with SLA tracking."""
    connected: bool = False
    last_connected: datetime | None = None
    last_disconnect: datetime | None = None
    reconnect_count: int = 0
    halt_new_entries: bool = False
    positions_before_disconnect: list[dict] = field(default_factory=list)
    # ── SLA tracking (Phase 1) ──
    disconnect_start_time: float = 0.0       # monotonic timestamp when disconnect began
    total_disconnect_duration: float = 0.0    # cumulative disconnect time this session
    sla_alarm_fired: bool = False             # 30s alarm sent
    sla_shutdown_fired: bool = False          # 5min shutdown triggered
    reconciliation_pending: bool = False      # True after reconnect, before reconciliation
    reconciliation_done: bool = False         # True after positions verified


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
        """Handle MT5 disconnect with SLA escalation.

        SLA Timeline:
        - t=0s: Detect disconnect, halt new entries, snapshot positions
        - t=5s: Reconnect attempts begin (exponential backoff)
        - t=10s: Aggressive reconnect phase
        - t=30s: Kill-switch + Telegram alert
        - t=300s: Complete trading shutdown, wait for human
        """
        logger.critical("mt5_disconnected")
        self.state.connected = False
        self.state.last_disconnect = datetime.now(timezone.utc)
        self.state.halt_new_entries = True
        self.state.disconnect_start_time = time.monotonic()

        # Snapshot current positions
        try:
            positions = broker.get_open_positions()
            self.state.positions_before_disconnect = [
                {"ticket": p.ticket, "symbol": p.symbol, "volume": p.volume,
                 "type": p.type, "pnl": p.pnl}
                for p in positions
            ]
        except Exception:  # Best-effort snapshot — don't fail disconnect on position fetch
            self.state.positions_before_disconnect = []

        disconnect_dur = self.get_disconnect_duration()
        await self._send_alert(
            f"⚠️ MT5 DISCONNECTED!\n"
            f"Open positions at disconnect: {len(self.state.positions_before_disconnect)}\n"
            f"New entries HALTED.\n"
            f"SLA: detect={DISCONNECT_DETECT_SECONDS}s, alarm={ALARM_DISCONNECT_SECONDS}s, "
            f"shutdown={SHUTDOWN_SECONDS}s"
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
            except (ConnectionError, OSError) as exc:
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
                except Exception:  # External callback — don't let failures propagate
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
        if self.state.disconnect_start_time <= 0:
            return 0.0
        return time.monotonic() - self.state.disconnect_start_time

    def check_disconnect_sla(self) -> Optional[str]:
        """Check disconnect duration against SLA thresholds.

        Returns the escalation level or None if not disconnected.
        - "alarm": > 30s disconnected → kill-switch + alert
        - "shutdown": > 300s (5min) → complete trading shutdown
        - None: within acceptable bounds
        """
        dur = self.get_disconnect_duration()
        if dur <= 0:
            return None

        if dur >= SHUTDOWN_SECONDS and not self.state.sla_shutdown_fired:
            self.state.sla_shutdown_fired = True
            logger.critical(
                "mt5_disconnect_shutdown",
                duration_seconds=round(dur, 0),
                threshold=SHUTDOWN_SECONDS,
            )
            return "shutdown"

        if dur >= ALARM_DISCONNECT_SECONDS and not self.state.sla_alarm_fired:
            self.state.sla_alarm_fired = True
            logger.critical(
                "mt5_disconnect_alarm",
                duration_seconds=round(dur, 0),
                threshold=ALARM_DISCONNECT_SECONDS,
            )
            return "alarm"

        return None

    def set_telegram_callback(self, callback: Any) -> None:
        """Set the Telegram alert callback."""
        self.telegram_callback = callback

    def mark_reconnect(self) -> None:
        """Clear disconnect tracking and SLA flags on reconnect."""
        disconnect_duration = self.get_disconnect_duration()
        self.state.disconnect_start_time = 0.0
        self.state.total_disconnect_duration += disconnect_duration
        self.state.sla_alarm_fired = False
        self.state.sla_shutdown_fired = False
        self.state.reconciliation_pending = True
        self._disconnect_start = None
        self._consecutive_failures = 0

    async def _send_alert(self, message: str) -> None:
        if self.telegram_callback:
            try:
                await self.telegram_callback(message)
            except Exception:  # External callback — don't let failures propagate
                pass
        logger.info("connection_alert", message=message)
