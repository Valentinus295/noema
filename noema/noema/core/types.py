"""Shared domain types. Pydantic v2 for cross-agent validation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


Direction = Literal["bullish", "bearish", "neutral"]
Timeframe = Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]


class _Base(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bias(_Base):
    """Fundamental currency bias. Magnitude clamped per docs/SECURITY.md.

    The LLM narrates `explanation` only — the numeric `score` is Python-computed.
    """
    currency: str = Field(min_length=3, max_length=4)
    score: float = Field(ge=-0.5, le=0.5)   # security clamp
    direction: Direction
    explanation: str = Field(max_length=2000)
    stale: bool = False
    sources_count: int = Field(ge=0)        # for ≥2 corroboration rule
    computed_at_utc: datetime


class Verdict(_Base):
    """Per-agent technical verdict feeding ConfluenceAgent."""
    agent: str
    symbol: str
    timeframe: Timeframe
    direction: Direction
    strength: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=500)


class Setup(_Base):
    """Output of ConfluenceAgent. Passed to PortfolioAgent → RiskAgent."""
    symbol: str
    direction: Direction
    score: float = Field(ge=0.0, le=1.0)
    entry_zone_lo: float
    entry_zone_hi: float
    sl_reference: float           # structure low/high before ATR buffer
    tp_reference: float           # next liquidity pool
    components: dict[str, float]  # {"trend": 0.8, "structure": 0.9, ...}
    settings_hash: str            # config content hash at decision time
    git_sha: str
    proposed_at_utc: datetime


@dataclass(frozen=True, slots=True)
class Bar:
    """Single OHLCV bar. Used by indicators and the 7-agent pipeline."""
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
