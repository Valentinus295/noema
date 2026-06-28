"""Tests for the NOEMA Loop Architecture.

Covers:
- Loop state transitions (IDLE → RUNNING → PAUSED → RUNNING → HALTED)
- Loop health tracking (tick count, error rate, timing)
- Loop priority ordering
- Loop pause/resume
- LoopManager lifecycle
- LoopLedger dashboard data
- Consecutive error auto-halt
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from noema.core.loop import TradingLoop, LoopState, LoopHealth
from noema.core.loop_manager import LoopManager
from noema.core.loop_ledger import LoopLedger


# ===========================================================================
# Helpers
# ===========================================================================


class _StubLoop(TradingLoop):
    """A minimal loop for testing. Tick counter increments on each call."""

    def __init__(self, name: str = "test", cadence: float = 0.01, priority: int = 5):
        super().__init__(name=name, cadence_seconds=cadence, priority=priority)
        self.tick_count = 0
        self._fail_until_tick: int | None = None

    async def tick(self) -> None:
        self.tick_count += 1
        if self._fail_until_tick and self.tick_count <= self._fail_until_tick:
            raise RuntimeError(f"Simulated failure at tick {self.tick_count}")


class _FailingLoop(TradingLoop):
    """A loop that always raises on tick()."""

    def __init__(self, name: str = "failing", max_consecutive: int = 3):
        super().__init__(
            name=name, cadence_seconds=0.01, priority=5,
            max_consecutive_errors=max_consecutive,
        )

    async def tick(self) -> None:
        raise RuntimeError("Always fails")


# ===========================================================================
# TradingLoop — State Transitions
# ===========================================================================


class TestLoopStateTransitions:
    """Test loop lifecycle state machine."""

    @pytest.mark.asyncio
    async def test_initial_state_is_idle(self):
        loop = _StubLoop()
        assert loop.health.state == LoopState.IDLE

    @pytest.mark.asyncio
    async def test_start_transitions_to_running(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.02)
        assert loop.health.state == LoopState.RUNNING
        loop.stop()
        await task

    @pytest.mark.asyncio
    async def test_pause_transitions_to_paused(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.02)
        loop.pause()
        assert loop.health.state == LoopState.PAUSED
        assert loop.is_paused
        loop.stop()
        await task

    @pytest.mark.asyncio
    async def test_resume_transitions_back_to_running(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.02)
        loop.pause()
        assert loop.health.state == LoopState.PAUSED
        loop.resume()
        assert loop.health.state == LoopState.RUNNING
        assert loop.is_running
        loop.stop()
        await task

    @pytest.mark.asyncio
    async def test_stop_transitions_to_halted(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.02)
        loop.stop()
        await task
        assert loop.health.state == LoopState.HALTED

    @pytest.mark.asyncio
    async def test_consecutive_errors_transitions_to_errored(self):
        loop = _FailingLoop(max_consecutive=3)
        task = asyncio.create_task(loop.start())
        await task
        assert loop.health.state == LoopState.ERRORED
        assert loop.health.consecutive_errors >= 3


# ===========================================================================
# TradingLoop — Health Tracking
# ===========================================================================


class TestLoopHealthTracking:
    """Test that health metrics are updated correctly."""

    @pytest.mark.asyncio
    async def test_tick_count_increments(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.08)  # Should complete ~5-8 ticks
        loop.stop()
        await task
        assert loop.health.tick_count >= 3

    @pytest.mark.asyncio
    async def test_error_count_tracks_failures(self):
        loop = _StubLoop(cadence=0.01)
        loop._fail_until_tick = 2  # Fail first 2 ticks, then succeed
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.15)
        loop.stop()
        await task
        assert loop.health.error_count >= 2
        assert loop.health.last_error is not None

    @pytest.mark.asyncio
    async def test_consecutive_errors_reset_on_success(self):
        loop = _StubLoop(cadence=0.01)
        loop._fail_until_tick = 2
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.15)
        loop.stop()
        await task
        # After succeeding, consecutive should be 0
        assert loop.health.consecutive_errors == 0

    @pytest.mark.asyncio
    async def test_avg_tick_ms_is_positive(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.08)
        loop.stop()
        await task
        assert loop.health.avg_tick_ms >= 0

    @pytest.mark.asyncio
    async def test_health_to_dict(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.05)
        loop.stop()
        await task
        d = loop.health.to_dict()
        assert "state" in d
        assert "tick_count" in d
        assert "error_count" in d
        assert "avg_tick_ms" in d
        assert "drift_ms" in d
        assert "uptime_seconds" in d


# ===========================================================================
# TradingLoop — Pause/Resume Behavior
# ===========================================================================


class TestLoopPauseResume:
    """Test that pause actually stops ticking and resume restarts it."""

    @pytest.mark.asyncio
    async def test_pause_stops_ticking(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.05)
        count_before_pause = loop.tick_count
        loop.pause()
        await asyncio.sleep(0.08)  # Wait while paused
        count_after_pause = loop.tick_count
        # Tick count should not have changed during pause
        assert count_after_pause == count_before_pause
        loop.stop()
        await task

    @pytest.mark.asyncio
    async def test_resume_restarts_ticking(self):
        loop = _StubLoop(cadence=0.01)
        task = asyncio.create_task(loop.start())
        await asyncio.sleep(0.05)
        loop.pause()
        await asyncio.sleep(0.05)
        count_after_pause = loop.tick_count
        loop.resume()
        await asyncio.sleep(0.08)
        count_after_resume = loop.tick_count
        assert count_after_resume > count_after_pause
        loop.stop()
        await task


# ===========================================================================
# LoopManager — Lifecycle
# ===========================================================================


class TestLoopManagerLifecycle:
    """Test LoopManager registration, start, stop."""

    @pytest.mark.asyncio
    async def test_register_and_start_all(self):
        manager = LoopManager()
        loop1 = _StubLoop(name="loop1", cadence=0.01, priority=5)
        loop2 = _StubLoop(name="loop2", cadence=0.01, priority=3)
        manager.register(loop1)
        manager.register(loop2)
        assert "loop1" in manager.loops
        assert "loop2" in manager.loops

        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.08)
        manager.stop_all()
        await task

        assert loop1.health.state == LoopState.HALTED
        assert loop2.health.state == LoopState.HALTED

    @pytest.mark.asyncio
    async def test_duplicate_registration_raises(self):
        manager = LoopManager()
        loop = _StubLoop(name="dup")
        manager.register(loop)
        with pytest.raises(ValueError, match="already registered"):
            manager.register(loop)

    @pytest.mark.asyncio
    async def test_unregister(self):
        manager = LoopManager()
        loop = _StubLoop(name="removable")
        manager.register(loop)
        assert "removable" in manager.loops
        manager.unregister("removable")
        assert "removable" not in manager.loops

    @pytest.mark.asyncio
    async def test_get_loop(self):
        manager = LoopManager()
        loop = _StubLoop(name="findme")
        manager.register(loop)
        assert manager.get_loop("findme") is loop
        assert manager.get_loop("nope") is None

    @pytest.mark.asyncio
    async def test_health_report(self):
        manager = LoopManager()
        loop = _StubLoop(name="h1", cadence=0.01)
        manager.register(loop)
        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.05)
        manager.stop_all()
        await task

        report = manager.health_report()
        assert "h1" in report
        assert report["h1"]["state"] == "halted"

    @pytest.mark.asyncio
    async def test_is_running_property(self):
        manager = LoopManager()
        assert not manager.is_running
        loop = _StubLoop(name="r1", cadence=0.01)
        manager.register(loop)
        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.02)
        assert manager.is_running
        manager.stop_all()
        await task
        assert not manager.is_running


# ===========================================================================
# LoopManager — Priority Ordering
# ===========================================================================


class TestLoopManagerPriority:
    """Test priority-based operations."""

    @pytest.mark.asyncio
    async def test_pause_lower_priority(self):
        manager = LoopManager()
        safety = _StubLoop(name="safety", priority=0, cadence=0.01)
        trading = _StubLoop(name="trading", priority=1, cadence=0.01)
        learning = _StubLoop(name="learning", priority=2, cadence=0.01)
        manager.register(safety)
        manager.register(trading)
        manager.register(learning)

        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.05)

        # Pause everything with priority > 0
        manager.pause_lower_priority(0)
        assert safety.is_running
        assert trading.is_paused
        assert learning.is_paused

        manager.stop_all()
        await task

    @pytest.mark.asyncio
    async def test_resume_all(self):
        manager = LoopManager()
        loop1 = _StubLoop(name="l1", priority=1, cadence=0.01)
        loop2 = _StubLoop(name="l2", priority=2, cadence=0.01)
        manager.register(loop1)
        manager.register(loop2)

        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.05)
        manager.pause_lower_priority(0)
        assert loop1.is_paused
        assert loop2.is_paused
        manager.resume_all()
        assert loop1.is_running
        assert loop2.is_running
        manager.stop_all()
        await task

    @pytest.mark.asyncio
    async def test_pause_resume_specific_loop(self):
        manager = LoopManager()
        loop = _StubLoop(name="target", cadence=0.01)
        manager.register(loop)
        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.05)
        manager.pause_loop("target")
        assert loop.is_paused
        manager.resume_loop("target")
        assert loop.is_running
        manager.stop_all()
        await task

    @pytest.mark.asyncio
    async def test_get_unhealthy_loops(self):
        manager = LoopManager()
        healthy = _StubLoop(name="healthy", cadence=0.01)
        broken = _FailingLoop(name="broken", max_consecutive=2)
        manager.register(healthy)
        manager.register(broken)

        task = asyncio.create_task(manager.start_all())
        await task

        unhealthy = manager.get_unhealthy_loops()
        assert "broken" in unhealthy
        assert "healthy" not in unhealthy


# ===========================================================================
# LoopLedger
# ===========================================================================


class TestLoopLedger:
    """Test LoopLedger dashboard data generation."""

    @pytest.mark.asyncio
    async def test_dashboard_data_structure(self):
        manager = LoopManager()
        loop = _StubLoop(name="test_loop", cadence=0.01)
        manager.register(loop)
        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.05)
        manager.stop_all()
        await task

        ledger = LoopLedger(manager)
        data = ledger.get_dashboard_data()

        assert "loops" in data
        assert "summary" in data
        assert "timestamp" in data
        assert "test_loop" in data["loops"]

        loop_data = data["loops"]["test_loop"]
        assert "state" in loop_data
        assert "tick_count" in loop_data
        assert "error_count" in loop_data
        assert "avg_tick_ms" in loop_data

    @pytest.mark.asyncio
    async def test_summary_counts(self):
        manager = LoopManager()
        loop1 = _StubLoop(name="l1", cadence=0.01, priority=1)
        loop2 = _StubLoop(name="l2", cadence=0.01, priority=2)
        manager.register(loop1)
        manager.register(loop2)
        task = asyncio.create_task(manager.start_all())
        await asyncio.sleep(0.05)
        manager.stop_all()
        await task

        ledger = LoopLedger(manager)
        data = ledger.get_dashboard_data()
        summary = data["summary"]

        assert summary["total_loops"] == 2
        assert summary["halted"] == 2
        assert summary["running"] == 0
        assert summary["overall_health"] == "healthy"

    @pytest.mark.asyncio
    async def test_overall_health_degraded_on_error(self):
        manager = LoopManager()
        broken = _FailingLoop(name="broken", max_consecutive=2)
        manager.register(broken)
        task = asyncio.create_task(manager.start_all())
        await task

        ledger = LoopLedger(manager)
        data = ledger.get_dashboard_data()
        assert data["summary"]["overall_health"] == "degraded"


# ===========================================================================
# LoopHealth Dataclass
# ===========================================================================


class TestLoopHealthDataclass:
    """Test LoopHealth serialization."""

    def test_to_dict_default(self):
        health = LoopHealth()
        d = health.to_dict()
        assert d["state"] == "idle"
        assert d["tick_count"] == 0
        assert d["error_count"] == 0

    def test_to_dict_with_values(self):
        health = LoopHealth(
            state=LoopState.RUNNING,
            tick_count=42,
            error_count=3,
            avg_tick_ms=12.5,
        )
        d = health.to_dict()
        assert d["state"] == "running"
        assert d["tick_count"] == 42
        assert d["error_count"] == 3
        assert d["avg_tick_ms"] == 12.5
