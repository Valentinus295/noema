"""FundamentalBiasAgent — hybrid: deterministic macro computations → optional LLM narrator.

Contract pinned in docs/ARCHITECTURE.md §2.

Updated: Uses FundamentalBiasOutput for type-safe LLM structured output.
The LLM contribution to bias_score is capped at ±0.05.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from noema.core.types import Bias, Direction
from noema.core.llm_structured import (
    FundamentalBiasOutput,
    LLMStructuredClient,
)

logger = structlog.get_logger(__name__)


@dataclass
class NewsEvent:
    event: str
    currency: str
    actual: float
    forecast: float
    prior: float
    timestamp: datetime


def _compute_taylor_rule(
    actual: float, forecast: float, prior: float, currency: str, config: dict[str, Any]
) -> float:
    r_star = config.get("r_star", 2.0)
    pi_target = config.get("pi_target", 2.0)
    y_gap = config.get("y_gap", 0.0)

    i_implied = r_star + pi_target + 0.5 * (actual - forecast) + 0.5 * y_gap
    return i_implied


def _compute_yield_differential(currency: str, yields: dict[str, float]) -> float:
    if currency not in yields:
        return 0.0
    return yields[currency]


def _determine_sentiment(actual: float, forecast: float, prior: float) -> Direction:
    surprise = actual - forecast

    if abs(surprise) < 0.1:
        return Direction("neutral")
    elif surprise > 0:
        return Direction("bullish")
    else:
        return Direction("bearish")


def _compute_bias_score(
    news_events: list[NewsEvent], yields: dict[str, float], config: dict[str, Any]
) -> dict[str, float]:
    scores: dict[str, float] = {}

    for event in news_events:
        sentiment = _determine_sentiment(event.actual, event.forecast, event.prior)
        yield_diff = _compute_yield_differential(event.currency, yields)

        impact = 1.0
        if "CPI" in event.event or "NFP" in event.event:
            impact = 1.5
        elif "PMI" in event.event:
            impact = 1.0
        elif "Retail" in event.event:
            impact = 0.8

        base_score = (
            0.1
            if sentiment == Direction("bullish")
            else -0.1
            if sentiment == Direction("bearish")
            else 0.0
        )
        score = base_score * impact + (yield_diff * 0.01)

        if event.currency in scores:
            scores[event.currency] += score
        else:
            scores[event.currency] = score

    return scores


async def fetch_news_events(broker: BrokerProtocol) -> list[NewsEvent]:
    await broker.connect()
    return []


async def compute_fundamental_bias(broker: BrokerProtocol, config: dict[str, Any]) -> list[Bias]:
    news_events = await fetch_news_events(broker)

    yields = {"USD": 4.5, "EUR": 3.5, "GBP": 4.0, "JPY": 0.5}

    scores = _compute_bias_score(news_events, yields, config)

    biases = []
    for currency, score in scores.items():
        clamped_score = max(-0.5, min(0.5, score))
        direction = (
            Direction("bullish")
            if clamped_score > 0
            else Direction("bearish")
            if clamped_score < 0
            else Direction("neutral")
        )

        biases.append(
            Bias(
                currency=currency,
                score=clamped_score,
                direction=direction,
                explanation=f"News impact: {len(news_events)} events, yield diff: {yields.get(currency, 0):.1f}%",
                stale=len(news_events) == 0,
                sources_count=len(news_events),
                computed_at_utc=datetime.now(timezone.utc),
            )
        )

    return biases


async def narrate_fundamental_bias(
    client: LLMStructuredClient,
    currency: str,
    deterministic_score: float,
    yields: dict[str, float],
    news_events: list[dict[str, Any]] | None = None,
    model: str = "claude-4-sonnet",
    tier: str = "analysis",
) -> FundamentalBiasOutput:
    """Use LLM to narrate the fundamental bias with a strictly capped contribution.

    The LLM provides narrative explanation but its numeric contribution
    (bias_score) is hard-capped at ±0.05. The deterministic computation
    drives the main score; LLM only adds nuance within the cap.

    Args:
        client: LLMStructuredClient instance
        currency: Currency code (e.g., 'USD')
        deterministic_score: Pre-computed deterministic bias score
        yields: Current yield data
        news_events: Recent news events (optional)
        model: Model name
        tier: Model tier for config lookup

    Returns:
        FundamentalBiasOutput with bias_score clamped to [-0.05, 0.05]
    """
    news_summary = ""
    if news_events:
        news_lines = []
        for ev in news_events[:5]:
            news_lines.append(
                f"  - {ev.get('event', 'Unknown')}: actual={ev.get('actual', 'N/A')} "
                f"forecast={ev.get('forecast', 'N/A')} prior={ev.get('prior', 'N/A')}"
            )
        news_summary = "\n".join(news_lines)
    else:
        news_summary = "  No recent news events available."

    prompt = f"""Analyze the fundamental bias for {currency}.

Deterministic bias score (pre-computed): {deterministic_score:.4f}
Current yields: {yields}

Recent news events:
{news_summary}

Provide:
1. A bias_score between -0.05 and +0.05 (this is the LLM contribution ONLY — keep it small)
2. Overall fundamental direction (bullish/bearish/neutral)
3. Confidence in your assessment (0.0-1.0)
4. Reasoning explaining the fundamental view
5. Key drivers (top 1-3 factors)
6. Data quality assessment (are you working with stale data?)"""

    system_prompt = """You are a fundamental analyst for forex markets.
Your job: Narrate the fundamental bias for a currency.

CRITICAL: Your bias_score MUST be between -0.05 and +0.05.
This represents only your qualitative adjustment on top of the deterministic computation.
Do NOT output a large score — the deterministic math handles the heavy lifting.

Be concise, evidence-based, and honest about data quality."""

    result = await client.complete(
        model=model,
        prompt=prompt,
        response_model=FundamentalBiasOutput,
        system_prompt=system_prompt,
        tier=tier,
        agent_name="fundamental-bias",
    )

    # Secondary enforcement of the 0.05 cap (Pydantic validator is first line)
    result = client.validate_bias_contribution(result)

    logger.info(
        "fundamental_bias_narrated",
        currency=currency,
        deterministic_score=round(deterministic_score, 4),
        llm_contribution=round(result.bias_score, 4),
        direction=result.direction.value,
        confidence=round(result.confidence, 2),
        data_quality=round(result.data_quality, 2),
    )

    return result


def merge_bias_with_narrative(
    deterministic_bias: Bias,
    llm_output: FundamentalBiasOutput,
) -> Bias:
    """Merge the deterministic Bias with LLM narrative output.

    The deterministic score is the anchor. The LLM contribution (±0.05)
    is added to provide nuance, and the LLM explanation replaces the
    auto-generated one.

    Args:
        deterministic_bias: Pre-computed deterministic Bias
        llm_output: LLM's FundamentalBiasOutput

    Returns:
        Merged Bias with LLM-enhanced explanation and capped score adjustment
    """
    adjusted_score = deterministic_bias.score + llm_output.bias_score
    adjusted_score = max(-0.5, min(0.5, adjusted_score))

    return Bias(
        currency=deterministic_bias.currency,
        score=adjusted_score,
        direction=deterministic_bias.direction,
        explanation=llm_output.reasoning,
        stale=llm_output.stale or deterministic_bias.stale,
        sources_count=deterministic_bias.sources_count,
        computed_at_utc=deterministic_bias.computed_at_utc,
    )
