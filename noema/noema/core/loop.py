"""Loop Architecture — Base TradingLoop class for NOEMA.

Every NOEMA loop inherits from TradingLoop, which provides:
- State management (IDLE/RUNNING/PAUSED/ERRORED/HALTED)
- Health tracking (tick count, error rate, timing, drift)
- Graceful shutdown via asyncio.Event
- Priority-based interruption (0=highest/safety, 10=lowest)
- Structured logging via structlog
- Consecutive error detection with auto-halt

Design reference: research-loop-systems.md §1.3, §3.2
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import structlog


class LoopState(Enum):
    """Lifecycle states for a trading loop."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERRORED = "errored"
    HALTED = "halted"


@dataclass
class LoopHealth:
    """Mutable health snapshot for a single loop.

    Updated every tick by TradingLoop.start(). Consumed by LoopLedger
    for dashboard / Prometheus export.
    """

    state: LoopState = LoopState.IDLE
    last_tick: float = 0.0
    tick_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    last_error: Optional[str] = None
    avg_tick_ms: float = 0.0
    drift_ms: float = 0.0  # How far off from target cadence
    started_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / dashboard consumption."""
        return {
            "state": self.state.value,
            "last_tick": self.last_tick,
            "tick_count": self.tick_count,
            "error_count": self.error_count,
            "consecutive_errors": self.consecutive_errors,
            "last_error": self.last_error,
            "avg_tick_ms": round(self.avg_tick_ms, 2),
            "drift_ms": round(self.drift_ms, 2),
            "uptime_seconds": round(time.time() - self.started_at, 1) if self.started_at else 0,
        }


class TradingLoop:
    """Base class for all NOEMA loops.

    Subclasses override ``tick()`` with their per-iteration logic.
    The base class handles cadence timing, health tracking, pause/resume,
    and graceful shutdown.

    Parameters
    ----------
    name : str
        Human-readable loop name (e.g. "safety", "trading").
    cadence_seconds : float
        Target interval between ticks. The loop sleeps for the
        remainder after each tick completes.
    priority : int
        0 = highest (safety), 10 = lowest. Used by LoopManager
        for conflict resolution and shutdown ordering.
    max_consecutive_errors : int
        Auto-halt after this many consecutive tick failures.
    """

    def __init__(
        self,
        name: str,
        cadence_seconds: float,
        priority: int = 5,
        max_consecutive_errors: int = 5,
    ):
        self.name = name
        self.cadence = cadence_seconds
        self.priority = priority
        self.max_consecutive_errors = max_consecutive_errors
        self.health = LoopHealth()
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused by default
        self.logger = structlog.get_logger().bind(loop=name)

    # ── Main Loop Runner ────────────────────────────────────────────

    async def start(self) -> None:
        """Main loop runner. Call via ``asyncio.create_task``.

        Runs ``tick()`` at the configured cadence until stopped.
        Respects pause/resume and halts on consecutive errors.
        """
        self.health.state = LoopState.RUNNING
        self.health.started_at = time.time()
        self.logger.info(
            "loop_started",
            cadence=self.cadence,
            priority=self.priority,
        )

        while not self._stop_event.is_set():
            # Block while paused
            await self._pause_event.wait()
            if self._stop_event.is_set():
                break

            tick_start = time.monotonic()
            try:
                await self.tick()
                self.health.tick_count += 1
                self.health.consecutive_errors = 0  # Reset on success
            except Exception as e:
                self.health.error_count += 1
                self.health.consecutive_errors += 1
                self.health.last_error = str(e)
                self.logger.error(
                    "loop_tick_error",
                    error=str(e),
                    tick=self.health.tick_count,
                    consecutive=self.health.consecutive_errors,
                )
                if self.health.consecutive_errors >= self.max_consecutive_errors:
                    self.health.state = LoopState.ERRORED
                    self.logger.critical(
                        "loop_errored",
                        consecutive_errors=self.health.consecutive_errors,
                    )
                    break

            # Update timing metrics (EMA)
            tick_ms = (time.monotonic() - tick_start) * 1000
            self.health.avg_tick_ms = (self.health.avg_tick_ms * 0.9) + (tick_ms * 0.1)
            self.health.last_tick = time.time()

            # Calculate drift (actual interval vs target cadence)
            self.health.drift_ms = max(0, tick_ms - (self.cadence * 1000))

            # Sleep for remaining cadence
            elapsed = time.monotonic() - tick_start
            sleep_time = max(0, self.cadence - elapsed)
            if sleep_time > 0:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=sleep_time
                    )
                    break  # Stop event was set during sleep
                except asyncio.TimeoutError:
                    pass  # Normal — timeout means keep running

    # ── Override Point ───────────────────────────────────────────────

    async def tick(self) -> None:
        """Called once per loop iteration. Subclasses must override.

        Raise an exception to signal a failed tick. The base class
        tracks consecutive failures and auto-halts after
        ``max_consecutive_errors``.
        """
        raise NotImplementedError(
            f"Loop '{self.name}' must implement tick()"
        )

    # ── Lifecycle Controls ───────────────────────────────────────────

    def pause(self) -> None:
        """Pause this loop. ``tick()`` will not be called until resume."""
        self._pause_event.clear()
        self.health.state = LoopState.PAUSED
        self.logger.info("loop_paused")

    def resume(self) -> None:
        """Resume a paused loop."""
        self._pause_event.set()
        self.health.state = LoopState.RUNNING
        self.logger.info("loop_resumed")

    def stop(self) -> None:
        """Signal the loop to stop after the current tick.

        Also unblocks a paused loop so it can exit cleanly.
        """
        self._stop_event.set()
        self._pause_event.set()  # Unblock if paused so stop_event is seen
        self.health.state = LoopState.HALTED
        self.logger.info("loop_stopped")

    @property
    def is_running(self) -> bool:
        return self.health.state == LoopState.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.health.state == LoopState.PAUSED
