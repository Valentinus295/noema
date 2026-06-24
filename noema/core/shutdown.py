"""
Noema Graceful Shutdown — Production-safe process lifecycle management.

Handles SIGTERM/SIGINT with configurable position close-vs-hold policy.
Ensures all background tasks are cancelled, logs/metrics flushed, and
PID files cleaned before process exit.

Architecture:
    signal_handler → ShutdownManager.initiate() → Phase 1 (halt new entries)
    → Phase 2 (close positions or hold) → Phase 3 (stop tasks) → Phase 4 (flush+clean)
    → Phase 5 (exit)

Timing:
    Total budget: 30s (configurable)
    Phase 1: 0.5s — reject new orders immediately
    Phase 2: 10s — close/verify positions
    Phase 3: 10s — cancel async tasks
    Phase 4: 5s  — flush logs, metrics, clean PID
    Phase 5: exit with appropriate code
"""

from __future__ import annotations

import asyncio
import atexit
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════

class ShutdownPositionPolicy(str, Enum):
    """What to do with open positions on shutdown."""
    CLOSE_ALL = "close_all"         # Close all open positions immediately
    CLOSE_LOSING = "close_losing"   # Close only losing positions, leave winners
    HOLD_ALL = "hold_all"           # Do nothing — leave all positions open
    STOP_LIMIT = "stop_limit"       # Place stop-loss/take-profit limits, then hold


@dataclass
class ShutdownConfig:
    """Configuration for graceful shutdown behaviour."""
    policy: ShutdownPositionPolicy = ShutdownPositionPolicy.CLOSE_ALL
    total_timeout_seconds: float = 30.0
    position_close_timeout: float = 10.0
    task_cancel_timeout: float = 10.0
    flush_timeout: float = 5.0
    enable_pid_file: bool = True
    pid_file_path: str = "/tmp/noema.pid"
    halt_new_entries_on_signal: bool = True


# ═══════════════════════════════════════════════════
# Shutdown Manager
# ═══════════════════════════════════════════════════

@dataclass
class ShutdownState:
    """Tracks shutdown progress through phases."""
    initiated: bool = False
    phase: str = "idle"
    started_at: float = 0.0
    completed_at: float = 0.0
    positions_closed: int = 0
    positions_held: int = 0
    tasks_cancelled: int = 0
    tasks_failed: int = 0
    errors: list[str] = field(default_factory=list)
    exit_code: int = 0


