"""Economic calendar data for VMPM fundamental analysis.

Fetches upcoming economic events from free APIs or provides
static fallback data for testing.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class EconomicCalendar:
    """Provides economic calendar events for fundamental analysis."""

    # Key events with typical impact levels
    KEY_EVENTS = {
        "interest_rate_decision": "high",
        "nfp": "high",
        "cpi": "high",
        "gdp": "high",
        "fomc": "high",
        "employment_change": "high",
        "manufacturing_pmi": "medium",
        "retail_sales": "medium",
        "consumer_confidence": "medium",
        "trade_balance": "medium",
        "housing_starts": "low",
        "building_permits": "low",
    }

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(component="calendar")

    async def get_events(
        self, currencies: list[str] | None = None, days_ahead: int = 7
    ) -> list[dict[str, Any]]:
        """Get upcoming economic events.

        Tries fetching from free API, falls back to sample data.
        """
        events = await self._fetch_from_api(currencies, days_ahead)
        if not events:
            events = self._generate_sample_events(currencies)
        return events

    async def _fetch_from_api(
        self, currencies: list[str] | None, days_ahead: int
    ) -> list[dict[str, Any]]:
        """Try to fetch from a free economic calendar API."""
        try:
            import aiohttp
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        events = []
                        for item in data:
                            event = {
                                "name": item.get("title", ""),
                                "currency": item.get("country", ""),
                                "impact": item.get("impact", "").lower(),
                                "forecast": self._safe_float(item.get("forecast")),
                                "actual": self._safe_float(item.get("actual")),
                                "previous": self._safe_float(item.get("previous")),
                            }
                            if currencies and event["currency"] not in currencies:
                                continue
                            events.append(event)
                        return events
        except Exception as exc:
            self._logger.debug("api_fetch_failed", error=str(exc))
        return []

    def _generate_sample_events(
        self, currencies: list[str] | None
    ) -> list[dict[str, Any]]:
        """Generate sample economic events for testing."""
        import random
        random.seed(int(time.time() / 86400))  # Same events per day

        major_currencies = currencies or ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF"]
        events = []

        # Simulate 2-4 high impact events per day
        event_names = [
            ("Interest Rate Decision", "high"),
            ("CPI", "high"),
            ("NFP", "high"),
            ("GDP", "high"),
            ("Manufacturing PMI", "medium"),
            ("Retail Sales", "medium"),
            ("Consumer Confidence", "medium"),
            ("Trade Balance", "low"),
        ]

        for _ in range(random.randint(2, 4)):
            name, impact = random.choice(event_names)
            curr = random.choice(major_currencies)
            forecast = round(random.uniform(-2, 5), 1)
            actual = round(forecast + random.uniform(-1, 1), 1)
            previous = round(forecast + random.uniform(-0.5, 0.5), 1)

            events.append({
                "name": name,
                "currency": curr,
                "impact": impact,
                "forecast": forecast,
                "actual": actual,
                "previous": previous,
            })

        return events

    def _safe_float(self, val: Any) -> float | None:
        """Safely convert value to float."""
        if val is None or val == "" or val == "—":
            return None
        try:
            return float(str(val).replace(",", ""))
        except (ValueError, TypeError):
            return None
