"""Loop Manager — Manages all NOEMA loops.

Provides:
- Loop registration and lifecycle
- Priority-based scheduling
- Conflict resolution (higher priority loop can pause lower)
- Graceful shutdown (reverse priority order — highest priority stops last)
- Integration with LoopLedger for monitoring

Design reference: research-loop-systems.md §3.6, §4.6
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from noema.core.loop import TradingLoop, LoopState

logger = structlog.get_logger(__name__)


class LoopManager:
    """Manages all NOEMA trading loops.

    Usage::

        manager = LoopManager()
        manager.register(safety_loop)
        manager.register(trading_loop)
        manager.register(learning_loop)
        await manager.start_all()
    """

    def __init__(self) -> None:
        self.loops: dict[str, TradingLoop] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    # ── Registration ────────────────────────────────────────────────

    def register(self, loop: TradingLoop) -> None:
        """Register a loop for management.

        Raises ValueError if a loop with the same name is already registered.
        """
        if loop.name in self.loops:
            raise ValueError(f"Loop '{loop.name}' is already registered")
        self.loops[loop.name] = loop
        logger.info("loop_registered", name=loop.name, priority=loop.priority)

    def unregister(self, name: str) -> None:
        """Unregister a loop by name."""
        if name in self.loops:
            self.loops[name].stop()
            self.loops.pop(name)
            logger.info("loop_unregistered", name=name)

    def get_loop(self, name: str) -> Optional[TradingLoop]:
        """Get a registered loop by name."""
        return self.loops.get(name)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start all registered loops as concurrent asyncio tasks.

        Loops are started in reverse priority order (lowest priority first)
        so that high-priority loops can immediately begin monitoring.
        """
        self._running = True
        sorted_loops = sorted(
            self.loops.values(), key=lambda l: l.priority, reverse=True
        )
        for loop in sorted_loops:
            task = asyncio.create_task(
                loop.start(), name=f"loop:{loop.name}"
            )
            self._tasks[loop.name] = task

        logger.info(
            "loop_manager_started",
            loop_count=len(self.loops),
            loops={n: l.priority for n, l in self.loops.items()},
        )

        # Wait for all tasks (they run indefinitely until stopped)
        results = await asyncio.gather(
            *self._tasks.values(), return_exceptions=True
        )

        # Log any unexpected exceptions
        for task, result in zip(self._tasks.values(), results):
            if isinstance(result, Exception):
                logger.error(
                    "loop_task_exception",
                    task=task.get_name(),
                    error=str(result),
                )

    def stop_all(self) -> None:
        """Stop all loops in priority order (highest priority stops last).

        This ensures safety loops keep running while other loops wind down.
        """
        sorted_loops = sorted(self.loops.values(), key=lambda l: l.priority)
        for loop in sorted_loops:
            loop.stop()
        self._running = False
        logger.info("loop_manager_stopped", loop_count=len(self.loops))

    # ── Conflict Resolution ─────────────────────────────────────────

    def pause_lower_priority(self, min_priority: int) -> None:
        """Pause all loops with priority > min_priority.

        Used by safety loops to freeze lower-priority operations
        during emergency conditions.
        """
        for loop in self.loops.values():
            if loop.priority > min_priority and loop.is_running:
                loop.pause()
                logger.info(
                    "loop_paused_by_priority",
                    name=loop.name,
                    priority=loop.priority,
                    min_priority=min_priority,
                )

    def resume_all(self) -> None:
        """Resume all paused loops."""
        for loop in self.loops.values():
            if loop.is_paused:
                loop.resume()

    def pause_loop(self, name: str) -> None:
        """Pause a specific loop by name."""
        loop = self.loops.get(name)
        if loop:
            loop.pause()

    def resume_loop(self, name: str) -> None:
        """Resume a specific loop by name."""
        loop = self.loops.get(name)
        if loop:
            loop.resume()

    # ── Health ──────────────────────────────────────────────────────

    def health_report(self) -> dict[str, Any]:
        """Return health status of all loops."""
        return {
            name: loop.health.to_dict()
            for name, loop in self.loops.items()
        }

    @property
    def is_running(self) -> bool:
        return self._running

    def get_unhealthy_loops(self) -> list[str]:
        """Return names of loops in ERRORED or HALTED state."""
        return [
            name
            for name, loop in self.loops.items()
            if loop.health.state in (LoopState.ERRORED, LoopState.HALTED)
        ]
