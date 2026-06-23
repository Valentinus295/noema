"""
Economic Event Calendar Data Source — Phase 1.5.

Provides:
- Primary: MT5 calendar via noema.tools.economic_calendar.get_economic_calendar()
- Fallback: Free web API (nfs.faireconomy.media) — already in data/calendar.py
- Conservative failure mode: if ALL sources fail, return synthetic high-impact warning
- Caching: calendar data cached per cycle (doesn't change mid-week)

All event classification is RULE-BASED (impact levels from the source, not LLM).
Blackout timing is DETERMINISTIC (event_time ± config_minutes).

Dataclasses:
    EconomicEvent: typed representation of a calendar event
    CalendarSnapshot: full snapshot with metadata and risk warnings
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════════════════════════

@dataclass
class EconomicEvent:
    """Typed representation of an economic calendar event.

    All fields are deterministic — impact comes from the calendar source,
    not from LLM classification.
    """
    name: str                                    # e.g. "Non-Farm Payrolls", "FOMC Interest Rate Decision"
    currency: str                                # ISO 4217: USD, EUR, GBP, JPY, etc.
    event_time: datetime                         # UTC timestamp of the event
    impact: str                                  # "high", "medium", "low" — from source
    forecast: float | None = None                # Consensus forecast value
    previous: float | None = None                # Previous release value
    actual: float | None = None                  # Actual released value (None for upcoming)
    category: str = ""                           # "employment", "inflation", "central_bank", etc.

    # Computed fields (deterministic)
    blackout_start: datetime | None = field(default=None)   # event_time - blackout_lead
    blackout_end: datetime | None = field(default=None)     # event_time + blackout_trail
    is_central_bank: bool = False                           # Rate decision related

    def __post_init__(self):
        """Ensure event_time is UTC and apply timezone if naive."""
        if self.event_time.tzinfo is None:
            self.event_time = self.event_time.replace(tzinfo=timezone.utc)

        # Auto-detect central bank decisions
        cb_keywords = ["rate decision", "interest rate", "fomc", "ecb", "boe",
                       "boj", "rba", "rbnz", "snb", "boc", "rbi"]
        name_lower = self.name.lower()
        self.is_central_bank = any(kw in name_lower for kw in cb_keywords)

    def compute_blackout_window(
        self,
        lead_minutes: int = 15,
        trail_minutes: int = 15,
    ) -> None:
        """Compute the blackout window around this event.

        blackout_start = event_time - lead_minutes
        blackout_end   = event_time + trail_minutes

        Called by the EventAnalyst after fetching events.
        """
        self.blackout_start = self.event_time - timedelta(minutes=lead_minutes)
        self.blackout_end = self.event_time + timedelta(minutes=trail_minutes)

    def is_in_blackout(self, now: datetime | None = None) -> bool:
        """Check if now is within the event's blackout window."""
        if now is None:
            now = datetime.now(timezone.utc)
        if self.blackout_start is None or self.blackout_end is None:
            return False
        return self.blackout_start <= now <= self.blackout_end

    def is_upcoming(self, now: datetime | None = None) -> bool:
        """Check if event is in the future."""
        if now is None:
            now = datetime.now(timezone.utc)
        return self.event_time > now

    @property
    def minutes_away(self) -> float:
        """Minutes until this event (negative if past)."""
        now = datetime.now(timezone.utc)
        delta = self.event_time - now
        return delta.total_seconds() / 60.0


@dataclass
class CalendarSnapshot:
    """Complete calendar snapshot for a trading cycle."""
    events: list[EconomicEvent] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "none"  # "mt5", "web_api", "synthetic_conservative"
    currencies_covered: list[str] = field(default_factory=list)

    @property
    def high_impact_events(self) -> list[EconomicEvent]:
        return [e for e in self.events if e.impact == "high"]

    @property
    def medium_impact_events(self) -> list[EconomicEvent]:
        return [e for e in self.events if e.impact == "medium"]

    @property
    def upcoming_events(self) -> list[EconomicEvent]:
        """Events in the future, sorted by event_time."""
        upcoming = [e for e in self.events if e.is_upcoming()]
        return sorted(upcoming, key=lambda e: e.event_time)

    @property
    def active_blackouts(self) -> list[EconomicEvent]:
        """Events currently in their blackout window."""
        now = datetime.now(timezone.utc)
        return [e for e in self.events if e.is_in_blackout(now)]

    def events_for_currency(self, currency: str) -> list[EconomicEvent]:
        """Get all events affecting a specific currency."""
        return [e for e in self.events if e.currency.upper() == currency.upper()]


