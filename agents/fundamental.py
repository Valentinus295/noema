"""FundamentalBiasAgent — hybrid: deterministic macro computations → optional LLM narrator.

Contract pinned in docs/ARCHITECTURE.md §2.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from vmpm.core.types import Bias, Direction
from vmpm.broker.base import BrokerProtocol


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
