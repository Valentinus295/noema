"""Abstract broker interface for VMPM.

All broker implementations (MT5, Paper) must implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class OrderResult:
    """Result of an order execution."""
    success: bool
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    error: str = ""


@dataclass
class Position:
    """An open position."""
    ticket: int
    symbol: str
    type: str           # "buy" or "sell"
    volume: float
    open_price: float
    current_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    pnl: float = 0.0
    magic: int = 0


class BrokerBase(ABC):
    """Abstract broker interface."""

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(broker=self.__class__.__name__)

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize connection to broker."""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown broker connection."""
        ...

    @abstractmethod
    def get_account_info(self) -> dict[str, Any]:
        """Get account balance, equity, margin, etc."""
        ...

    @abstractmethod
    def get_tick(self, symbol: str) -> dict[str, float]:
        """Get current bid/ask for a symbol."""
        ...

    @abstractmethod
    def get_rates(self, symbol: str, timeframe: str, count: int) -> Any:
        """Get OHLCV rates for a symbol."""
        ...

    @abstractmethod
    def place_order(
        self, symbol: str, direction: str, volume: float,
        sl: float = 0, tp: float = 0, magic: int = 0, comment: str = ""
    ) -> OrderResult:
        """Place a market order."""
        ...

    @abstractmethod
    def modify_position(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        """Modify SL/TP of an open position."""
        ...

    @abstractmethod
    def close_position(self, ticket: int) -> bool:
        """Close an open position."""
        ...

    @abstractmethod
    def get_open_positions(self, magic: int = 0) -> list[Position]:
        """Get all open positions, optionally filtered by magic number."""
        ...

    @abstractmethod
    def get_daily_pnl(self) -> float:
        """Get today's realized P&L."""
        ...

    @abstractmethod
    def get_weekly_pnl(self) -> float:
        """Get this week's realized P&L."""
        ...

from vmpm.core.types import Bar

from typing import Protocol, Sequence

class BrokerProtocol(Protocol):
    """Structural interface for broker implementations.

    Used by the 7-agent orchestrator. BrokerBase (ABC) is the legacy interface.
    """

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def is_connected(self) -> bool: ...
    async def account_state(self) -> "AccountState": ...
    async def bars(self, symbol: str, timeframe: str, count: int) -> Sequence["Bar"]: ...
    async def tick(self, symbol: str) -> "Tick": ...
    async def symbol_info(self, symbol: str) -> dict: ...
    async def positions(self) -> Sequence["Position"]: ...
    async def send_order(self, req: "OrderRequest") -> "Position": ...
    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> "Position": ...
    async def close_position(self, ticket: int, volume: float | None = None) -> "Position": ...
    async def close_all_positions(self, reason: str) -> Sequence["Position"]: ...


@dataclass
class OrderRequest:
    """Request to place an order via the broker."""
    symbol: str
    side: str          # "buy" or "sell"
    type: str = "market"  # "market" or "limit"
    volume: float = 0.01
    price: float | None = None
    sl: float = 0.0
    tp: float = 0.0
    comment: str = ""


@dataclass
class Tick:
    """A single price tick."""
    bid: float
    ask: float
    time: float = 0.0


@dataclass
class AccountState:
    """Account balance and margin state."""
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    leverage: int = 100
    currency: str = "USD"

