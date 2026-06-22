"""Tests for DuckDB trade journal."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from noema.database.journal import TradeJournal


class TestTradeJournal:
    """Tests for TradeJournal."""

    def test_initialization(self, tmp_path):
        journal = TradeJournal(db_path=str(tmp_path / "test.duckdb"))
        assert journal._conn is not None
        journal.close()

    def test_record_trade(self, tmp_path):
        journal = TradeJournal(db_path=str(tmp_path / "test.duckdb"))
        trade_id = journal.record_trade(
            ticket=1001, symbol="EURUSD", direction="buy",
            entry_price=1.1000, exit_price=1.1050,
            volume=0.1, sl=1.0950, tp=1.1100,
            pnl=50.0, pnl_pips=50.0,
            entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            exit_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
            exit_reason="tp", session="london",
            settings_hash="abc123", git_sha="def456",
        )
        assert trade_id >= 0
        journal.close()

    def test_record_agent_decision(self, tmp_path):
        journal = TradeJournal(db_path=str(tmp_path / "test.duckdb"))
        trade_id = journal.record_trade(
            ticket=1001, symbol="EURUSD", direction="buy",
            entry_price=1.1, exit_price=1.105,
            volume=0.1, sl=1.095, tp=1.11,
            pnl=50.0, pnl_pips=50.0,
            entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            exit_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
            exit_reason="tp", session="london",
            settings_hash="abc", git_sha="def",
        )
        journal.record_agent_decision(
            trade_id, "macro-economic", "BULLISH", 0.8, "Strong fundamentals"
        )
        journal.close()

    def test_get_trades(self, tmp_path):
        journal = TradeJournal(db_path=str(tmp_path / "test.duckdb"))
        for i in range(5):
            journal.record_trade(
                ticket=1000 + i, symbol="EURUSD", direction="buy",
                entry_price=1.1, exit_price=1.105,
                volume=0.1, sl=1.095, tp=1.11,
                pnl=50.0, pnl_pips=50.0,
                entry_time=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
                exit_time=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
                exit_reason="tp", session="london",
                settings_hash="abc", git_sha="def",
            )
        trades = journal.get_trades(symbol="EURUSD")
        assert len(trades) == 5
        journal.close()

    def test_config_hash(self, tmp_path):
        journal = TradeJournal(db_path=str(tmp_path / "test.duckdb"))
        h1 = journal.compute_config_hash({"risk": 0.01, "pairs": ["EURUSD"]})
        h2 = journal.compute_config_hash({"risk": 0.01, "pairs": ["EURUSD"]})
        h3 = journal.compute_config_hash({"risk": 0.02, "pairs": ["EURUSD"]})
        assert h1 == h2
        assert h1 != h3
        journal.close()

    def test_get_trades_empty(self, tmp_path):
        journal = TradeJournal(db_path=str(tmp_path / "test.duckdb"))
        trades = journal.get_trades()
        assert trades == []
        journal.close()
