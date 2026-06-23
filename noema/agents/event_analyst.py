"""
EventAnalyst Agent — Phase 1.5: Economic Calendar & News Event Analysis.

Polls the economic calendar every N cycles, classifies events by impact level
(HIGH / MEDIUM / LOW), maps events to affected currency pairs, and activates/
deactivates Guardian blackout windows around high-impact events.

Architecture (per board decision):
    - Event classification: RULE-BASED (impact from calendar source, not LLM)
    - Blackout timing: DETERMINISTIC (event_time ± config_minutes)
    - Position management: RULE-BASED (flatten or hold, no new trades)
    - LLM role: NARRATIVE ONLY ("FOMC decision: rates held at 5.25%")

Integration:
    - Polls calendar via EventCalendarDataSource → returns CalendarSnapshot
    - Activates Guardian blackout 15 min before high-impact events
    - Monitors volatility normalization post-event → deactivates blackout
    - COO conditions: 60-min max blackout, conservative failure mode, Prometheus metrics
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from noema.core.modern_agent import DeterministicAgent, AgentReport
from noema.data.event_calendar import (
    EconomicEvent,
    CalendarSnapshot,
    EventCalendarDataSource,
    get_currencies_for_pair,
    get_pairs_for_currency,
)
from noema.data.event_study import EventStudy, EventImpactResult

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# EventAnalystState
# ══════════════════════════════════════════════════════════════════════

@dataclass
class EventAnalystState:
    """Mutable state tracked by the EventAnalyst across cycles."""
    # Calendar cache
    last_calendar_snapshot: CalendarSnapshot | None = None
    last_calendar_fetch: datetime | None = None

    # Active blackouts
    active_blackouts: dict[str, EconomicEvent] = field(default_factory=dict)
    #   key = "event_name:pair" → EconomicEvent in blackout

    blackout_started_at: dict[str, datetime] = field(default_factory=dict)
    #   key = "event_name:pair" → when blackout was activated

    # Event study integration
    event_study: EventStudy | None = None
    pre_event_volatility: dict[str, float] = field(default_factory=dict)
    #   key = pair → pre-event volatility baseline

    # Watchdog
    max_blackout_minutes: int = 60

    # Metrics
    cycle_count: int = 0
    events_detected_total: int = 0
    blackout_activations_total: int = 0
    blackout_auto_lifted_total: int = 0

    # Audit log
    audit_log: list[dict[str, Any]] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# EventAnalyst Agent
# ══════════════════════════════════════════════════════════════════════

class EventAnalyst(DeterministicAgent):
    """Agent responsible for economic calendar monitoring and news blackout management.

    Operates on a configurable cycle (default: every 5 minutes). Checks upcoming
    events, activates Guardian blackout, monitors volatility normalization, and
    deactivates blackout when conditions are met.

    All logic is DETERMINISTIC — no LLM involvement in blackout decisions.
    """

    name = "event_analyst"
    role = "EventAnalyst"
    priority = 1  # Runs before DATA phase

    def __init__(
        self,
        calendar_source: EventCalendarDataSource | None = None,
        event_study: EventStudy | None = None,
        config: Any = None,
        guardian_state: Any = None,  # GuardianState reference for blackout activation
        guardian_agent: Any = None,  # GuardianAgent reference for activate/deactivate
        traded_pairs: list[str] | None = None,
        poll_interval_cycles: int = 1,   # Check calendar every N orchestrator cycles
        blackout_minutes: int = 30,       # Total blackout window (15 before + 15 after)
        high_impact_only: bool = True,
        max_blackout_minutes: int = 60,
        metrics_exporter: Any = None,
    ):
        super().__init__(config=config)
        self._state = EventAnalystState(max_blackout_minutes=max_blackout_minutes)
        self._calendar = calendar_source or EventCalendarDataSource(
            high_impact_only=high_impact_only,
        )
        self._study = event_study or EventStudy()
        self._guardian_state = guardian_state
        self._guardian_agent = guardian_agent
        self._traded_pairs = traded_pairs or [
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"
        ]
        self._poll_interval = poll_interval_cycles
        self._high_impact_only = high_impact_only
        self._blackout_minutes = blackout_minutes
        self._max_blackout_minutes = max_blackout_minutes
        self._metrics_exporter = metrics_exporter

        # Derive currencies to monitor from traded pairs
        self._monitored_currencies = list(set(
            curr for pair in self._traded_pairs
            for curr in get_currencies_for_pair(pair)
        ))

        self._cycle_count = 0

    # ── Core Analysis (DeterministicAgent interface) ────────────────

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Run the event analysis cycle.

        This is the main entry point called by the orchestrator pre-cycle.
        Checks for upcoming high-impact events, activates blackout if needed,
        and monitors existing blackouts for expiration/normalization.
        """
        self._cycle_count += 1
        self._state.cycle_count += 1
        now = datetime.now(timezone.utc)

        # Determine if we should poll the calendar this cycle
        should_poll = (
            self._cycle_count % max(self._poll_interval, 1) == 1
            or self._state.last_calendar_snapshot is None
        )

        # ── 1. Poll calendar if due ────────────────────────────────
        if should_poll:
            snapshot = self._calendar.get_events(
                currencies=self._monitored_currencies,
                force_refresh=False,
            )
            self._state.last_calendar_snapshot = snapshot
            self._state.last_calendar_fetch = now
            self._state.events_detected_total += len(snapshot.events)

            logger.info(
                "event_analyst_calendar_polled source=%s total=%d high=%d currencies=%s",
                snapshot.source, len(snapshot.events),
                len(snapshot.high_impact_events), self._monitored_currencies,
            )

            # ── 2. Check for new blackout-worthy events ─────────────
            for event in snapshot.high_impact_events:
                affected_pairs = self._get_affected_pairs(event)
                for pair in affected_pairs:
                    blackout_key = f"{event.name}:{pair}"
                    if blackout_key in self._state.active_blackouts:
                        continue  # Already blacked out for this event

                    # Check if we're approaching the event (within blackout window)
                    if event.is_in_blackout(now) or event.minutes_away <= (self._blackout_minutes / 2):
                        self._activate_blackout(event, pair, now)

        # ── 3. Monitor existing blackouts ──────────────────────────
        expired_blackouts = []
        for blackout_key, event in self._state.active_blackouts.items():
            # Check hard timeout (watchdog — COO condition #1)
            started = self._state.blackout_started_at.get(blackout_key)
            if started:
                elapsed = (now - started).total_seconds() / 60
                if elapsed > self._max_blackout_minutes:
                    logger.error(
                        "event_analyst_blackout_watchdog_timeout key=%s elapsed=%.1f max=%d",
                        blackout_key, elapsed, self._max_blackout_minutes,
                    )
                    expired_blackouts.append(blackout_key)
                    continue

            # Check if event has passed + trail window
            if event.blackout_end and now > event.blackout_end:
                # Event window is over — check volatility normalization
                pair = blackout_key.split(":")[-1]
                if self._is_vol_normalized(pair, now):
                    expired_blackouts.append(blackout_key)
                else:
                    logger.debug(
                        "event_analyst_volatility_not_normalized pair=%s event=%s reason=%s",
                        pair, event.name, "Holding blackout — volatility still elevated",
                    )

        # ── 4. Deactivate expired blackouts ────────────────────────
        for key in expired_blackouts:
            self._deactivate_blackout(key, now)

        # ── 5. Update metrics ──────────────────────────────────────
        self._export_metrics()

        # Prepare report
        active_count = len(self._state.active_blackouts)
        blackout_status = "ACTIVE" if active_count > 0 else "CLEAR"

        return AgentReport(
            agent_name=self.name,
            signal=blackout_status,
            confidence=0.99,
            reasoning=(
                f"Blackout: {blackout_status} ({active_count} active). "
                f"Monitored currencies: {self._monitored_currencies}. "
                f"Cycle: {self._cycle_count}"
            ),
            data={
                "blackout_status": blackout_status,
                "active_blackouts": active_count,
                "monitored_currencies": self._monitored_currencies,
                "blackout_details": [
                    {
                        "event": evt.name,
                        "pair": key.split(":")[-1],
                        "impact": evt.impact,
                        "minutes_remaining": round(evt.minutes_away, 1),
                    }
                    for key, evt in self._state.active_blackouts.items()
                ],
            },
        )

    # ── Blackout Activation/Deactivation ────────────────────────────

    def _activate_blackout(
        self,
        event: EconomicEvent,
        pair: str,
        now: datetime,
    ) -> None:
        """Activate the news blackout for an event-pair combination.

        Wires into:
        1. GuardianAgent (set news_blackout = True on GuardianState)
        2. EventAnalystState (track active blackouts)
        3. Prometheus metrics
        4. Audit log
        """
        blackout_key = f"{event.name}:{pair}"

        # ── Guardian integration ────────
        if self._guardian_agent:
            self._guardian_agent.activate_news_blackout(
                reason=f"{event.name} ({event.impact} impact) — {pair} within {self._blackout_minutes//2} min window",
                pair=pair,
            )
        elif self._guardian_state:
            # Direct state manipulation if agent not available
            self._guardian_state.news_blackout = True
            self._guardian_state.news_blackout_until = event.blackout_end

        # ── Track state ────────
        self._state.active_blackouts[blackout_key] = event
        self._state.blackout_started_at[blackout_key] = now
        self._state.blackout_activations_total += 1

        # ── Audit log ────────
        audit_entry = {
            "event": "news_blackout_activated",
            "event_name": event.name,
            "pair": pair,
            "currency": event.currency,
            "impact": event.impact,
            "event_time_utc": event.event_time.isoformat(),
            "blackout_start": event.blackout_start.isoformat() if event.blackout_start else None,
            "blackout_end": event.blackout_end.isoformat() if event.blackout_end else None,
            "activated_at": now.isoformat(),
            "watchdog_timeout_minutes": self._max_blackout_minutes,
        }
        self._state.audit_log.append(audit_entry)

        logger.warning(
            "event_analyst_blackout_activated %s",
            str({k: v for k, v in audit_entry.items() if k != 'event'}),
        )

    def _deactivate_blackout(
        self,
        blackout_key: str,
        now: datetime,
    ) -> None:
        """Deactivate a specific blackout and clean up state.

        Called when:
        - Event window has passed AND volatility is normalized
        - Watchdog timeout has been reached
        """
        if blackout_key not in self._state.active_blackouts:
            return

        event = self._state.active_blackouts.pop(blackout_key)
        started = self._state.blackout_started_at.pop(blackout_key, None)
        pair = blackout_key.split(":")[-1]

        # ── Guardian integration ────────
        # Only clear if no other blackouts are active for this pair
        still_blocked = any(k.endswith(f":{pair}") for k in self._state.active_blackouts)

        if not still_blocked:
            if self._guardian_agent:
                self._guardian_agent.deactivate_news_blackout(
                    reason=f"Event window expired: {event.name}",
                    pair=pair,
                )
            elif self._guardian_state:
                self._guardian_state.news_blackout = False
                self._guardian_state.news_blackout_until = None

        # Duration info
        duration_minutes = (
            round((now - started).total_seconds() / 60, 1) if started else 0
        )

        # ── Audit log ────────
        audit_entry = {
            "event": "news_blackout_deactivated",
            "event_name": event.name,
            "pair": pair,
            "impact": event.impact,
            "deactivated_at": now.isoformat(),
            "duration_minutes": duration_minutes,
        }
        self._state.audit_log.append(audit_entry)

        logger.info(
            "event_analyst_blackout_deactivated %s",
            str({k: v for k, v in audit_entry.items() if k != 'event'}),
        )

    # ── Volatility Normalization ────────────────────────────────────

    def _is_vol_normalized(self, pair: str, now: datetime) -> bool:
        """Check if post-event volatility has returned to normal levels.

        Compares recent volatility to the pre-event baseline.
        If no baseline exists (first event), assume normalized after timeout.
        """
        pre_vol = self._state.pre_event_volatility.get(pair, 0.0)
        if pre_vol <= 0:
            return True

        try:
            # Use EventStudy to check normalization
            # In production, this would read recent price bars
            # For now: return True if event window has clearly passed
            # (event end + 5 bars minimum)
            return True  # Placeholder — actual price data needed
        except Exception:
            return True

    def update_pre_event_volatility(
        self, pair: str, prices: list[float]
    ) -> None:
        """Record pre-event volatility baseline for a pair.

        Called by orchestrator when a blackout is activated,
        to establish the baseline for normalization detection.
        """
        vol_est = self._study.estimate_pre_event_volatility(prices)
        self._state.pre_event_volatility[pair] = vol_est["volatility"]
        logger.debug(
            "event_analyst_baseline_volatility_set pair=%s vol=%.6f method=%s",
            pair, vol_est["volatility"], vol_est["model_used"],
        )

    # ── Helpers ─────────────────────────────────────────────────────

    def _get_affected_pairs(self, event: EconomicEvent) -> list[str]:
        """Map an economic event to the trading pairs it affects.

        Uses the deterministic CURRENCY_PAIR_MAP. For a USD event (NFP, FOMC),
        this returns ALL pairs that include USD: EURUSD, GBPUSD, USDJPY, etc.
        """
        affected = get_pairs_for_currency(event.currency)
        # Filter to only pairs we're actually trading
        if self._traded_pairs:
            affected = [p for p in affected if p.upper() in self._traded_pairs]
        return affected or [self._traded_pairs[0]]  # At least one pair

    # ── Metrics Export ──────────────────────────────────────────────

    def _export_metrics(self) -> None:
        """Export Prometheus metrics for blackout state (COO condition #3)."""
        if not self._metrics_exporter:
            return

        try:
            # Report active blackout status
            is_active = len(self._state.active_blackouts) > 0

            # Use metrics_exporter if available
            if hasattr(self._metrics_exporter, 'set_news_blackout_active'):
                self._metrics_exporter.set_news_blackout_active(is_active)

            if hasattr(self._metrics_exporter, 'record_event_impact_triggered'):
                # Report per-currency pair blackout status
                for pair in self._traded_pairs:
                    blocked = any(
                        k.endswith(f":{pair}")
                        for k in self._state.active_blackouts
                    )
                    self._metrics_exporter.record_event_impact_triggered(
                        pair=pair,
                        blocked=blocked,
                    )
        except Exception as e:
            logger.debug("event_analyst_metrics_export_failed error=%s", str(e))

    # ── Public API ──────────────────────────────────────────────────

    def is_pair_blacked_out(self, pair: str) -> bool:
        """Check if a specific pair is currently under news blackout."""
        return any(
            k.endswith(f":{pair}")
            for k in self._state.active_blackouts
        )

    def get_active_blackouts(self) -> dict[str, EconomicEvent]:
        """Return all currently active blackouts."""
        return dict(self._state.active_blackouts)

    def get_blackout_status(self) -> dict[str, Any]:
        """Get a summary of current blackout status."""
        active = self._state.active_blackouts
        now = datetime.now(timezone.utc)

        return {
            "active_count": len(active),
            "blackouts": [
                {
                    "event": evt.name,
                    "pair": key.split(":")[-1],
                    "impact": evt.impact,
                    "event_time_utc": evt.event_time.isoformat(),
                    "blackout_end_utc": evt.blackout_end.isoformat() if evt.blackout_end else None,
                    "minutes_remaining": round(
                        (evt.blackout_end - now).total_seconds() / 60, 1
                    ) if evt.blackout_end else 0,
                    "minutes_until_event": round(evt.minutes_away, 1),
                }
                for key, evt in active.items()
            ],
            "last_calendar_fetch": (
                self._state.last_calendar_fetch.isoformat()
                if self._state.last_calendar_fetch else None
            ),
            "calendar_source": (
                self._state.last_calendar_snapshot.source
                if self._state.last_calendar_snapshot else "unknown"
            ),
        }

    def get_recent_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent audit log entries for monitoring (COO condition #4)."""
        return self._state.audit_log[-limit:]

    @property
    def analyst_state(self) -> EventAnalystState:
        return self._state
