"""Episodic Memory — PostgreSQL-backed trade event log.

Stores the complete narrative of every trade: entry context, agent signals,
debate outcomes, PnL, and post-trade reflections. This is the system's
"what happened" store — the ground truth for all learning.

Uses the existing TradeStore (noema/core/storage.py) for PostgreSQL access.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

from noema.core.storage import TradeStore

logger = structlog.get_logger(__name__)


class EpisodicMemory:
    """PostgreSQL-backed episodic memory store.

    Records full trade narratives with context for later replay and learning.
    Each episode contains: pre-trade context, agent signals, debate results,
    execution details, PnL outcome, and post-trade reflections.
    """

    def __init__(self, trade_store: TradeStore):
        self._store = trade_store
        self._episodes: list[dict[str, Any]] = []  # In-memory cache for fast access

    async def record_episode(self, episode: dict[str, Any]) -> int:
        """Record a complete trade episode.

        Args:
            episode: Dict with keys:
                - symbol, direction, entry_price, exit_price, stop_loss, take_profit
                - lot_size, pnl, status
                - pre_trade_context (dict): market regime, trend, session, etc.
                - agent_signals (dict): {agent_name: {signal, confidence}}
                - debate_outcome (dict): thesis, devil, cio decisions
                - metadata (dict): any additional context

        Returns:
            trade_id from PostgreSQL
        """
        trade_data = {
            "symbol": episode.get("symbol", ""),
            "direction": episode.get("direction", ""),
            "entry_price": episode.get("entry_price", 0),
            "exit_price": episode.get("exit_price"),
            "stop_loss": episode.get("stop_loss", 0),
            "take_profit": episode.get("take_profit"),
            "lot_size": episode.get("lot_size", 0.01),
            "confidence": episode.get("confidence", 0),
            "reasoning": episode.get("reasoning", ""),
            "agent_signals": episode.get("agent_signals", {}),
            "metadata": {
                "pre_trade_context": episode.get("pre_trade_context", {}),
                "debate_outcome": episode.get("debate_outcome", {}),
                "episode_type": episode.get("episode_type", "trade"),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                **(episode.get("metadata", {})),
            },
        }

        trade_id = await self._store.store_trade(trade_data)

        # Update in-memory cache
        episode["trade_id"] = trade_id
        self._episodes.append(episode)
        if len(self._episodes) > 10_000:  # Cap in-memory cache
            self._episodes = self._episodes[-5_000:]

        logger.info(
            "episodic_memory_recorded",
            trade_id=trade_id,
            symbol=episode.get("symbol"),
            outcome=episode.get("pnl", 0),
        )
        return trade_id

    async def close_episode(self, trade_id: int, exit_price: float, pnl: float) -> None:
        """Close an open episode with final P&L."""
        await self._store.close_trade(trade_id, exit_price, pnl)
        logger.info("episodic_memory_closed", trade_id=trade_id, pnl=pnl)

    async def get_episodes(
        self,
        symbol: str | None = None,
        days: int = 30,
        min_pnl: float | None = None,
        max_pnl: float | None = None,
        status: str = "CLOSED",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query trade episodes with filters.

        Args:
            symbol: Filter by symbol (None = all)
            days: Look back N days
            min_pnl: Minimum PnL filter
            max_pnl: Maximum PnL filter
            status: Trade status ('OPEN', 'CLOSED', 'CANCELLED')
            limit: Max results

        Returns:
            List of trade dictionaries
        """
        # For now, use the store's get_recent_trades and filter client-side
        # Full query support would require extending TradeStore
        if symbol:
            trades = await self._store.get_recent_trades(symbol, limit=limit)
        else:
            # If no symbol, get from in-memory cache filtered by recency
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            trades = [
                e for e in self._episodes
                if e.get("trade_id") and e.get("status", "CLOSED") == status
            ]
            trades = trades[-limit:]

        # Apply filters
        result = []
        for t in trades:
            pnl = t.get("pnl", 0)
            if min_pnl is not None and pnl < min_pnl:
                continue
            if max_pnl is not None and pnl > max_pnl:
                continue
            if t.get("status", "CLOSED") != status:
                continue
            result.append(t)

        return result

    async def get_recent_winners(self, symbol: str, n: int = 10) -> list[dict[str, Any]]:
        """Get the N most recent winning trades for a symbol."""
        return await self.get_episodes(symbol=symbol, min_pnl=0.01, limit=n)

    async def get_recent_losers(self, symbol: str, n: int = 10) -> list[dict[str, Any]]:
        """Get the N most recent losing trades for a symbol."""
        return await self.get_episodes(symbol=symbol, max_pnl=-0.01, limit=n)

    async def get_significant_episodes(
        self, symbol: str | None = None, n: int = 20
    ) -> list[dict[str, Any]]:
        """Get the most significant episodes (largest |PnL|) for experience replay.

        These are the trades we want to replay and learn from most.
        """
        episodes = await self.get_episodes(symbol=symbol, limit=n * 5)
        # Sort by absolute PnL
        episodes.sort(key=lambda e: abs(e.get("pnl", 0)), reverse=True)
        return episodes[:n]

    async def store_reflection(self, trade_id: int, reflection: dict[str, Any]) -> None:
        """Store a post-trade reflection linked to an episode."""
        await self._store.store_reflection({
            "trade_id": trade_id,
            **reflection,
        })

    def get_episode_count(self) -> int:
        """Return count of cached episodes."""
        return len(self._episodes)

    async def close(self) -> None:
        """Cleanup — no explicit close needed (TradeStore lifecycle managed externally)."""
        self._episodes.clear()
