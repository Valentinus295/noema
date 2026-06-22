"""Position model — represents an open or historical position."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PositionInfo:
    """Represents a position tracked by the system."""
    ticket: int = 0
    symbol: str = ""
    direction: str = ""       # "buy" or "sell"
    volume: float = 0.0
    open_price: float = 0.0
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    pnl: float = 0.0
    magic: int = 0

    @property
    def pnl_pips(self) -> float:
        if "JPY" in self.symbol:
            divisor = 0.01
        else:
            divisor = 0.0001
        if self.direction == "buy":
            return (self.current_price - self.open_price) / divisor
        return (self.open_price - self.current_price) / divisor

    @property
    def risk_pips(self) -> float:
        if self.stop_loss == 0:
            return 0
        divisor = 0.01 if "JPY" in self.symbol else 0.0001
        return abs(self.open_price - self.stop_loss) / divisor

    @property
    def reward_pips(self) -> float:
        if self.take_profit == 0:
            return 0
        divisor = 0.01 if "JPY" in self.symbol else 0.0001
        return abs(self.take_profit - self.open_price) / divisor

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "direction": self.direction,
            "volume": self.volume,
            "open_price": self.open_price,
            "current_price": self.current_price,
            "sl": self.stop_loss,
            "tp": self.take_profit,
            "pnl": self.pnl,
            "pnl_pips": self.pnl_pips,
            "magic": self.magic,
        }
