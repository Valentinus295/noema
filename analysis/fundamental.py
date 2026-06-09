"""Fundamental analysis module for VMPM.

Analyzes economic data, news events, and macro indicators
to determine fundamental bias for currencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class FundamentalBias(Enum):
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


class ImpactLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EconomicEvent:
    """A single economic calendar event."""
    name: str
    currency: str
    impact: ImpactLevel
    forecast: float | None = None
    actual: float | None = None
    previous: float | None = None
    timestamp: float = 0.0

    @property
    def surprise(self) -> float | None:
        """Calculate actual vs forecast surprise."""
        if self.actual is None or self.forecast is None:
            return None
        return self.actual - self.forecast

    @property
    def sentiment(self) -> str:
        """Determine if the release was bullish/bearish for the currency."""
        s = self.surprise
        if s is None:
            return "pending"
        # Generic: higher actual = hawkish = bullish for currency
        # Context-dependent overrides happen at agent level
        if s > 0:
            return "bullish"
        elif s < 0:
            return "bearish"
        return "neutral"


@dataclass
class FundamentalReport:
    """Output from fundamental analysis."""
    bias: FundamentalBias
    currency_scores: dict[str, float] = field(default_factory=dict)
    events_analyzed: int = 0
    high_impact_events: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0


class FundamentalAnalyzer:
    """Analyzes economic calendar and macro data to determine fundamental bias.

    Scoring system:
    - Each high-impact surprise contributes +/- 3 points
    - Each medium-impact surprise contributes +/- 2 points
    - Each low-impact surprise contributes +/- 1 point
    - Contextual interpretation adjusts scores
    """

    # Base points per impact level
    IMPACT_SCORES = {
        ImpactLevel.HIGH: 3.0,
        ImpactLevel.MEDIUM: 2.0,
        ImpactLevel.LOW: 1.0,
    }

    # Key events that override normal scoring
    CONTEXT_OVERRIDES = {
        "interest_rate_decision": 2.0,   # Extra weight
        "nfp": 2.0,
        "cpi": 1.5,
        "gdp": 1.5,
        "fomc": 2.0,
    }

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(component="fundamental")

    def analyze_events(
        self, events: list[EconomicEvent], context: dict[str, Any] | None = None
    ) -> FundamentalReport:
        """Analyze a list of economic events and produce a fundamental report."""
        currency_scores: dict[str, float] = {}
        high_impact = []

        for event in events:
            score = self._score_event(event)
            currency_scores[event.currency] = currency_scores.get(event.currency, 0.0) + score

            if event.impact == ImpactLevel.HIGH and event.actual is not None:
                high_impact.append({
                    "name": event.name,
                    "currency": event.currency,
                    "actual": event.actual,
                    "forecast": event.forecast,
                    "surprise": event.surprise,
                    "sentiment": event.sentiment,
                })

        # Contextual adjustments
        if context:
            currency_scores = self._apply_context(currency_scores, context)

        # Determine overall bias (based on strongest currency pair spread)
        bias = self._determine_bias(currency_scores)

        reasoning = self._build_reasoning(currency_scores, high_impact)

        return FundamentalReport(
            bias=bias,
            currency_scores=currency_scores,
            events_analyzed=len(events),
            high_impact_events=high_impact,
            reasoning=reasoning,
            confidence=min(1.0, len(high_impact) * 0.15 + 0.3),
        )

    def _score_event(self, event: EconomicEvent) -> float:
        """Score a single economic event."""
        if event.actual is None or event.forecast is None:
            return 0.0

        surprise = event.surprise or 0.0
        base_score = self.IMPACT_SCORES.get(event.impact, 1.0)

        # Apply context override
        override = self.CONTEXT_OVERRIDES.get(event.name.lower().replace(" ", "_"), 0.0)
        multiplier = 1.0 + override

        # Normalize surprise (relative to forecast magnitude)
        if event.forecast != 0:
            relative_surprise = surprise / abs(event.forecast)
        else:
            relative_surprise = 0.0

        return base_score * multiplier * (1.0 if relative_surprise > 0 else -1.0 if relative_surprise < 0 else 0.0)


    def _apply_context(
        self, scores: dict[str, float], context: dict[str, Any]
    ) -> dict[str, float]:
        """Apply contextual interpretation to scores.

        Example: Positive CPI may not be bullish if markets expect rate cuts.
        """
        adjusted = scores.copy()

        market_expectation = context.get("market_regime", "")
        rate_direction = context.get("expected_rate_direction", "")

        # If market expects rate cuts, hawkish data is contrarian
        if rate_direction == "cutting":
            for curr in adjusted:
                if adjusted[curr] > 0:
                    adjusted[curr] *= 0.7  # Dampen bullish signals

        return adjusted

    def _determine_bias(self, scores: dict[str, float]) -> FundamentalBias:
        """Determine overall fundamental bias from currency scores."""
        if not scores:
            return FundamentalBias.NEUTRAL

        max_score = max(scores.values())
        min_score = min(scores.values())
        spread = max_score - min_score

        if spread > 8:
            # Strong imbalance
            strongest = max(scores, key=scores.get)
            if scores[strongest] > 0:
                return FundamentalBias.STRONG_BULLISH
            return FundamentalBias.STRONG_BEARISH
        elif spread > 4:
            strongest = max(scores, key=scores.get)
            if scores[strongest] > 0:
                return FundamentalBias.BULLISH
            return FundamentalBias.BEARISH

        return FundamentalBias.NEUTRAL

    def _build_reasoning(
        self, scores: dict[str, float], high_impact: list[dict]
    ) -> str:
        """Build human-readable reasoning."""
        parts = []

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        if sorted_scores:
            parts.append("Currency strength ranking:")
            for curr, score in sorted_scores:
                parts.append(f"  {curr}: {score:+.1f}")

        if high_impact:
            parts.append(f"\nHigh impact events ({len(high_impact)}):")
            for evt in high_impact[:5]:
                parts.append(
                    f"  {evt['name']} ({evt['currency']}): "
                    f"{evt['sentiment'].upper()} "
                    f"(actual={evt['actual']}, forecast={evt['forecast']})"
                )

        return "\n".join(parts)

