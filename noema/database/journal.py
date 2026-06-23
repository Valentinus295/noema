"""DuckDB trade journal — full audit trail with config-hash and git-SHA stamping.

Every trade, every decision, every config version is recorded.
This is the system's memory — immutable, queryable, auditable.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TradeJournal:
    """DuckDB-backed trade journal with full audit trail.

    Records every trade with:
    - Config hash + git SHA (reproducibility)
    - Agent reports (decision audit)
    - Market context (regime, session, indicators)
    - Outcome metrics (P&L, R-multiple, duration)
    """

    def __init__(self, db_path: str = "data/journal.duckdb") -> None:
        self.db_path = Path(db_path)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            logger.error("journal_dir_create_failed", path=str(self.db_path.parent), error=str(exc))
        self._conn = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize DuckDB connection and create tables."""
        try:
            import duckdb
            self._conn = duckdb.connect(str(self.db_path))

            # Sequences must be created before tables that reference them
            self._conn.execute("CREATE SEQUENCE IF NOT EXISTS trades_seq START 1")
            self._conn.execute("CREATE SEQUENCE IF NOT EXISTS decisions_seq START 1")

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER DEFAULT (nextval('trades_seq')),
                    ticket INTEGER,
                    symbol VARCHAR,
                    direction VARCHAR,
                    entry_price DOUBLE,
                    exit_price DOUBLE,
                    volume DOUBLE,
                    sl DOUBLE,
                    tp DOUBLE,
                    pnl DOUBLE,
                    pnl_pips DOUBLE,
                    r_multiple DOUBLE,
                    entry_time TIMESTAMP,
                    exit_time TIMESTAMP,
                    exit_reason VARCHAR,
                    session VARCHAR,
                    market_regime VARCHAR,
                    settings_hash VARCHAR,
                    git_sha VARCHAR,
                    strategy_version VARCHAR,
                    account_balance_before DOUBLE,
                    account_balance_after DOUBLE,
                    agent_reports JSON,
                    market_context JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date DATE PRIMARY KEY,
                    trades_count INTEGER,
                    wins INTEGER,
                    losses INTEGER,
                    win_rate DOUBLE,
                    total_pnl DOUBLE,
                    max_drawdown DOUBLE,
                    sharpe_rolling DOUBLE,
                    settings_hash VARCHAR,
                    git_sha VARCHAR
                )
            """)

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_decisions (
                    id INTEGER DEFAULT (nextval('decisions_seq')),
                    trade_id INTEGER,
                    agent_name VARCHAR,
                    signal VARCHAR,
                    confidence DOUBLE,
                    reasoning TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            logger.info("journal_initialized", db_path=str(self.db_path))

        except ImportError:
            logger.warning("duckdb_not_available")
            self._conn = None

    def record_trade(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        volume: float,
        sl: float,
        tp: float,
        pnl: float,
        pnl_pips: float,
        entry_time: datetime,
        exit_time: datetime,
        exit_reason: str,
        session: str,
        settings_hash: str,
        git_sha: str,
        strategy_version: str = "0.1.0",
        account_balance_before: float = 0.0,
        account_balance_after: float = 0.0,
        agent_reports: dict[str, Any] | None = None,
        market_context: dict[str, Any] | None = None,
        market_regime: str = "unknown",
    ) -> int:
        """Record a completed trade. Returns trade ID."""
        if not self._conn:
            return -1

        risk = abs(entry_price - sl) if sl > 0 else 0.0010
        r_multiple = pnl / (risk * volume * 10000) if risk > 0 else 0.0

        result = self._conn.execute("""
            INSERT INTO trades (
                ticket, symbol, direction, entry_price, exit_price,
                volume, sl, tp, pnl, pnl_pips, r_multiple,
                entry_time, exit_time, exit_reason, session,
                market_regime, settings_hash, git_sha, strategy_version,
                account_balance_before, account_balance_after,
                agent_reports, market_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (
            ticket, symbol, direction, entry_price, exit_price,
            volume, sl, tp, pnl, pnl_pips, r_multiple,
            entry_time, exit_time, exit_reason, session,
            market_regime, settings_hash, git_sha, strategy_version,
            account_balance_before, account_balance_after,
            json.dumps(agent_reports or {}), json.dumps(market_context or {}),
        ))

        trade_id = result.fetchone()[0]
        logger.info("trade_recorded", trade_id=trade_id, symbol=symbol,
                     pnl=pnl, r_multiple=r_multiple)
        return trade_id

    def record_agent_decision(
        self,
        trade_id: int,
        agent_name: str,
        signal: str,
        confidence: float,
        reasoning: str,
    ) -> None:
        """Record an agent's decision for a trade."""
        if not self._conn:
            return

        self._conn.execute("""
            INSERT INTO agent_decisions (trade_id, agent_name, signal, confidence, reasoning)
            VALUES (?, ?, ?, ?, ?)
        """, (trade_id, agent_name, signal, confidence, reasoning))

    def get_trades(
        self,
        symbol: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query trades from the journal."""
        if not self._conn:
            return []

        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if start_date:
            query += " AND entry_time >= ?"
            params.append(start_date)
        if end_date:
            query += " AND exit_time <= ?"
            params.append(end_date)

        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)

        result = self._conn.execute(query, params)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def get_daily_summary(self, days: int = 30) -> list[dict[str, Any]]:
        """Get daily P&L summary."""
        if not self._conn:
            return []

        result = self._conn.execute("""
            SELECT
                DATE(entry_time) as date,
                COUNT(*) as trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl
            FROM trades
            WHERE entry_time >= CURRENT_DATE - INTERVAL ? DAY
            GROUP BY DATE(entry_time)
            ORDER BY date DESC
        """, (days,))

        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def get_agent_accuracy(self, agent_name: str | None = None) -> dict[str, Any]:
        """Get agent prediction accuracy."""
        if not self._conn:
            return {}

        query = """
            SELECT
                ad.agent_name,
                COUNT(*) as total_decisions,
                SUM(CASE WHEN ad.signal = 'BUY' AND t.pnl > 0 THEN 1
                         WHEN ad.signal = 'SELL' AND t.pnl > 0 THEN 1
                         WHEN ad.signal IN ('WAIT', 'REJECT') AND t.pnl <= 0 THEN 1
                         ELSE 0 END) as correct,
                AVG(ad.confidence) as avg_confidence
            FROM agent_decisions ad
            JOIN trades t ON ad.trade_id = t.id
        """
        params: list[Any] = []

        if agent_name:
            query += " WHERE ad.agent_name = ?"
            params.append(agent_name)

        query += " GROUP BY ad.agent_name"

        result = self._conn.execute(query, params)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return {row[0]: dict(zip(columns[1:], row[1:])) for row in rows}

    def compute_config_hash(self, config_dict: dict[str, Any]) -> str:
        """Compute SHA-256 hash of configuration for versioning."""
        config_str = json.dumps(config_dict, sort_keys=True, default=str)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
