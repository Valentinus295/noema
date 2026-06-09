"""Paper trading broker — simulates trades without real money.

Used for development, testing, and paper trading mode.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from vmpm.broker.base import BrokerBase, OrderResult, Position

logger = structlog.get_logger(__name__)


class PaperBroker(BrokerBase):
    """Simulated broker for paper trading.

    Maintains virtual balance, simulates fills at mid-price,
    and tracks open positions in memory.
    """

    def __init__(self, config: Any = None, initial_balance: float = 10000.0) -> None:
        super().__init__(config)
        self._balance = initial_balance
        self._equity = initial_balance
        self._positions: dict[int, Position] = {}
        self._history: list[dict] = []
        self._next_ticket = 100001
        self._connected = False
        self._daily_pnl = 0.0
        self._weekly_pnl = 0.0

    def initialize(self) -> bool:
        self._connected = True
        self._logger.info("paper_broker_initialized", balance=self._balance)
        return True

    def shutdown(self) -> None:
        self._connected = False
        self._logger.info("paper_broker_shutdown")

    def get_account_info(self) -> dict[str, Any]:
        unrealized = sum(p.pnl for p in self._positions.values())
        return {
            "balance": self._balance,
            "equity": self._balance + unrealized,
            "margin": 0.0,
            "free_margin": self._balance,
            "leverage": 100,
            "currency": "USD",
        }

    def get_tick(self, symbol: str) -> dict[str, float]:
        # Simulate a basic spread
        return {"bid": 1.1000, "ask": 1.1002, "time": time.time()}

    def get_rates(self, symbol: str, timeframe: str, count: int = 100) -> Any:
        import pandas as pd
        import numpy as np
        # Generate synthetic OHLCV data for testing
        np.random.seed(42)
        close = 1.1000 + np.cumsum(np.random.randn(count) * 0.0005)
        df = pd.DataFrame({
            "time": pd.date_range(end=pd.Timestamp.now(), periods=count, freq="1h"),
            "open": close + np.random.randn(count) * 0.0001,
            "high": close + abs(np.random.randn(count) * 0.0003),
            "low": close - abs(np.random.randn(count) * 0.0003),
            "close": close,
            "volume": np.random.randint(100, 1000, count).astype(float),
        })
        return df

    def place_order(
        self, symbol: str, direction: str, volume: float,
        sl: float = 0, tp: float = 0, magic: int = 0, comment: str = "VMPM"
    ) -> OrderResult:
        ticket = self._next_ticket
        self._next_ticket += 1

        # Simulate fill at mid-price
        price = 1.1001 if direction.lower() == "buy" else 1.1001

        pos = Position(
            ticket=ticket,
            symbol=symbol,
            type=direction.lower(),
            volume=volume,
            open_price=price,
            current_price=price,
            sl=sl,
            tp=tp,
            magic=magic,
        )
        self._positions[ticket] = pos

        self._logger.info(
            "paper_order_placed",
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            volume=volume,
            price=price,
        )

        return OrderResult(success=True, ticket=ticket, price=price, volume=volume)

    def modify_position(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        if ticket not in self._positions:
            return False
        pos = self._positions[ticket]
        if sl > 0:
            pos.sl = sl
        if tp > 0:
            pos.tp = tp
        return True

    def close_position(self, ticket: int) -> bool:
        if ticket not in self._positions:
            return False
        pos = self._positions.pop(ticket)
        pnl = pos.pnl
        self._balance += pnl
        self._daily_pnl += pnl
        self._history.append({
            "ticket": ticket, "symbol": pos.symbol,
            "direction": pos.type, "pnl": pnl,
            "closed_at": time.time(),
        })
        self._logger.info("paper_position_closed", ticket=ticket, pnl=pnl)
        return True

    def get_open_positions(self, magic: int = 0) -> list[Position]:
        positions = list(self._positions.values())
        if magic:
            positions = [p for p in positions if p.magic == magic]
        return positions

    def get_daily_pnl(self) -> float:
        return self._daily_pnl

    def get_weekly_pnl(self) -> float:
        return self._weekly_pnl

    @property
    def trade_history(self) -> list[dict]:
        return self._history
