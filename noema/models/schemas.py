"""Pydantic schemas for all LLM-structured outputs in Noema.

Every LLM response is parsed into a Pydantic model. No free-text trust.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────

class TradeDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


class MarketRegime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class SessionType(str, Enum):
    ASIAN = "ASIAN"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP = "OVERLAP"
    OFF_HOURS = "OFF_HOURS"


# ── Analysis Schemas (LLM output for analysis agents) ───────────────

class TrendAnalysis(BaseModel):
    """Output from trend analysis (LLM-assisted)."""
    direction: TradeDirection
    strength: SignalStrength
    timeframe_alignment: dict[str, TradeDirection] = Field(
        description="Direction per timeframe, e.g. {'H4': 'BUY', 'D1': 'BUY'}"
    )
    key_levels: list[float] = Field(
        default_factory=list,
        description="Key price levels identified (EMA crossovers, etc.)"
    )
    reasoning: str = Field(min_length=10, max_length=500)


class StructureAnalysis(BaseModel):
    """Output from market structure analysis (LLM-assisted)."""
    regime: MarketRegime
    swing_highs: list[float] = Field(default_factory=list)
    swing_lows: list[float] = Field(default_factory=list)
    bos_direction: Optional[TradeDirection] = Field(
        None, description="Break of structure direction"
    )
    choch_direction: Optional[TradeDirection] = Field(
        None, description="Change of character direction"
    )
    reasoning: str = Field(min_length=10, max_length=500)


class InstitutionalAnalysis(BaseModel):
    """Output from institutional footprint analysis (LLM-assisted)."""
    order_blocks: list[dict[str, float]] = Field(
        default_factory=list,
        description="Detected order blocks: [{'high': 1.09, 'low': 1.085, 'type': 'demand'}]"
    )
    liquidity_zones: list[float] = Field(default_factory=list)
    fvg_zones: list[dict[str, float]] = Field(
        default_factory=list,
        description="Fair value gaps: [{'high': 1.09, 'low': 1.085}]"
    )
    direction: TradeDirection
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=10, max_length=500)


class SRAnalysis(BaseModel):
    """Output from support/resistance analysis."""
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    price_position: str = Field(
        description="Where price is relative to S/R, e.g. 'near_support', 'between', 'at_resistance'"
    )
    direction: TradeDirection
    reasoning: str = Field(min_length=10, max_length=500)


class MomentumAnalysis(BaseModel):
    """Output from momentum analysis (RSI, MACD, divergence)."""
    rsi_value: float = Field(ge=0, le=100)
    rsi_signal: SignalStrength
    macd_histogram: float
    macd_cross: Optional[TradeDirection] = None
    divergence: Optional[TradeDirection] = Field(
        None, description="Bullish or bearish divergence detected"
    )
    direction: TradeDirection
    reasoning: str = Field(min_length=10, max_length=500)


class PriceActionAnalysis(BaseModel):
    """Output from candlestick/price action analysis."""
    pattern_detected: Optional[str] = Field(
        None, description="Candlestick pattern name, e.g. 'bullish_engulfing'"
    )
    pattern_strength: SignalStrength
    direction: TradeDirection
    key_candles: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Notable candles: [{'index': -2, 'type': 'doji', 'significance': 'indecision'}]"
    )
    reasoning: str = Field(min_length=10, max_length=500)


# ── Decision Schemas (LLM output for decision agents) ───────────────

class TradeThesis(BaseModel):
    """Output from Trade Thesis Agent — the case FOR a trade."""
    direction: TradeDirection
    symbol: str = Field(pattern=r"^[A-Z]{6}$")
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    conviction: float = Field(ge=0.0, le=1.0, description="How strong is the thesis")
    narrative: str = Field(
        min_length=20, max_length=1000,
        description="The complete trade narrative — why this setup works"
    )
    key_risk: str = Field(
        min_length=5, max_length=200,
        description="The single biggest risk to this trade"
    )


class DevilsAdvocate(BaseModel):
    """Output from Devil's Advocate Agent — the case AGAINST a trade."""
    should_trade: bool
    objections: list[str] = Field(
        default_factory=list,
        description="Specific reasons NOT to trade"
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="What evidence is missing or unverified?"
    )
    worst_case_scenario: str = Field(
        min_length=10, max_length=300,
        description="What's the worst that could happen?"
    )
    confidence_reduction: float = Field(
        ge=0.0, le=0.5,
        description="How much should this reduce the CIO's confidence?"
    )
    reasoning: str = Field(min_length=10, max_length=500)


