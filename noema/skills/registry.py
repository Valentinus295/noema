"""Skill Registry — 15 concrete trading skills catalog.

Each skill is a named, categorized capability with:
- Activation conditions (when the skill can be applied)
- Parameters (configurable thresholds/periods)
- Input requirements (what data the skill needs)
- Output schema (what the skill produces)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SkillCategory(str, Enum):
    TECHNICAL = "technical"       # TA indicators, patterns, S/R levels
    STRUCTURAL = "structural"    # SMC: order blocks, FVG, liquidity
    FUNDAMENTAL = "fundamental"  # Macro, sentiment, news, events
    RISK = "risk"                # Sizing, hedging, correlation


@dataclass
class Skill:
    """A concrete trading skill — an atomic capability.

    Skills are the building blocks that the Composer assembles into setups.
    Each skill has a unique ID, category, activation conditions, and parameters.
    """
    skill_id: str
    name: str
    category: SkillCategory
    description: str
    activation_conditions: dict[str, Any]  # e.g. {"trend": "defined", "timeframe": "H4"}
    default_parameters: dict[str, Any] = field(default_factory=dict)
    required_inputs: list[str] = field(default_factory=list)  # e.g. ["ohlcv", "rsi"]
    produces_outputs: list[str] = field(default_factory=list)  # e.g. ["signal", "confidence"]
    priority: int = 0  # Higher = applied first in a setup

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "activation_conditions": self.activation_conditions,
            "default_parameters": self.default_parameters,
            "required_inputs": self.required_inputs,
            "produces_outputs": self.produces_outputs,
            "priority": self.priority,
        }


class SkillRegistry:
    """Central registry of all 15 trading skills.

    Skills are divided into 4 categories:
    - Technical (5 skills)
    - Structural/SMC (4 skills)
    - Fundamental (3 skills)
    - Risk (3 skills)
    """

    # ── Technical Skills (5) ─────────────────────────────────────────

    SKILL_RSI_DIVERGENCE = Skill(
        skill_id="ta_rsi_divergence",
        name="RSI Divergence Detection",
        category=SkillCategory.TECHNICAL,
        description="Detect bullish/bearish RSI divergence against price for reversal signals",
        activation_conditions={"trend": "defined", "timeframe": "H4"},
        default_parameters={"rsi_period": 14, "divergence_lookback": 20},
        required_inputs=["ohlcv", "rsi"],
        produces_outputs=["signal", "confidence", "divergence_type"],
        priority=10,
    )

    SKILL_TREND_FOLLOWING = Skill(
        skill_id="ta_trend_following",
        name="Trend Following (EMA Cross)",
        category=SkillCategory.TECHNICAL,
        description="50/200 EMA crossover with trend confirmation on H4/D1",
        activation_conditions={"timeframe": "H4"},
        default_parameters={"ema_fast": 50, "ema_slow": 200, "min_separation_pct": 0.5},
        required_inputs=["ohlcv", "ema_50", "ema_200"],
        produces_outputs=["signal", "confidence", "trend_strength"],
        priority=5,
    )

    SKILL_SUPPORT_RESISTANCE = Skill(
        skill_id="ta_support_resistance",
        name="Support/Resistance Level Trading",
        category=SkillCategory.TECHNICAL,
        description="Trade bounces off key S/R levels with confirmation on M15",
        activation_conditions={"levels_defined": True},
        default_parameters={"zone_width_pips": 10, "confirmation_touches": 2},
        required_inputs=["ohlcv", "sr_levels"],
        produces_outputs=["signal", "confidence", "level_type", "level_price"],
        priority=8,
    )

    SKILL_CANDLESTICK_PATTERNS = Skill(
        skill_id="ta_candlestick_patterns",
        name="Candlestick Pattern Recognition",
        category=SkillCategory.TECHNICAL,
        description="Detect 8 reversal/continuation candlestick patterns on entry timeframe",
        activation_conditions={"timeframe": "H1"},
        default_parameters={"min_pattern_confidence": 0.6},
        required_inputs=["ohlcv"],
        produces_outputs=["signal", "confidence", "pattern_type"],
        priority=6,
    )

    SKILL_MOMENTUM_CONFIRMATION = Skill(
        skill_id="ta_momentum_confirmation",
        name="Multi-Timeframe Momentum Confirmation",
        category=SkillCategory.TECHNICAL,
        description="Confirm momentum alignment across M15/H1/D1 using RSI",
        activation_conditions={"all_timeframes_available": True},
        default_parameters={"rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70},
        required_inputs=["rsi_m15", "rsi_h1", "rsi_d1"],
        produces_outputs=["signal", "confidence", "alignment_score"],
        priority=7,
    )

    # ── Structural / SMC Skills (4) ──────────────────────────────────

    SKILL_ORDER_BLOCK = Skill(
        skill_id="smc_order_block",
        name="Order Block Detection",
        category=SkillCategory.STRUCTURAL,
        description="Identify and trade from institutional order blocks (OB) on H4/H1",
        activation_conditions={"timeframe": "H4"},
        default_parameters={"min_block_size_pips": 15, "max_block_age_bars": 20},
        required_inputs=["ohlcv", "order_blocks"],
        produces_outputs=["signal", "confidence", "ob_type", "ob_price"],
        priority=12,
    )

    SKILL_FVG = Skill(
        skill_id="smc_fvg",
        name="Fair Value Gap (FVG) Trading",
        category=SkillCategory.STRUCTURAL,
        description="Trade imbalances via FVG fills on H1/M15",
        activation_conditions={"timeframe": "H1"},
        default_parameters={"min_gap_pips": 3, "max_gap_age_bars": 5},
        required_inputs=["ohlcv", "fvg_zones"],
        produces_outputs=["signal", "confidence", "fvg_type", "fvg_zone"],
        priority=9,
    )

    SKILL_LIQUIDITY_SWEEP = Skill(
        skill_id="smc_liquidity_sweep",
        name="Liquidity Sweep Recognition",
        category=SkillCategory.STRUCTURAL,
        description="Detect liquidity grabs at swing highs/lows before reversals",
        activation_conditions={"swing_points_defined": True, "timeframe": "H1"},
        default_parameters={"sweep_wick_pct": 0.3, "min_sweep_distance_pips": 20},
        required_inputs=["ohlcv", "swing_highs", "swing_lows"],
        produces_outputs=["signal", "confidence", "sweep_direction"],
        priority=11,
    )

    SKILL_MARKET_STRUCTURE = Skill(
        skill_id="smc_market_structure",
        name="Market Structure Break (BOS/CHoCH)",
        category=SkillCategory.STRUCTURAL,
        description="Identify Break of Structure and Change of Character for trend shifts",
        activation_conditions={"timeframe": "H4"},
        default_parameters={"min_break_pips": 10, "confirmation_bars": 2},
        required_inputs=["ohlcv", "swing_points"],
        produces_outputs=["signal", "confidence", "structure_type"],
        priority=15,
    )

    # ── Fundamental Skills (3) ───────────────────────────────────────

    SKILL_MACRO_BIAS = Skill(
        skill_id="fa_macro_bias",
        name="Macroeconomic Bias Assessment",
        category=SkillCategory.FUNDAMENTAL,
        description="Determine fundamental bias from interest rates, GDP, inflation data",
        activation_conditions={"macro_data_available": True},
        default_parameters={"bias_lookback_days": 30},
        required_inputs=["interest_rates", "gdp_growth", "inflation", "employment"],
        produces_outputs=["bias", "confidence", "bias_strength"],
        priority=4,
    )

    SKILL_SENTIMENT_ANALYSIS = Skill(
        skill_id="fa_sentiment_analysis",
        name="Market Sentiment Reading",
        category=SkillCategory.FUNDAMENTAL,
        description="Gauge market sentiment from COT data, retail positioning, volatility",
        activation_conditions={"sentiment_data_available": True},
        default_parameters={"cot_lookback_weeks": 4, "retail_sentiment_weight": 0.3},
        required_inputs=["cot_data", "retail_positioning", "vix"],
        produces_outputs=["signal", "confidence", "sentiment_score"],
        priority=3,
    )

    SKILL_EVENT_AWARENESS = Skill(
        skill_id="fa_event_awareness",
        name="Economic Event Awareness",
        category=SkillCategory.FUNDAMENTAL,
        description="Blackout trading around high-impact news events (NFP, FOMC, CPI)",
        activation_conditions={"calendar_available": True},
        default_parameters={"blackout_minutes": 30, "high_impact_only": True},
        required_inputs=["economic_calendar"],
        produces_outputs=["signal", "confidence", "event_risk"],
        priority=2,
    )

    # ── Risk Skills (3) ──────────────────────────────────────────────

    SKILL_POSITION_SIZING = Skill(
        skill_id="rm_position_sizing",
        name="Kelly-Optimal Position Sizing",
        category=SkillCategory.RISK,
        description="Size positions based on win rate, R:R, and account risk limits",
        activation_conditions={"account_known": True},
        default_parameters={"risk_pct": 0.01, "kelly_fraction": 0.25},
        required_inputs=["account_balance", "win_rate", "avg_rr"],
        produces_outputs=["lot_size", "confidence", "risk_amount"],
        priority=13,
    )

    SKILL_CORRELATION_CHECK = Skill(
        skill_id="rm_correlation_check",
        name="Portfolio Correlation Gate",
        category=SkillCategory.RISK,
        description="Prevent correlated trades from accumulating directional risk",
        activation_conditions={"open_positions": True},
        default_parameters={"max_correlation": 0.7, "max_same_direction": 2},
        required_inputs=["open_positions", "pair", "direction"],
        produces_outputs=["signal", "confidence", "correlation_warning"],
        priority=14,
    )

    SKILL_DRAWDOWN_PROTECTION = Skill(
        skill_id="rm_drawdown_protection",
        name="Dynamic Drawdown Protection",
        category=SkillCategory.RISK,
        description="Progressive position size reduction as drawdown increases",
        activation_conditions={"drawdown_known": True},
        default_parameters={"reduction_start_dd": 0.05, "full_stop_dd": 0.10},
        required_inputs=["current_drawdown", "max_drawdown_limit"],
        produces_outputs=["size_multiplier", "confidence", "risk_level"],
        priority=16,
    )

    # ── Registry ─────────────────────────────────────────────────────

    ALL_SKILLS: list[Skill] = [
        # Technical
        SKILL_RSI_DIVERGENCE,
        SKILL_TREND_FOLLOWING,
        SKILL_SUPPORT_RESISTANCE,
        SKILL_CANDLESTICK_PATTERNS,
        SKILL_MOMENTUM_CONFIRMATION,
        # Structural
        SKILL_ORDER_BLOCK,
        SKILL_FVG,
        SKILL_LIQUIDITY_SWEEP,
        SKILL_MARKET_STRUCTURE,
        # Fundamental
        SKILL_MACRO_BIAS,
        SKILL_SENTIMENT_ANALYSIS,
        SKILL_EVENT_AWARENESS,
        # Risk
        SKILL_POSITION_SIZING,
        SKILL_CORRELATION_CHECK,
        SKILL_DRAWDOWN_PROTECTION,
    ]

    _by_id: dict[str, Skill] = {s.skill_id: s for s in ALL_SKILLS}

    @classmethod
    def get(cls, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        return cls._by_id.get(skill_id)

    @classmethod
    def get_by_category(cls, category: SkillCategory) -> list[Skill]:
        """Get all skills in a category."""
        return [s for s in cls.ALL_SKILLS if s.category == category]

    @classmethod
    def get_all(cls) -> list[Skill]:
        """Get all registered skills."""
        return list(cls.ALL_SKILLS)

    @classmethod
    def get_ids_by_category(cls) -> dict[str, list[str]]:
        """Get skill IDs grouped by category."""
        result: dict[str, list[str]] = {}
        for s in cls.ALL_SKILLS:
            result.setdefault(s.category.value, []).append(s.skill_id)
        return result

    @classmethod
    def count(cls) -> int:
        """Total number of registered skills."""
        return len(cls.ALL_SKILLS)
