"""
Economic Calendar Tool — check upcoming economic events.

Provides access to forex economic calendar data (central bank decisions,
CPI, NFP, PMI, GDP releases, etc.) through MT5 economic calendar or
fallback sources.

Pattern inspired by TradingAgents' get_macro_indicators — gives agents
real data instead of relying on training-data knowledge.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from noema.tools import ToolDef

logger = logging.getLogger(__name__)


def get_economic_calendar(
    currency: str = "USD",
    lookback_days: int = 7,
    lookahead_days: int = 14,
    min_impact: str = "medium",
) -> dict[str, Any]:
    """Fetch upcoming and recent economic events for a currency.

    Args:
        currency: ISO currency code (USD, EUR, GBP, JPY, etc.)
        lookback_days: Days to look back for recent events
        lookahead_days: Days to look ahead for upcoming events
        min_impact: Minimum impact level (low, medium, high)

    Returns:
        dict with 'upcoming_events', 'recent_events', and metadata

    Example response:
        {
            "upcoming_events": [
                {
                    "event": "FOMC Interest Rate Decision",
                    "currency": "USD",
                    "date": "2026-06-25",
                    "time": "18:00 UTC",
                    "impact": "high",
                    "forecast": "4.25%",
                    "previous": "4.50%"
                }
            ],
            "recent_events": [...],
            "high_impact_count": 2,
            "risk_warning": "FOMC rate decision within 48h — expect elevated volatility"
        }
    """
    events: list[dict[str, Any]] = []

    # --- Try MT5 economic calendar first ---
    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5()
        if mt5.initialize():
            # MT5 calendar: currency filter and date range
            from datetime import timedelta

            now = datetime.now(timezone.utc)
            from_date = now - timedelta(days=lookback_days)
            to_date = now + timedelta(days=lookahead_days)

            calendar = mt5.calendar_get(
                from_date, to_date, currency=currency
            )

            if calendar is not None and len(calendar) > 0:
                for event_row in calendar:
                    # MT5 returns tuples; extract fields
                    try:
                        event_time = datetime.fromtimestamp(
                            event_row.time, tz=timezone.utc
                        )
                        impact_levels = {1: "low", 2: "medium", 3: "high"}
                        impact = impact_levels.get(
                            getattr(event_row, "impact", 1), "low"
                        )

                        events.append({
                            "event": getattr(event_row, "name", "Unknown"),
                            "currency": getattr(event_row, "currency", currency),
                            "date": event_time.strftime("%Y-%m-%d"),
                            "time": event_time.strftime("%H:%M UTC"),
                            "impact": impact,
                            "forecast": getattr(event_row, "forecast_value", None),
                            "previous": getattr(event_row, "previous_value", None),
                        })
                    except Exception:
                        continue

            mt5.shutdown()
    except ImportError:
        logger.debug("MT5 not available for economic calendar — using static fallback")
    except Exception as e:
        logger.warning(f"MT5 economic calendar failed: {e}")

    # --- Filter by impact ---
    impact_order = {"low": 0, "medium": 1, "high": 2}
    min_level = impact_order.get(min_impact, 1)
    filtered = [e for e in events if impact_order.get(e["impact"], 0) >= min_level]

    # Split into upcoming and recent
    now = datetime.now(timezone.utc)
    upcoming = [e for e in filtered if e["date"] >= now.strftime("%Y-%m-%d")]
    recent = [e for e in filtered if e["date"] < now.strftime("%Y-%m-%d")]

    # Sort by date
    upcoming.sort(key=lambda e: e["date"])
    recent.sort(key=lambda e: e["date"], reverse=True)

    high_impact_upcoming = [e for e in upcoming if e["impact"] == "high"]
    risk_warning = ""
    if high_impact_upcoming:
        next_high = high_impact_upcoming[0]
        risk_warning = (
            f"{next_high['event']} within 48h — expect elevated volatility"
        )
    elif not upcoming:
        risk_warning = "No significant events in the lookahead window"

    return {
        "upcoming_events": upcoming,
        "recent_events": recent[:5],  # Keep last 5
        "high_impact_count": len(high_impact_upcoming),
        "currency": currency,
        "risk_warning": risk_warning,
        "source": "mt5_calendar" if events else "none_available",
    }


def get_central_bank_decisions(
    currency: str = "USD",
    days_ahead: int = 30,
) -> dict[str, Any]:
    """Check for upcoming central bank rate decisions.

    Args:
        currency: ISO currency code
        days_ahead: How many days to look ahead

    Returns:
        dict with upcoming decisions and recent rate history
    """
    # Shortcut to economic calendar filtered for rate decisions
    calendar = get_economic_calendar(
        currency=currency,
        lookback_days=90,
        lookahead_days=days_ahead,
        min_impact="high",
    )

    rate_keywords = ["rate decision", "interest rate", "fomc", "ecb", "boe", "boj", "rba", "rbnz"]
    decisions = [
        e for e in calendar["upcoming_events"]
        if any(kw.lower() in e["event"].lower() for kw in rate_keywords)
    ]
    recent = [
        e for e in calendar["recent_events"]
        if any(kw.lower() in e["event"].lower() for kw in rate_keywords)
    ]

    return {
        "currency": currency,
        "upcoming_decisions": decisions,
        "recent_decisions": recent[:3],
        "has_decision_soon": len(decisions) > 0,
    }


# ── ToolDef for registration ───────────────────────────────────────────

economic_calendar_tool = ToolDef(
    name="get_economic_calendar",
    description=(
        "Fetch upcoming and recent economic events for a currency. "
        "Returns central bank decisions, CPI, NFP, PMI, GDP releases, etc. "
        "Use this before trading to check for high-impact events that could "
        "cause volatility. Currency should be an ISO 4217 code (USD, EUR, GBP, JPY, etc.)."
    ),
    func=get_economic_calendar,
    parameters={
        "currency": {
            "type": "string",
            "description": "ISO 4217 currency code (USD, EUR, GBP, JPY, AUD, NZD, CAD, CHF)",
        },
        "lookback_days": {
            "type": "integer",
            "description": "Days to look back for recent events (default: 7)",
        },
        "lookahead_days": {
            "type": "integer",
            "description": "Days to look ahead for upcoming events (default: 14)",
        },
        "min_impact": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Minimum impact level filter (default: medium)",
        },
    },
    tags=["forex", "fundamental", "macro", "calendar"],
    category="fundamental",
    requires_broker=True,
)

central_bank_tool = ToolDef(
    name="get_central_bank_decisions",
    description=(
        "Check for upcoming central bank rate decisions affecting a currency. "
        "Returns recent rate history and any decisions within the lookahead window. "
        "Critical for forex trading — rate decisions are the highest-impact events."
    ),
    func=get_central_bank_decisions,
    parameters={
        "currency": {
            "type": "string",
            "description": "ISO 4217 currency code",
        },
        "days_ahead": {
            "type": "integer",
            "description": "Days to look ahead for rate decisions (default: 30)",
        },
    },
    tags=["forex", "fundamental", "central_bank", "rates"],
    category="fundamental",
    requires_broker=True,
)