class CIODecision(BaseModel):
    """Output from CIO Agent — the final trade decision."""
    decision: TradeDirection
    symbol: str = Field(pattern=r"^[A-Z]{6}$")
    confidence: float = Field(ge=0.0, le=1.0)
    consensus_score: float = Field(
        ge=0.0, le=1.0,
        description="How much agents agree (0=all disagree, 1=unanimous)"
    )
    thesis_approved: bool
    devil_approved: bool
    risk_approved: bool
    final_reasoning: str = Field(
        min_length=20, max_length=800,
        description="CIO's complete reasoning for the decision"
    )
    dissenting_agents: list[str] = Field(
        default_factory=list,
        description="Agents that disagreed with the decision"
    )


# ── Execution Schemas ────────────────────────────────────────────────

class TradeParameters(BaseModel):
    """Validated trade parameters ready for execution."""
    symbol: str = Field(pattern=r"^[A-Z]{6}$")
    direction: TradeDirection
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: Optional[float] = Field(None, gt=0)
    lot_size: float = Field(gt=0, le=10.0)
    risk_amount: float = Field(ge=0, description="Dollar amount at risk")
    rr_ratio: float = Field(ge=0, description="Risk/reward ratio")
    order_type: str = Field(default="MARKET", pattern=r"^(MARKET|LIMIT|STOP)$")

    @field_validator("stop_loss")
    @classmethod
    def validate_sl(cls, v: float, info) -> float:
        """Ensure stop loss is on the correct side of entry."""
        return v

    @field_validator("take_profit")
    @classmethod
    def validate_tp(cls, v: float | None, info) -> float | None:
        """Ensure take profit is on the correct side of entry."""
        return v


class ExecutionReport(BaseModel):
    """Report from order execution."""
    success: bool
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_time: Optional[datetime] = None
    slippage_pips: float = 0.0
    error: Optional[str] = None
    trade_params: Optional[TradeParameters] = None


# ── Learning Schemas ─────────────────────────────────────────────────

class TradeReflection(BaseModel):
    """Output from Learning Agent — post-trade reflection."""
    trade_id: str
    symbol: str
    direction: TradeDirection
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    outcome: str = Field(description="WIN, LOSS, BREAKEVEN, OPEN")

    what_worked: list[str] = Field(
        default_factory=list,
        description="What aspects of the analysis were correct"
    )
    what_failed: list[str] = Field(
        default_factory=list,
        description="What aspects were wrong or misleading"
    )
    lesson_learned: str = Field(
        min_length=20, max_length=500,
        description="The key takeaway for future trades"
    )
    pattern_type: Optional[str] = Field(
        None,
        description="The type of pattern/setup, e.g. 'trend_continuation', 'reversal'"
    )
    should_repeat: bool = Field(
        description="Should we look for this type of setup again?"
    )
    adjustments: list[str] = Field(
        default_factory=list,
        description="Specific adjustments for next time"
    )


# ── Helper: Build system prompts from schemas ────────────────────────

def schema_prompt(model: type[BaseModel]) -> str:
    """Generate a JSON schema instruction for an LLM from a Pydantic model.

    Used in system prompts to tell the LLM exactly what format to output.
    """
    schema = model.model_json_schema()
    return (
        f"You MUST respond with valid JSON matching this schema:\n"
        f"```json\n{json.dumps(schema, indent=2)}\n```\n"
        f"Do NOT include any text outside the JSON block."
    )


import json  # noqa: E402 (needed for schema_prompt)
