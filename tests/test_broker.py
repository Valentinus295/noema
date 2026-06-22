"""Unit tests for broker modules.

Covers:
- BrokerBase abstract interface
- PaperBroker (account info, orders, positions, P&L)
"""

from __future__ import annotations

import pytest

from vmpm.broker.base import BrokerBase, OrderResult, Position
from vmpm.broker.paper import PaperBroker


# ===========================================================================
# BrokerBase (Abstract)
# ===========================================================================


class TestBrokerBase:
    """Tests for the abstract BrokerBase class."""

    def test_cannot_instantiate(self):
        """BrokerBase should not be instantiable directly."""
        with pytest.raises(TypeError):
            BrokerBase()  # type: ignore[abstract]

    def test_order_result_defaults(self):
        """OrderResult should have sensible defaults."""
        result = OrderResult(success=True)
        assert result.success is True
        assert result.ticket == 0
        assert result.price == 0.0
        assert result.error == ""

    def test_order_result_custom(self):
        """OrderResult should accept custom values."""
        result = OrderResult(success=False, error="Insufficient margin")
        assert result.success is False
        assert result.error == "Insufficient margin"

    def test_position_dataclass(self):
        """Position should store trade info."""
        pos = Position(
            ticket=1001,
            symbol="EURUSD",
            type="buy",
            volume=0.1,
            open_price=1.1000,
        )
        assert pos.ticket == 1001
        assert pos.symbol == "EURUSD"
        assert pos.type == "buy"
        assert pos.volume == 0.1
        assert pos.open_price == 1.1000
        assert pos.pnl == 0.0
        assert pos.magic == 0


# ===========================================================================
# PaperBroker
# ===========================================================================


class TestPaperBroker:
    """Tests for the PaperBroker simulation."""

    async def test_initialize(self):
        """initialize should set connected state."""
        broker = PaperBroker()
        assert broker.initialize() is True
        assert broker._connected is True

    async def test_initial_balance(self):
        """PaperBroker should start with default balance."""
        broker = PaperBroker()
        broker.initialize()
        info = broker.get_account_info()
        assert info["balance"] == 10000.0
        assert info["equity"] == 10000.0

    async def test_custom_initial_balance(self):
        """PaperBroker should accept custom initial balance."""
        broker = PaperBroker(initial_balance=50000.0)
        broker.initialize()
        info = broker.get_account_info()
        assert info["balance"] == 50000.0

    async def test_shutdown(self):
        """shutdown should set disconnected state."""
        broker = PaperBroker()
        broker.initialize()
        assert broker._connected is True
        broker.shutdown()
        assert broker._connected is False

    async def test_get_tick(self):
        """get_tick should return bid/ask."""
        broker = PaperBroker()
        tick = broker.get_tick("EURUSD")
        assert "bid" in tick
        assert "ask" in tick
        assert tick["bid"] < tick["ask"]

    async def test_get_rates(self):
        """get_rates should return a DataFrame."""
        import pandas as pd
        broker = PaperBroker()
        df = broker.get_rates("EURUSD", "H1", 100)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 100
        assert "close" in df.columns
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "volume" in df.columns

    async def test_place_market_order_buy(self):
        """place_order should create a position for buy orders."""
        broker = PaperBroker()
        broker.initialize()
        result = broker.place_order("EURUSD", "buy", 0.1, sl=1.0900, tp=1.1200)
        assert result.success is True
        assert result.ticket > 0
        assert result.volume == 0.1

        positions = broker.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "EURUSD"
        assert positions[0].type == "buy"

    async def test_place_market_order_sell(self):
        """place_order should create a position for sell orders."""
        broker = PaperBroker()
        broker.initialize()
        result = broker.place_order("GBPUSD", "sell", 0.2)
        assert result.success is True
        assert result.ticket > 0

    async def test_modify_position_sl_tp(self):
        """modify_position should update SL and TP."""
        broker = PaperBroker()
        broker.initialize()
        result = broker.place_order("EURUSD", "buy", 0.1)
        assert result.ticket > 0

        modified = broker.modify_position(result.ticket, sl=1.0950, tp=1.1150)
        assert modified is True

        positions = broker.get_open_positions()
        pos = [p for p in positions if p.ticket == result.ticket][0]
        assert pos.sl == 1.0950
        assert pos.tp == 1.1150

    async def test_modify_nonexistent_position(self):
        """modify_position should return False for unknown ticket."""
        broker = PaperBroker()
        assert broker.modify_position(99999, sl=1.09) is False

    async def test_close_position(self):
        """close_position should remove position and update balance."""
        broker = PaperBroker()
        broker.initialize()
        result = broker.place_order("EURUSD", "buy", 0.1)
        balance_before = broker.get_account_info()["balance"]

        closed = broker.close_position(result.ticket)
        assert closed is True

        positions = broker.get_open_positions()
        assert result.ticket not in [p.ticket for p in positions]

    async def test_close_nonexistent_position(self):
        """close_position should return False for unknown ticket."""
        broker = PaperBroker()
        assert broker.close_position(99999) is False

    async def test_get_open_positions_empty(self):
        """get_open_positions should return empty list when no positions."""
        broker = PaperBroker()
        broker.initialize()
        assert broker.get_open_positions() == []

    async def test_get_open_positions_filter_by_magic(self):
        """get_open_positions should filter by magic number."""
        broker = PaperBroker()
        broker.initialize()
        broker.place_order("EURUSD", "buy", 0.1, magic=100)
        broker.place_order("GBPUSD", "buy", 0.1, magic=200)

        magic_100 = broker.get_open_positions(magic=100)
        assert len(magic_100) == 1

    async def test_get_daily_pnl(self):
        """get_daily_pnl should return cumulative daily P&L."""
        broker = PaperBroker()
        assert broker.get_daily_pnl() == 0.0

    async def test_get_weekly_pnl(self):
        """get_weekly_pnl should return cumulative weekly P&L."""
        broker = PaperBroker()
        assert broker.get_weekly_pnl() == 0.0

    async def test_trade_history(self):
        """trade_history should record closed trades."""
        broker = PaperBroker()
        broker.initialize()
        result = broker.place_order("EURUSD", "buy", 0.1)
        broker.close_position(result.ticket)
        assert len(broker.trade_history) == 1
        assert broker.trade_history[0]["ticket"] == result.ticket