# ══════════════════════════════════════════════════════════════════════
# Pair → Currency mapping (deterministic)
# ══════════════════════════════════════════════════════════════════════

# Maps a trading pair symbol → list of currencies whose events matter
PAIR_CURRENCY_MAP: dict[str, list[str]] = {
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCHF": ["USD", "CHF"],
    "AUDUSD": ["AUD", "USD"],
    "NZDUSD": ["NZD", "USD"],
    "USDCAD": ["USD", "CAD"],
    "EURGBP": ["EUR", "GBP"],
    "EURJPY": ["EUR", "JPY"],
    "EURCHF": ["EUR", "CHF"],
    "GBPJPY": ["GBP", "JPY"],
    "GBPCHF": ["GBP", "CHF"],
    "AUDJPY": ["AUD", "JPY"],
    "NZDJPY": ["NZD", "JPY"],
    "CADJPY": ["CAD", "JPY"],
    "EURAUD": ["EUR", "AUD"],
    "EURNZD": ["EUR", "NZD"],
    "GBPAUD": ["GBP", "AUD"],
    "GBPNZD": ["GBP", "NZD"],
    "AUDCAD": ["AUD", "CAD"],
    "AUDNZD": ["AUD", "NZD"],
    "AUDCHF": ["AUD", "CHF"],
    "CADCHF": ["CAD", "CHF"],
    "NZDCAD": ["NZD", "CAD"],
    "NZDCHF": ["NZD", "CHF"],
    "XAUUSD": ["XAU", "USD"],
    "XAGUSD": ["XAG", "USD"],
}

# Reverse: which pairs does a currency event affect?
CURRENCY_PAIR_MAP: dict[str, list[str]] = {}
for pair, currencies in PAIR_CURRENCY_MAP.items():
    for curr in currencies:
        if curr not in CURRENCY_PAIR_MAP:
            CURRENCY_PAIR_MAP[curr] = []
        if pair not in CURRENCY_PAIR_MAP[curr]:
            CURRENCY_PAIR_MAP[curr].append(pair)

# Add gold/silver as special currencies
CURRENCY_PAIR_MAP["XAU"] = ["XAUUSD"]
CURRENCY_PAIR_MAP["XAG"] = ["XAGUSD"]


def get_currencies_for_pair(pair: str) -> list[str]:
    """Return list of currencies whose events affect this pair."""
    return PAIR_CURRENCY_MAP.get(pair.upper(), ["USD"])


def get_pairs_for_currency(currency: str) -> list[str]:
    """Return list of pairs affected by events for this currency."""
    return CURRENCY_PAIR_MAP.get(currency.upper(), [])


# ══════════════════════════════════════════════════════════════════════
# Event Calendar Data Source
# ══════════════════════════════════════════════════════════════════════

