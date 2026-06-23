"""Data package for Noema — market data feeds and economic calendar."""

from noema.data.feed import MarketDataFeed
from noema.data.calendar import EconomicCalendar
from noema.data.event_calendar import (
    EconomicEvent,
    CalendarSnapshot,
    EventCalendarDataSource,
    PAIR_CURRENCY_MAP,
    CURRENCY_PAIR_MAP,
    get_currencies_for_pair,
    get_pairs_for_currency,
    create_event_calendar,
)
from noema.data.event_study import (
    EventStudy,
    EventImpactResult,
    EventStudyRecord,
)

__all__ = [
    "MarketDataFeed",
    "EconomicCalendar",
    "EconomicEvent",
    "CalendarSnapshot",
    "EventCalendarDataSource",
    "PAIR_CURRENCY_MAP",
    "CURRENCY_PAIR_MAP",
    "get_currencies_for_pair",
    "get_pairs_for_currency",
    "create_event_calendar",
    "EventStudy",
    "EventImpactResult",
    "EventStudyRecord",
]
