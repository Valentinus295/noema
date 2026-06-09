"""Database models for VMPM trade history and knowledge base."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Float, Integer, String, DateTime, Text
from vmpm.database import Base


class TradeRecord(Base):
    """Persisted trade record."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket = Column(Integer, nullable=True)
    pair = Column(String(10), nullable=False)
    direction = Column(String(5), nullable=False)
    volume = Column(Float, nullable=False)
    open_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    session = Column(String(20), nullable=True)
    market_regime = Column(String(30), nullable=True)
    trend = Column(String(15), nullable=True)
    rsi_at_entry = Column(Float, nullable=True)
    candlestick_pattern = Column(String(30), nullable=True)
    order_block_type = Column(String(15), nullable=True)
    confidence = Column(Float, nullable=True)
    risk_reward = Column(Float, nullable=True)
    decision_reasoning = Column(Text, nullable=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(10), default="open")  # open, closed, cancelled


class KnowledgeEntry(Base):
    """Learning system knowledge entry."""
    __tablename__ = "knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(50), nullable=False)  # session, pattern, regime
    key = Column(String(100), nullable=False)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    avg_confidence = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=datetime.utcnow)


class DailyStats(Base):
    """Daily performance statistics."""
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, unique=True)
    trades_taken = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