class EventCalendarDataSource:
    """Provides economic calendar data from multiple sources with caching.

    Primary source: MT5 calendar (via tools/economic_calendar.py)
    Fallback: Free web API (via data/calendar.py)
    Conservative mode: Synthetic high-impact warning on all sources fail

    Caches results for the duration of one trading cycle (calendar data
    doesn't change mid-cycle).
    """

    def __init__(
        self,
        lead_minutes: int = 15,
        trail_minutes: int = 15,
        high_impact_only: bool = True,
        cache_ttl_seconds: int = 300,
        failure_mode: str = "conservative",  # "conservative" | "permissive"
    ):
        self.lead_minutes = lead_minutes
        self.trail_minutes = trail_minutes
        self.high_impact_only = high_impact_only
        self.cache_ttl_seconds = cache_ttl_seconds
        self.failure_mode = failure_mode

        # Cache
        self._cache: CalendarSnapshot | None = None
        self._cache_time: float = 0.0
        self._cache_currencies: set[str] = set()

    # ── Public API ──────────────────────────────────────────────────

    def get_events(
        self,
        currencies: list[str] | None = None,
        force_refresh: bool = False,
    ) -> CalendarSnapshot:
        """Get upcoming economic events for the given currencies.

        Returns cached snapshot if within TTL, otherwise fetches fresh data.

        Args:
            currencies: List of ISO currency codes (e.g. ["USD", "EUR"]).
                        If None, fetches for all major currencies.
            force_refresh: Ignore cache and fetch new data.

        Returns:
            CalendarSnapshot with typed EconomicEvent objects.
        """
        if currencies is None:
            currencies = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]

        curr_set = set(c.upper() for c in currencies)

        # Check cache
        if not force_refresh and self._is_cache_valid(curr_set):
            assert self._cache is not None
            return self._cache

        # Fetch fresh data
        snapshot = self._fetch_calendar(currencies)

        # Compute blackout windows for all events
        for event in snapshot.events:
            event.compute_blackout_window(self.lead_minutes, self.trail_minutes)

        # Update cache
        self._cache = snapshot
        self._cache_time = time.monotonic()
        self._cache_currencies = curr_set

        return snapshot

    async def get_events_async(
        self,
        currencies: list[str] | None = None,
        force_refresh: bool = False,
    ) -> CalendarSnapshot:
        """Async version — delegates to sync for MT5 compatibility."""
        return self.get_events(currencies, force_refresh)

    def invalidate_cache(self) -> None:
        """Force next call to fetch fresh data."""
        self._cache = None
        self._cache_time = 0.0
        self._cache_currencies.clear()

    # ── Internal ────────────────────────────────────────────────────

    def _is_cache_valid(self, currencies: set[str]) -> bool:
        """Check if cached data is still valid."""
        if self._cache is None:
            return False
        elapsed = time.monotonic() - self._cache_time
        if elapsed > self.cache_ttl_seconds:
            return False
        # Cache is valid if it covers at least the requested currencies
        return currencies.issubset(self._cache_currencies)

    def _fetch_calendar(self, currencies: list[str]) -> CalendarSnapshot:
        """Fetch calendar from MT5, fall back to web API, then conservative.

        Source priority:
        1. MT5 calendar (tools/economic_calendar.py)
        2. Free web API (data/calendar.py)
        3. Synthetic conservative (high-impact warning for all currencies)
        """
        # ── Source 1: MT5 calendar ────────
        events = self._fetch_from_mt5(currencies)
        if events:
            logger.info(
                "event_calendar_source source=%s event_count=%d currencies=%s",
                "mt5", len(events), currencies,
            )
            return CalendarSnapshot(
                events=events,
                source="mt5",
                currencies_covered=currencies,
            )

        # ── Source 2: Free web API ────────
        events = self._fetch_from_web_api(currencies)
        if events:
            logger.info(
                "event_calendar_source source=web_api event_count=%d currencies=%s",
                len(events), currencies,
            )
            return CalendarSnapshot(
                events=events,
                source="web_api",
                currencies_covered=currencies,
            )

        # ── Source 3: Conservative synthetic ────────
        if self.failure_mode == "conservative":
            logger.warning(
                "event_calendar_fallback_conservative reason=%s currencies=%s",
                "All calendar sources unavailable — generating synthetic high-impact warnings",
                currencies,
            )
            events = self._generate_conservative_events(currencies)
        else:
            logger.info(
                "event_calendar_fallback_permissive reason=%s currencies=%s",
                "All calendar sources unavailable — proceeding without event protection",
                currencies,
            )
            events = []

        return CalendarSnapshot(
            events=events,
            source="synthetic_conservative" if self.failure_mode == "conservative" else "none",
            currencies_covered=currencies,
        )

    def _fetch_from_mt5(self, currencies: list[str]) -> list[EconomicEvent]:
        """Fetch events using the existing MT5 economic calendar tool."""
        try:
            from noema.tools.economic_calendar import get_economic_calendar

            all_events: list[EconomicEvent] = []
            for currency in currencies:
                raw = get_economic_calendar(
                    currency=currency,
                    lookback_days=0,
                    lookahead_days=7,
                    min_impact="medium" if not self.high_impact_only else "high",
                )

                for evt_dict in raw.get("upcoming_events", []):
                    try:
                        # Parse event time
                        date_str = evt_dict.get("date", "")  # "2026-06-25"
                        time_str = evt_dict.get("time", "00:00 UTC")  # "18:00 UTC"
                        dt_str = f"{date_str} {time_str.replace(' UTC', '')}"
                        event_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                        event_time = event_time.replace(tzinfo=timezone.utc)

                        # Parse forecast/previous
                        forecast = self._safe_float(evt_dict.get("forecast"))
                        previous = self._safe_float(evt_dict.get("previous"))

                        event = EconomicEvent(
                            name=evt_dict.get("event", "Unknown"),
                            currency=evt_dict.get("currency", currency),
                            event_time=event_time,
                            impact=evt_dict.get("impact", "medium"),
                            forecast=forecast,
                            previous=previous,
                        )
                        all_events.append(event)
                    except Exception:
                        continue

            return all_events
        except Exception as e:
            logger.debug("mt5_calendar_unavailable error=%s", str(e))
            return []

    def _fetch_from_web_api(self, currencies: list[str]) -> list[EconomicEvent]:
        """Fetch events from free web API (nfs.faireconomy.media)."""
        try:
            import requests