class ShutdownManager:
    """Orchestrates graceful shutdown of the Noema system.

    Usage:
        mgr = ShutdownManager(
            orchestrator=orch,
            companion=services,
            broker=broker,
            config=ShutdownConfig(policy=ShutdownPositionPolicy.CLOSE_ALL),
        )

        # Register signal handlers
        mgr.register_signal_handlers()

        # Main loop waits for shutdown signal
        await mgr.wait_for_shutdown()

        # Or manually trigger:
        await mgr.shutdown(reason="manual")
    """

    def __init__(
        self,
        orchestrator: Any = None,
        companion: Any = None,
        broker: Any = None,
        health_checker: Any = None,
        metrics_collector: Any = None,
        redis_cache: Any = None,
        trade_store: Any = None,
        config: ShutdownConfig | None = None,
        extra_cleanup_callbacks: list[Callable[[], Any]] | None = None,
    ):
        self._orch = orchestrator
        self._companion = companion
        self._broker = broker
        self._health_checker = health_checker
        self._metrics_collector = metrics_collector
        self._redis = redis_cache
        self._trade_store = trade_store

        self.config = config or ShutdownConfig()
        self.state = ShutdownState()

        # Event that triggers when shutdown is complete
        self._shutdown_event = asyncio.Event()
        self._halt_new_entries = False
        self._extra_cleanup = extra_cleanup_callbacks or []

        # Write PID file at init
        self._write_pid_file()

    # ── PID File ─────────────────────────────────────────────────────

    def _write_pid_file(self) -> None:
        """Write current PID to the pid file."""
        if not self.config.enable_pid_file:
            return
        try:
            path = Path(self.config.pid_file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(os.getpid()))
            logger.debug("pid_file_written", path=str(path), pid=os.getpid())
        except Exception as e:
            logger.warning("pid_file_write_failed", path=self.config.pid_file_path, error=str(e))

    def _remove_pid_file(self) -> None:
        """Remove the PID file on clean shutdown."""
        if not self.config.enable_pid_file:
            return
        try:
            path = Path(self.config.pid_file_path)
            if path.exists():
                path.unlink()
                logger.debug("pid_file_removed", path=str(path))
        except Exception as e:
            logger.warning("pid_file_remove_failed", path=self.config.pid_file_path, error=str(e))

    # ── Signal Handling ──────────────────────────────────────────────

    def register_signal_handlers(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Register SIGTERM and SIGINT handlers.

        Must be called from the main thread before the event loop starts.

        Args:
            loop: The event loop to schedule shutdown on. If None, uses the running loop.
        """
        target_loop = loop or asyncio.get_event_loop()

        def _handle_signal(sig: int, _frame: Any) -> None:
            signame = signal.Signals(sig).name
            logger.warning("shutdown_signal_received", signal=signame, pid=os.getpid())
            # Schedule the async shutdown on the event loop
            asyncio.ensure_future(self.shutdown(reason=signame), loop=target_loop)

        try:
            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)
            logger.info("shutdown_signals_registered", signals=["SIGTERM", "SIGINT"])
        except Exception as e:
            logger.error("shutdown_signal_registration_failed", error=str(e))

    # ── Wait for Shutdown ────────────────────────────────────────────

    async def wait_for_shutdown(self) -> int:
        """Block until shutdown completes. Returns exit code."""
        await self._shutdown_event.wait()
        return self.state.exit_code

    # ── Shutdown Procedure ───────────────────────────────────────────

    async def shutdown(self, reason: str = "unknown") -> int:
        """Execute the full graceful shutdown sequence.

        Phases:
            1. Halt new entries (reject all new orders immediately)
            2. Handle open positions per policy
            3. Cancel all background tasks
            4. Flush logs, metrics, close connections
            5. Clean up PID files, run extra callbacks, exit

        Returns exit code (0 = clean, 1 = errors during shutdown).
        """
        if self.state.initiated:
            logger.warning("shutdown_already_in_progress", phase=self.state.phase)
            return self.state.exit_code

        self.state.initiated = True
        self.state.started_at = time.monotonic()
        logger.warning("noema_shutdown_initiated", reason=reason, pid=os.getpid())

        # ── Phase 1: Halt new entries ───────────────────────────────
        self.state.phase = "halt_entries"
        await self._phase_halt_new_entries()

        # ── Phase 2: Handle open positions ──────────────────────────
        self.state.phase = "handle_positions"
        await self._phase_handle_positions()

        # ── Phase 3: Cancel background tasks ────────────────────────
        self.state.phase = "cancel_tasks"
        await self._phase_cancel_tasks()

        # ── Phase 4: Flush and clean connections ────────────────────
        self.state.phase = "flush_clean"
        await self._phase_flush_and_clean()

        # ── Phase 5: Final cleanup ──────────────────────────────────
        self.state.phase = "final_cleanup"
        self._phase_final_cleanup()

        self.state.completed_at = time.monotonic()
        duration = self.state.completed_at - self.state.started_at
        self.state.exit_code = 1 if self.state.errors else 0

        logger.warning(
            "noema_shutdown_complete",
            duration_seconds=round(duration, 2),
            exit_code=self.state.exit_code,
            positions_closed=self.state.positions_closed,
            positions_held=self.state.positions_held,
            tasks_cancelled=self.state.tasks_cancelled,
            errors=len(self.state.errors),
        )

        self._shutdown_event.set()
        return self.state.exit_code

    # ── Phase Implementations ────────────────────────────────────────

    async def _phase_halt_new_entries(self) -> None:
        """Immediately reject all new order requests."""
        self._halt_new_entries = True
        logger.info("shutdown_phase1_halt_entries", halted=True)

        # Notify the orchestrator to stop accepting new cycles
        if self._orch:
            try:
                self._orch._running = False
                logger.info("orchestrator_loops_halted")
            except Exception as e:
                self.state.errors.append(f"halt_orchestrator: {e}")
                logger.error("halt_orchestrator_failed", error=str(e))

    async def _phase_handle_positions(self) -> None:
        """Handle open positions according to the configured policy.

        Uses a timeout to prevent hanging on broker operations.
        """
        policy = self.config.policy

        if policy == ShutdownPositionPolicy.HOLD_ALL:
            logger.info("shutdown_phase2_holding_all_positions")
            return

        if self._broker is None:
            logger.info("shutdown_phase2_no_broker", skipped=True)
            return

        try:
            positions = await asyncio.wait_for(
                self._get_open_positions(),
                timeout=self.config.position_close_timeout * 0.3,
            )
        except asyncio.TimeoutError:
            logger.error("shutdown_phase2_get_positions_timeout")
            self.state.errors.append("get_positions_timeout")
            return
        except Exception as e:
            logger.error("shutdown_phase2_get_positions_failed", error=str(e))
            self.state.errors.append(f"get_positions: {e}")
            return

        if not positions:
            logger.info("shutdown_phase2_no_open_positions")
            return

        logger.warning(
            "shutdown_phase2_open_positions",
            count=len(positions),
            positions=[p.get("symbol", "?") for p in positions],
            policy=policy.value,
        )

        positions_to_close = []
        positions_to_hold = []

        for pos in positions:
            if policy == ShutdownPositionPolicy.CLOSE_ALL:
                positions_to_close.append(pos)
            elif policy == ShutdownPositionPolicy.CLOSE_LOSING:
                pnl = pos.get("profit", 0.0)
                if pnl < 0:
                    positions_to_close.append(pos)
                else:
                    positions_to_hold.append(pos)
            elif policy == ShutdownPositionPolicy.STOP_LIMIT:
                # Place protective orders — hold position with limits
                positions_to_hold.append(pos)

        # Close positions that need closing
        for pos in positions_to_close:
            try:
                await asyncio.wait_for(
                    self._close_position(pos),
                    timeout=self.config.position_close_timeout / max(len(positions_to_close), 1),
                )
                self.state.positions_closed += 1
                logger.info(
                    "shutdown_position_closed",
                    symbol=pos.get("symbol", "?"),
                    ticket=pos.get("ticket", "?"),
                )
            except asyncio.TimeoutError:
                logger.error(
                    "shutdown_position_close_timeout",
                    symbol=pos.get("symbol", "?"),
                    ticket=pos.get("ticket", "?"),
                )
                self.state.errors.append(f"close_timeout: {pos.get('symbol', '?')}")
            except Exception as e:
                logger.error(
                    "shutdown_position_close_failed",
                    symbol=pos.get("symbol", "?"),
                    error=str(e),
                )
                self.state.errors.append(f"close: {pos.get('symbol', '?')}: {e}")

        self.state.positions_held = len(positions_to_hold)

        if policy == ShutdownPositionPolicy.STOP_LIMIT and positions_to_hold:
            await self._place_protective_orders(positions_to_hold)

    async def _get_open_positions(self) -> list[dict]:
        """Get list of open positions from the broker."""
        broker = self._broker
        if hasattr(broker, "get_positions"):
            if asyncio.iscoroutinefunction(broker.get_positions):
                return await broker.get_positions()
            else:
                return broker.get_positions()
        if hasattr(broker, "positions"):
            return broker.positions
        return []

    async def _close_position(self, position: dict) -> None:
        """Close a single position via the broker."""
        broker = self._broker
        symbol = position.get("symbol", "")
        ticket = position.get("ticket", 0)
        volume = position.get("volume", 0.01)
        direction = position.get("type", 0)  # 0=BUY, 1=SELL

        if hasattr(broker, "close_position"):
            if asyncio.iscoroutinefunction(broker.close_position):
                await broker.close_position(ticket=ticket, symbol=symbol, volume=volume)
            else:
                broker.close_position(ticket=ticket, symbol=symbol, volume=volume)
        elif hasattr(broker, "close"):
            if asyncio.iscoroutinefunction(broker.close):
                await broker.close(symbol=symbol, ticket=ticket)
            else:
                broker.close(symbol=symbol, ticket=ticket)
        else:
            logger.error("shutdown_no_close_method", broker_type=type(broker).__name__)

    async def _place_protective_orders(self, positions: list[dict]) -> None:
        """Place SL/TP orders on held positions."""
        if not hasattr(self._broker, "modify_position"):
            logger.warning("shutdown_cannot_place_protective_orders", reason="broker missing modify_position")
            return
        for pos in positions:
            try:
                await self._broker.modify_position(
                    ticket=pos.get("ticket", 0),
                    sl=pos.get("sl", 0),
                    tp=pos.get("tp", 0),
                )
            except Exception as e:
                logger.error(
                    "shutdown_protective_order_failed",
                    symbol=pos.get("symbol", "?"),
                    error=str(e),
                )

    async def _phase_cancel_tasks(self) -> None:
        """Cancel all background asyncio tasks gracefully."""
        logger.info("shutdown_phase3_cancelling_tasks")

        tasks_to_cancel: list[asyncio.Task] = []

        # Stop orchestrator internal tasks
        if self._orch and hasattr(self._orch, "_tasks"):
            tasks_to_cancel.extend(self._orch._tasks)

        # Stop companion services (Telegram, reflector, journal)
        if self._companion:
            try:
                await asyncio.wait_for(
                    self._companion.stop(),
                    timeout=self.config.task_cancel_timeout * 0.3,
                )
            except asyncio.TimeoutError:
                self.state.errors.append("companion_stop_timeout")
            except Exception as e:
                self.state.errors.append(f"companion_stop: {e}")

        # Cancel all tracked tasks
        for task in tasks_to_cancel:
            if not task.done():
                task.cancel()
                self.state.tasks_cancelled += 1

        # Wait for tasks to finish cancellation
        if tasks_to_cancel:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                    timeout=self.config.task_cancel_timeout * 0.6,
                )
            except asyncio.TimeoutError:
                self.state.tasks_failed = len([t for t in tasks_to_cancel if not t.done()])
                logger.error(
                    "shutdown_tasks_cancel_timeout",
                    pending=self.state.tasks_failed,
                )
                self.state.errors.append("task_cancel_timeout")

        # Clear task list
        if self._orch and hasattr(self._orch, "_tasks"):
            self._orch._tasks.clear()

        logger.info(
            "shutdown_phase3_tasks_cancelled",
            cancelled=self.state.tasks_cancelled,
            failed=self.state.tasks_failed,
        )

    async def _phase_flush_and_clean(self) -> None:
        """Flush logs, metrics, and close connections."""
        logger.info("shutdown_phase4_flushing")

        # ── Flush NIM client (LLM API) ─────
        if self._orch and hasattr(self._orch, "nim"):
            try:
                await asyncio.wait_for(
                    self._orch.nim.close(),
                    timeout=5.0,
                )
            except Exception as e:
                logger.warning("shutdown_nim_close_failed", error=str(e))

        # ── Close Redis ──────────────────
        if self._redis:
            try:
                await asyncio.wait_for(
                    self._redis.close(),
                    timeout=3.0,
                )
                logger.info("shutdown_redis_closed")
            except Exception as e:
                logger.warning("shutdown_redis_close_failed", error=str(e))

        # ── Close TradeStore (PostgreSQL) ──
        if self._trade_store:
            try:
                await asyncio.wait_for(
                    self._trade_store.close(),
                    timeout=3.0,
                )
                logger.info("shutdown_tradestore_closed")
            except Exception as e:
                logger.warning("shutdown_tradestore_close_failed", error=str(e))

        # ── Close broker connection ──────
        if self._broker and hasattr(self._broker, "disconnect"):
            try:
                fn = self._broker.disconnect
                if asyncio.iscoroutinefunction(fn):
                    await asyncio.wait_for(fn(), timeout=5.0)
                else:
                    fn()
                logger.info("shutdown_broker_disconnected")
            except Exception as e:
                logger.warning("shutdown_broker_disconnect_failed", error=str(e))

        # ── Final metrics flush ──────────
        if self._health_checker:
            try:
                health = self._health_checker.collect()
                logger.info(
                    "shutdown_final_health_snapshot",
                    status=health.overall_status.value,
                    agents=len(health.agents),
                )
            except Exception as e:
                logger.warning("shutdown_health_snapshot_failed", error=str(e))

        # ── Flush structlog ──────────────
        try:
            import structlog
            structlog.reset_defaults()
        except Exception:
            pass

        logger.info("shutdown_phase4_flush_complete")

    def _phase_final_cleanup(self) -> None:
        """Remove PID file, run extra callbacks, prepare for exit."""
        # Remove PID file
        self._remove_pid_file()

        # Run extra cleanup callbacks
        for callback in self._extra_cleanup:
            try:
                callback()
            except Exception as e:
                self.state.errors.append(f"cleanup_callback: {e}")
                logger.error("shutdown_cleanup_callback_failed", error=str(e))

        logger.info("shutdown_phase5_final_cleanup_complete")

    # ── Convenience: Exit Application ────────────────────────────────

    def exit(self, exit_code: int | None = None) -> None:
        """Exit the process with the appropriate exit code.

        Call this after `await mgr.shutdown()` completes.

        Args:
            exit_code: Override exit code. Defaults to self.state.exit_code.
        """
        code = exit_code if exit_code is not None else self.state.exit_code
        # Ensure any buffered stderr/stdout is flushed
        sys.stdout.flush()
        sys.stderr.flush()
        # Register atexit handler as safety net
        atexit.register(self._remove_pid_file)
        sys.exit(code)

    # ── Manual Override ──────────────────────────────────────────────

    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self.state.initiated

    @property
    def new_entries_halted(self) -> bool:
        """Check if new trade entries are being rejected."""
        return self._halt_new_entries

    def halt_new_entries(self) -> None:
        """Manually halt new entries (for external triggers like kill-switch)."""
        self._halt_new_entries = True
        logger.warning("new_entries_halted_manually")


# ═══════════════════════════════════════════════════
# Factory: Create ShutdownConfig from environment
# ═══════════════════════════════════════════════════

def load_shutdown_config_from_env() -> ShutdownConfig:
    """Build shutdown configuration from environment variables.

    Environment Variables:
        NOEMA_SHUTDOWN_POLICY: "close_all" | "close_losing" | "hold_all" | "stop_limit"
        NOEMA_SHUTDOWN_TIMEOUT: Total shutdown budget in seconds (default 30)
        NOEMA_PID_FILE: Path to PID file (default /tmp/noema.pid)
        NOEMA_PID_FILE_ENABLED: Set to "false" to disable PID file
    """
    policy_map = {
        "close_all": ShutdownPositionPolicy.CLOSE_ALL,
        "close_losing": ShutdownPositionPolicy.CLOSE_LOSING,
        "hold_all": ShutdownPositionPolicy.HOLD_ALL,
        "stop_limit": ShutdownPositionPolicy.STOP_LIMIT,
    }
    policy = policy_map.get(
        os.getenv("NOEMA_SHUTDOWN_POLICY", "close_all").lower(),
        ShutdownPositionPolicy.CLOSE_ALL,
    )
    total_timeout = float(os.getenv("NOEMA_SHUTDOWN_TIMEOUT", "30"))

    return ShutdownConfig(
        policy=policy,
        total_timeout_seconds=total_timeout,
        position_close_timeout=total_timeout * 0.35,
        task_cancel_timeout=total_timeout * 0.35,
        flush_timeout=total_timeout * 0.2,
        enable_pid_file=os.getenv("NOEMA_PID_FILE_ENABLED", "true").lower() != "false",
        pid_file_path=os.getenv("NOEMA_PID_FILE", "/tmp/noema.pid"),
    )
