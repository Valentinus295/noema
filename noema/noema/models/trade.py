"""Trade model — represents a single trade through its lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Trade:
    """Represents a trade from signal to close."""
    pair: str = ""
    direction: str = ""           # "long" or "short"
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    lot_size: float = 0.01
    pnl: float = 0.0
    ticket: int = 0
    session: str = ""
    market_regime: str = ""
    trend: str = ""
    rsi_at_entry: float = 50.0
    candlestick_pattern: str = ""
    order_block_type: str = ""
    confidence: float = 0.0
    risk_reward: float = 0.0
    status: str = "pending"       # pending, open, closed, cancelled
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    decision_reasoning: str = ""
    agent_reports: dict[str, Any] = field(default_factory=dict)

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def duration_seconds(self) -> float | None:
        if self.opened_at and self.closed_at:
            return (self.closed_at - self.opened_at).total_seconds()
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair": self.pair,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "lot_size": self.lot_size,
            "pnl": self.pnl,
            "ticket": self.ticket,
            "session": self.session,
            "market_regime": self.market_regime,
            "trend": self.trend,
            "rsi_at_entry": self.rsi_at_entry,
            "candlestick_pattern": self.candlestick_pattern,
            "order_block_type": self.order_block_type,
            "confidence": self.confidence,
            "risk_reward": self.risk_reward,
            "status": self.status,
            "outcome": "win" if self.pnl > 0 else "loss",
        }