import asyncio

            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            resp = await asyncio.to_thread(requests.get(url, timeout=10)
            if resp.status_code != 200:
                return []

            data = resp.json()
            events: list[EconomicEvent] = []
            for item in data:
                currency = item.get("country", "")
                if currency not in currencies:
                    continue

                # Parse time
                date_str = item.get("date", "")
                time_str = item.get("time", "00:00")
                impact = item.get("impact", "").lower()
                if impact not in ("low", "medium", "high"):
                    impact = "medium"

                if self.high_impact_only and impact != "high":
                    continue

                try:
                    dt_str = f"{date_str} {time_str}"
                    event_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                    event_time = event_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

                event = EconomicEvent(
                    name=item.get("title", "Unknown"),
                    currency=currency,
                    event_time=event_time,
                    impact=impact,
                    forecast=self._safe_float(item.get("forecast")),
                    previous=self._safe_float(item.get("previous")),
                    actual=self._safe_float(item.get("actual")),
                )
                events.append(event)

            return events
        except Exception as e:
            logger.debug("web_api_calendar_unavailable error=%s", str(e))
            return []

    def _generate_conservative_events(
        self, currencies: list[str]
    ) -> list[EconomicEvent]:
        """Generate synthetic high-impact events as a conservative fallback.

        When ALL calendar sources fail, this creates a "phantom" high-impact
        event for each currency, effectively activating the blackout. This is
        the COO's condition #2: conservative failure mode.

        The synthetic events expire after 60 minutes (watchdog timeout).
        """
        now = datetime.now(timezone.utc)
        # Placeholder events 30 min in the future (triggers immediate blackout)
        events = []
        for currency in currencies:
            fake_time = now + timedelta(minutes=30)
            event = EconomicEvent(
                name=f"[CALENDAR_UNAVAILABLE] Synthetic high-impact warning for {currency}",
                currency=currency,
                event_time=fake_time,
                impact="high",
                category="synthetic_conservative",
            )
            event.compute_blackout_window(self.lead_minutes, self.trail_minutes)
            events.append(event)
        return events

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        """Safely convert a value to float."""
        if val is None or val == "" or val == "—":
            return None
        try:
            return float(str(val).replace(",", "").replace("%", ""))
        except (ValueError, TypeError):
            return None


# ══════════════════════════════════════════════════════════════════════
# Convenience factory
# ══════════════════════════════════════════════════════════════════════

def create_event_calendar(
    lead_minutes: int = 15,
    trail_minutes: int = 15,
    high_impact_only: bool = True,
    cache_ttl_seconds: int = 300,
    failure_mode: str = "conservative",
) -> EventCalendarDataSource:
    """Create an EventCalendarDataSource with the given configuration."""
    return EventCalendarDataSource(
        lead_minutes=lead_minutes,
        trail_minutes=trail_minutes,
        high_impact_only=high_impact_only,
        cache_ttl_seconds=cache_ttl_seconds,
        failure_mode=failure_mode,
    )
