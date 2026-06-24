"""Working Memory — Redis-backed live trading state.

Holds the system's immediate awareness:
- Current market state per symbol (price, spread, trend, regime)
- Active positions with full context
- Current setups being evaluated
- Debate state (active agents, consensus)
- Guardian kill-switch status
- Learning freeze state

TTL-based expiry prevents stale data accumulation.
Uses the existing RedisCache (noema/core/storage.py) for Redis access.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from noema.core.storage import RedisCache

logger = structlog.get_logger(__name__)

# TTL constants (seconds)
DEFAULT_TTL = 300        # 5 min for market snapshots
POSITION_TTL = 3600      # 1 hour for position state
SETUP_TTL = 300          # 5 min for setups
GUARDIAN_TTL = 60        # 1 min for guardian status
LEARNING_TTL = 3600      # 1 hour for learning state


@dataclass
class MarketSnapshot:
    """Current market state for a single symbol."""
    symbol: str
    bid: float = 0.0
    ask: float = 0.0
    spread_pips: float = 0.0
    trend: str = "neutral"       # "bullish", "bearish", "neutral"
    regime: str = "unknown"      # "trending", "ranging", "breakout", "volatile"
    volatility: float = 0.0
    rsi: float = 50.0
    session: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def spread_pct(self) -> float:
        if self.ask <= 0:
            return 0.0
        return (self.ask - self.bid) / self.ask * 100


@dataclass
class ActiveSetup:
    """A trading setup currently being evaluated."""
    setup_id: str
    symbol: str
    direction: str  # "long" or "short"
    entry_zone: tuple[float, float]  # (low, high)
    stop_loss: float
    take_profit: float
    confluence_score: float  # 0.0 - 1.0
    agent_consensus: dict[str, dict] = field(default_factory=dict)  # agent → {signal, confidence}
    status: str = "evaluating"  # "evaluating", "approved", "rejected", "executed"
    created_at: float = field(default_factory=time.time)
    skills_used: list[str] = field(default_factory=list)


class WorkingMemory:
    """Redis-backed working memory for live trading state.

    Provides fast read/write access to current market conditions,
    active positions, setups being evaluated, and system status.
    Falls back to in-memory cache when Redis is unavailable.
    """

    def __init__(self, redis: RedisCache | None = None):
        self._redis = redis
        self._local: dict[str, Any] = {}  # In-memory fallback
        self._snapshots: dict[str, MarketSnapshot] = {}
        self._setups: dict[str, ActiveSetup] = {}
        self._positions: dict[str, dict] = {}

    # ── Market Snapshots ─────────────────────────────────────────────

    async def update_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        """Update the current market snapshot for a symbol."""
        key = f"market:{snapshot.symbol}"
        self._snapshots[snapshot.symbol] = snapshot

        if self._redis:
            await self._redis.set(key, {
                "symbol": snapshot.symbol,
                "bid": snapshot.bid,
                "ask": snapshot.ask,
                "spread_pips": snapshot.spread_pips,
                "trend": snapshot.trend,
                "regime": snapshot.regime,
                "volatility": snapshot.volatility,
                "rsi": snapshot.rsi,
                "session": snapshot.session,
                "timestamp": snapshot.timestamp,
                "additional": snapshot.additional,
            }, ttl=DEFAULT_TTL)

        logger.debug("working_market_snapshot_updated", symbol=snapshot.symbol)

    def get_market_snapshot(self, symbol: str) -> MarketSnapshot | None:
        """Get the cached market snapshot for a symbol."""
        return self._snapshots.get(symbol)

    def get_all_market_snapshots(self) -> dict[str, MarketSnapshot]:
        """Get all cached market snapshots."""
        return dict(self._snapshots)

    # ── Active Positions ─────────────────────────────────────────────

    async def set_positions(self, positions: list[dict[str, Any]]) -> None:
        """Update the active positions list."""
        self._positions = {p.get("ticket", str(i)): p for i, p in enumerate(positions)}

        if self._redis:
            await self._redis.set("positions", positions, ttl=POSITION_TTL)

        logger.debug("working_positions_updated", count=len(positions))

    def get_positions(self) -> list[dict[str, Any]]:
        """Get all active positions."""
        return list(self._positions.values())

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        """Get the active position for a symbol, if any."""
        for pos in self._positions.values():
            if pos.get("symbol") == symbol:
                return pos
        return None

    def get_open_symbols(self) -> set[str]:
        """Get the set of symbols with active positions."""
        return {p.get("symbol", "") for p in self._positions.values() if p.get("symbol")}

    # ── Active Setups ────────────────────────────────────────────────

    async def add_setup(self, setup: ActiveSetup) -> None:
        """Add a setup being evaluated to working memory."""
        self._setups[setup.setup_id] = setup

        if self._redis:
            await self._redis.set(
                f"setup:{setup.setup_id}",
                {
                    "setup_id": setup.setup_id,
                    "symbol": setup.symbol,
                    "direction": setup.direction,
                    "entry_zone": list(setup.entry_zone),
                    "stop_loss": setup.stop_loss,
                    "take_profit": setup.take_profit,
                    "confluence_score": setup.confluence_score,
                    "status": setup.status,
                    "created_at": setup.created_at,
                    "skills_used": setup.skills_used,
                },
                ttl=SETUP_TTL,
            )

    def get_setup(self, setup_id: str) -> ActiveSetup | None:
        """Get a specific setup."""
        return self._setups.get(setup_id)

    def get_active_setups(self) -> list[ActiveSetup]:
        """Get all setups currently in evaluation."""
        return [s for s in self._setups.values() if s.status == "evaluating"]

    def get_setups_for_symbol(self, symbol: str) -> list[ActiveSetup]:
        """Get all setups for a specific symbol."""
        return [s for s in self._setups.values() if s.symbol == symbol]

    async def update_setup_status(self, setup_id: str, status: str) -> None:
        """Update the status of a setup (evaluating → approved/rejected/executed)."""
        setup = self._setups.get(setup_id)
        if setup:
            setup.status = status
            if self._redis:
                await self._redis.set(f"setup:{setup_id}:status", status, ttl=SETUP_TTL)

    # ── Guardian Status ──────────────────────────────────────────────

    async def set_guardian_status(self, status: dict[str, Any]) -> None:
        """Update the guardian kill-switch status."""
        self._local["guardian_status"] = status

        if self._redis:
            await self._redis.set("guardian:status", status, ttl=GUARDIAN_TTL)

    def get_guardian_status(self) -> dict[str, Any]:
        """Get the current guardian status."""
        return self._local.get("guardian_status", {})

    def is_trading_halted(self) -> bool:
        """Check if trading is currently halted."""
        gs = self.get_guardian_status()
        return gs.get("trading_halted", False)

    def is_learning_frozen(self) -> bool:
        """Check if learning is frozen (kill-switch #16)."""
        gs = self.get_guardian_status()
        return gs.get("learning_frozen", False)

    # ── Learning State ───────────────────────────────────────────────

    async def set_learning_state(self, state: dict[str, Any]) -> None:
        """Update the learning system state."""
        self._local["learning_state"] = state

        if self._redis:
            await self._redis.set("learning:state", state, ttl=LEARNING_TTL)

    def get_learning_state(self) -> dict[str, Any]:
        """Get the current learning system state."""
        return self._local.get("learning_state", {})

    # ── Debate State ─────────────────────────────────────────────────

    async def set_debate_state(
        self, symbol: str, agent_reports: dict[str, dict[str, Any]], consensus: dict[str, Any]
    ) -> None:
        """Store the current debate round state."""
        state = {
            "symbol": symbol,
            "agent_reports": agent_reports,
            "consensus": consensus,
            "timestamp": time.time(),
        }
        self._local[f"debate:{symbol}"] = state

        if self._redis:
            await self._redis.set(f"debate:{symbol}", state, ttl=SETUP_TTL)

    def get_debate_state(self, symbol: str) -> dict[str, Any] | None:
        """Get the debate state for a symbol."""
        return self._local.get(f"debate:{symbol}")

    # ── Utility ──────────────────────────────────────────────────────

    async def clear_symbol(self, symbol: str) -> None:
        """Clear all working memory for a symbol."""
        self._snapshots.pop(symbol, None)
        self._setups = {
            k: v for k, v in self._setups.items() if v.symbol != symbol
        }
        self._local.pop(f"debate:{symbol}", None)

    async def clear_all(self) -> None:
        """Clear all working memory (for testing or reset)."""
        self._snapshots.clear()
        self._setups.clear()
        self._positions.clear()
        self._local.clear()

    @property
    def stats(self) -> dict[str, Any]:
        """Return working memory statistics."""
        return {
            "snapshots_count": len(self._snapshots),
            "active_setups": len([s for s in self._setups.values() if s.status == "evaluating"]),
            "active_positions": len(self._positions),
            "trading_halted": self.is_trading_halted(),
            "learning_frozen": self.is_learning_frozen(),
            "symbols_tracked": sorted(self._snapshots.keys()),
        }
