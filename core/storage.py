"""PostgreSQL + Redis infrastructure for VMPM.

Provides:
- PostgreSQL: Trade history, reflections, audit trail (replaces SQLite)
- Redis: Decision caching, rate limiting, pub/sub for inter-agent communication
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── PostgreSQL (Trade History + Reflections) ─────────────────────────

class TradeStore:
    """PostgreSQL-backed trade history and reflections.

    Uses SQLAlchemy async engine for non-blocking DB access.
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._engine = None
        self._session_factory = None

    async def initialize(self) -> None:
        """Create engine and tables."""
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy import text

        self._engine = create_async_engine(
            self.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )

        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

        # Create tables if not exist
        async with self._engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(10) NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    entry_price NUMERIC(12, 6),
                    exit_price NUMERIC(12, 6),
                    stop_loss NUMERIC(12, 6),
                    take_profit NUMERIC(12, 6),
                    lot_size NUMERIC(8, 4),
                    pnl NUMERIC(12, 2),
                    status VARCHAR(20) DEFAULT 'OPEN',
                    decision_confidence NUMERIC(4, 3),
                    decision_reasoning TEXT,
                    agent_signals JSONB,
                    opened_at TIMESTAMPTZ DEFAULT NOW(),
                    closed_at TIMESTAMPTZ,
                    metadata JSONB DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS reflections (
                    id SERIAL PRIMARY KEY,
                    trade_id INTEGER REFERENCES trades(id),
                    symbol VARCHAR(10) NOT NULL,
                    outcome VARCHAR(20),
                    what_worked TEXT[],
                    what_failed TEXT[],
                    lesson_learned TEXT,
                    pattern_type VARCHAR(100),
                    should_repeat BOOLEAN,
                    adjustments TEXT[],
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at);
                CREATE INDEX IF NOT EXISTS idx_reflections_symbol ON reflections(symbol);
            """))

        logger.info("trade_store_initialized", url=self.database_url.split("@")[-1])

    async def store_trade(self, trade: dict[str, Any]) -> int:
        """Store a new trade and return its ID."""
        from sqlalchemy import text

        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    INSERT INTO trades (symbol, direction, entry_price, stop_loss, take_profit,
                                        lot_size, decision_confidence, decision_reasoning, agent_signals, metadata)
                    VALUES (:symbol, :direction, :entry_price, :stop_loss, :take_profit,
                            :lot_size, :confidence, :reasoning, :signals, :metadata)
                    RETURNING id
                """),
                {
                    "symbol": trade.get("symbol", ""),
                    "direction": trade.get("direction", ""),
                    "entry_price": trade.get("entry_price", 0),
                    "stop_loss": trade.get("stop_loss", 0),
                    "take_profit": trade.get("take_profit"),
                    "lot_size": trade.get("lot_size", 0.01),
                    "confidence": trade.get("confidence", 0),
                    "reasoning": trade.get("reasoning", ""),
                    "signals": json.dumps(trade.get("agent_signals", {})),
                    "metadata": json.dumps(trade.get("metadata", {})),
                },
            )
            await session.commit()
            trade_id = result.scalar_one()
            logger.info("trade_stored", trade_id=trade_id, symbol=trade.get("symbol"))
            return trade_id

    async def close_trade(self, trade_id: int, exit_price: float, pnl: float) -> None:
        """Close a trade with exit price and P&L."""
        from sqlalchemy import text

        async with self._session_factory() as session:
            await session.execute(
                text("""
                    UPDATE trades
                    SET exit_price = :exit_price, pnl = :pnl,
                        status = 'CLOSED', closed_at = NOW()
                    WHERE id = :trade_id
                """),
                {"trade_id": trade_id, "exit_price": exit_price, "pnl": pnl},
            )
            await session.commit()
            logger.info("trade_closed", trade_id=trade_id, pnl=pnl)

    async def store_reflection(self, reflection: dict[str, Any]) -> None:
        """Store a post-trade reflection."""
        from sqlalchemy import text

        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO reflections (trade_id, symbol, outcome, what_worked, what_failed,
                                            lesson_learned, pattern_type, should_repeat, adjustments)
                    VALUES (:trade_id, :symbol, :outcome, :what_worked, :what_failed,
                            :lesson, :pattern, :repeat, :adjustments)
                """),
                {
                    "trade_id": reflection.get("trade_id"),
                    "symbol": reflection.get("symbol", ""),
                    "outcome": reflection.get("outcome", ""),
                    "what_worked": reflection.get("what_worked", []),
                    "what_failed": reflection.get("what_failed", []),
                    "lesson": reflection.get("lesson_learned", ""),
                    "pattern": reflection.get("pattern_type"),
                    "repeat": reflection.get("should_repeat", True),
                    "adjustments": reflection.get("adjustments", []),
                },
            )
            await session.commit()

    async def get_recent_trades(self, symbol: str, limit: int = 10) -> list[dict]:
        """Get recent trades for a symbol."""
        from sqlalchemy import text

        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM trades
                    WHERE symbol = :symbol
                    ORDER BY opened_at DESC
                    LIMIT :limit
                """),
                {"symbol": symbol, "limit": limit},
            )
            return [dict(row._mapping) for row in result.fetchall()]

    async def get_performance_stats(self, symbol: str, days: int = 30) -> dict:
        """Get performance statistics for a symbol."""
        from sqlalchemy import text

        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        COUNT(*) as total_trades,
                        COUNT(*) FILTER (WHERE pnl > 0) as winning_trades,
                        COUNT(*) FILTER (WHERE pnl < 0) as losing_trades,
                        COALESCE(SUM(pnl), 0) as total_pnl,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl > 0), 0) as avg_win,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl < 0), 0) as avg_loss,
                        COALESCE(AVG(decision_confidence), 0) as avg_confidence
                    FROM trades
                    WHERE symbol = :symbol
                      AND status = 'CLOSED'
                      AND closed_at > NOW() - INTERVAL ':days days'
                """),
                {"symbol": symbol, "days": days},
            )
            row = result.fetchone()
            if row:
                d = dict(row._mapping)
                total = d["total_trades"]
                d["win_rate"] = d["winning_trades"] / total if total else 0
                return d
            return {}

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()


# ── Redis (Caching + Pub/Sub) ────────────────────────────────────────

class RedisCache:
    """Redis-backed caching and pub/sub for VMPM.

    Provides:
    - Decision caching (faster than in-process cache, shared across processes)
    - Rate limiting (atomic counter operations)
    - Pub/sub for inter-agent communication
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._redis = None

    async def initialize(self) -> None:
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self._redis.ping()
            logger.info("redis_connected", url=self.redis_url.split("@")[-1])
        except ImportError:
            logger.warning("redis_not_installed", hint="pip install redis")
        except Exception as e:
            logger.warning("redis_connection_failed", error=str(e))

    async def get(self, key: str) -> Any | None:
        if not self._redis:
            return None
        try:
            data = await self._redis.get(f"vmpm:{key}")
            return json.loads(data) if data else None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(f"vmpm:{key}", json.dumps(value, default=str), ex=ttl)
        except Exception as e:
            logger.warning("redis_set_failed", error=str(e))

    async def incr_rate_limit(self, key: str, window: int = 60) -> int:
        """Increment rate limit counter. Returns current count."""
        if not self._redis:
            return 0
        try:
            pipe = self._redis.pipeline()
            full_key = f"vmpm:ratelimit:{key}"
            pipe.incr(full_key)
            pipe.expire(full_key, window)
            results = await pipe.execute()
            return results[0]
        except Exception:
            return 0

    async def publish(self, channel: str, message: dict) -> None:
        """Publish a message to a Redis channel."""
        if not self._redis:
            return
        try:
            await self._redis.publish(f"vmpm:{channel}", json.dumps(message, default=str))
        except Exception as e:
            logger.warning("redis_publish_failed", error=str(e))

    async def subscribe(self, channel: str, callback):
        """Subscribe to a Redis channel."""
        if not self._redis:
            return
        try:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(f"vmpm:{channel}")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    await callback(data)
        except Exception as e:
            logger.warning("redis_subscribe_failed", error=str(e))

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
