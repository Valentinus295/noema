"""Position Reconciliation — detect & correct drift between Noema and brokers.

Compares Noema's internal position records (from the journal / state machine)
against the broker's actual positions. Detects discrepancies caused by:

- Partial fills (volume mismatch)
- Slippage (price mismatch)
- Manual broker intervention (positions Noema doesn't know about)
- Connection gaps (positions Noema missed closing)

Reconciliation runs on startup and every N decision cycles.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════

class DriftSeverity(str, Enum):
    """Severity of a position drift event."""
    INFO = "info"               # Minor — logged only
    WARNING = "warning"         # Notable — alert sent
    CRITICAL = "critical"       # Must resolve — can trigger kill-switch


class DriftAction(str, Enum):
    """Action taken on drift."""
    NOOP = "noop"                   # No action — within tolerance
    LOG = "log"                     # Log only
    ALERT = "alert"                 # Send alert (Telegram/Dashboard)
    AUTO_CORRECT = "auto_correct"   # Automatically fix the drift
    KILL_SWITCH = "kill_switch"     # Trigger kill-switch — human must intervene


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation run."""
    timestamp: float = field(default_factory=time.time)
    total_positions_noema: int = 0
    total_positions_broker: int = 0
    matched: int = 0
    drifted: int = 0
    missing_from_noema: int = 0     # On broker but not in Noema
    missing_from_broker: int = 0    # In Noema but not on broker
    actions_taken: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    drifts: list["PositionDrift"] = field(default_factory=list)
    success: bool = True

    @property
    def is_clean(self) -> bool:
        return self.drifted == 0 and self.missing_from_noema == 0 and self.missing_from_broker == 0


@dataclass
class PositionDrift:
    """A detected drift between Noema's record and broker reality."""
    ticket: int
    symbol: str
    drift_type: str  # "volume", "price", "sl", "tp", "direction", "missing", "unknown"
    noema_value: Any = None
    broker_value: Any = None
    severity: DriftSeverity = DriftSeverity.WARNING
    action: DriftAction = DriftAction.ALERT
    resolved: bool = False
    resolution_note: str = ""
    detected_at: float = field(default_factory=time.time)


@dataclass
class PositionRecord:
    """Noema's internal position representation for reconciliation."""
    ticket: int
    symbol: str
    direction: str      # "buy" | "sell" | "long" | "short"
    volume: float
    open_price: float
    sl: float = 0.0
    tp: float = 0.0
    magic: int = 0
    opened_at: datetime | None = None

    def normalize_direction(self) -> str:
        """Normalize direction to 'buy' or 'sell'."""
        d = self.direction.lower()
        if d in ("long", "buy"):
            return "buy"
        if d in ("short", "sell"):
            return "sell"
        return d


# ═══════════════════════════════════════════════════════════
# Tolerances
# ═══════════════════════════════════════════════════════════

@dataclass
class ReconciliationTolerances:
    """Tolerance thresholds for drift detection.

    Conservative defaults: we alert early rather than late.
    """
    price_absolute: float = 0.00050     # 5 pips for most FX pairs
    price_jpy_absolute: float = 0.050   # 5 pips JPY
    volume_relative: float = 0.05       # 5% volume drift
    sl_tp_absolute: float = 0.00100     # 10 pips SL/TP
    auto_correct_max_volume: float = 0.10  # max 10% auto-correct
    max_drift_percent: float = 0.10     # >10% drift = CRITICAL


# ═══════════════════════════════════════════════════════════
# Reconciliation Engine
# ═══════════════════════════════════════════════════════════

class PositionReconciler:
    """Compare Noema position records vs broker positions, detect and fix drift.

    Usage:
        reconciler = PositionReconciler(tolerances=ReconciliationTolerances())
        result = reconciler.reconcile(noema_positions, broker_positions)
        if not result.is_clean:
            reconciler.correct_drifts(result, broker)
    """

    def __init__(
        self,
        tolerances: ReconciliationTolerances | None = None,
        auto_correct_enabled: bool = False,
        alert_callback: Any = None,  # callable(str) for alerts
    ) -> None:
        self.tolerances = tolerances or ReconciliationTolerances()
        self.auto_correct_enabled = auto_correct_enabled
        self.alert_callback = alert_callback
        self._last_reconciliation: ReconciliationResult | None = None
        self._drift_history: list[PositionDrift] = []
        self._logger = logger.bind(component="position_reconciler")

    # ── Reconciliation ──────────────────────────────────────

    def reconcile(
        self,
        noema_positions: list[PositionRecord],
        broker_positions: list[dict[str, Any]],
    ) -> ReconciliationResult:
        """Run full position reconciliation.

        Args:
            noema_positions: Noema's internal position records
            broker_positions: Broker's actual positions (dicts with keys:
                ticket, symbol, type, volume, open_price, sl, tp)

        Returns:
            ReconciliationResult with all drifts found.
        """
        result = ReconciliationResult(
            total_positions_noema=len(noema_positions),
            total_positions_broker=len(broker_positions),
        )

        # Index positions by ticket
        noema_by_ticket: dict[int, PositionRecord] = {}
        for p in noema_positions:
            if p.ticket > 0:
                noema_by_ticket[p.ticket] = p

        broker_by_ticket: dict[int, dict] = {}
        for p in broker_positions:
            ticket = p.get("ticket", 0)
            if ticket > 0:
                broker_by_ticket[ticket] = p

        # Find matches and drifts
        all_tickets = set(noema_by_ticket) | set(broker_by_ticket)
        for ticket in sorted(all_tickets):
            noema_pos = noema_by_ticket.get(ticket)
            broker_pos = broker_by_ticket.get(ticket)

            if noema_pos and broker_pos:
                # Both have this position — check for drift
                drifts = self._compare_positions(noema_pos, broker_pos)
                if drifts:
                    result.drifted += len(drifts)
                    result.drifts.extend(drifts)
                    # Determine action
                    severity = max(d.severity for d in drifts)
                    action = self._determine_action(drifts, severity)
                    for d in drifts:
                        d.action = action
                    if action == DriftAction.KILL_SWITCH:
                        result.alerts.append(
                            f"CRITICAL DRIFT: Ticket {ticket} {broker_pos.get('symbol', '')} "
                            + "; ".join(f"{d.drift_type}: noema={d.noema_value} broker={d.broker_value}" for d in drifts)
                        )
                else:
                    result.matched += 1

            elif noema_pos and not broker_pos:
                # Noema thinks position is open, broker doesn't have it
                drift = PositionDrift(
                    ticket=ticket,
                    symbol=noema_pos.symbol,
                    drift_type="missing",
                    noema_value=f"vol={noema_pos.volume} dir={noema_pos.direction}",
                    broker_value="NOT ON BROKER",
                    severity=DriftSeverity.WARNING,
                    action=DriftAction.ALERT,
                )
                result.drifts.append(drift)
                result.missing_from_broker += 1
                result.alerts.append(
                    f"Position ticket {ticket} ({noema_pos.symbol}) in Noema but MISSING from broker"
                )

            elif broker_pos and not noema_pos:
                # Broker has position Noema doesn't know about
                drift = PositionDrift(
                    ticket=ticket,
                    symbol=broker_pos.get("symbol", "UNKNOWN"),
                    drift_type="unknown",
                    noema_value="NOT IN NOEMA",
                    broker_value=f"vol={broker_pos.get('volume', 0)} type={broker_pos.get('type', '?')}",
                    severity=DriftSeverity.CRITICAL,
                    action=DriftAction.KILL_SWITCH,
                )
                result.drifts.append(drift)
                result.missing_from_noema += 1
                result.alerts.append(
                    f"UNKNOWN POSITION: Ticket {ticket} ({broker_pos.get('symbol', '?')}) "
                    f"on broker but NOT in Noema records — possible manual intervention!"
                )

        self._last_reconciliation = result
        self._drift_history.extend(result.drifts)

        if result.alerts:
            self._logger.warning(
                "reconciliation_drifts_found",
                drifts=len(result.drifts),
                alerts=len(result.alerts),
            )
        else:
            self._logger.info(
                "reconciliation_clean",
                matched=result.matched,
                total_noema=result.total_positions_noema,
                total_broker=result.total_positions_broker,
            )

        return result

    # ── Position Comparison ──────────────────────────────────

    def _compare_positions(
        self,
        noema: PositionRecord,
        broker: dict[str, Any],
    ) -> list[PositionDrift]:
        """Compare a single Noema position against broker reality."""
        drifts: list[PositionDrift] = []

        # Direction
        broker_type = str(broker.get("type", "")).lower()
        normalized_noema = noema.normalize_direction()
        if normalized_noema != broker_type:
            drifts.append(PositionDrift(
                ticket=noema.ticket,
                symbol=noema.symbol,
                drift_type="direction",
                noema_value=normalized_noema,
                broker_value=broker_type,
                severity=DriftSeverity.CRITICAL,
            ))

        # Volume
        broker_vol = float(broker.get("volume", 0))
        vol_diff = abs(noema.volume - broker_vol)
        vol_diff_rel = vol_diff / max(noema.volume, 0.001)
        if vol_diff_rel > self.tolerances.volume_relative:
            severity = DriftSeverity.CRITICAL if vol_diff_rel > self.tolerances.max_drift_percent else DriftSeverity.WARNING
            drifts.append(PositionDrift(
                ticket=noema.ticket,
                symbol=noema.symbol,
                drift_type="volume",
                noema_value=noema.volume,
                broker_value=broker_vol,
                severity=severity,
            ))

        # Price
        broker_price = float(broker.get("open_price", 0))
        price_tolerance = self.tolerances.price_jpy_absolute if "JPY" in noema.symbol else self.tolerances.price_absolute
        price_diff = abs(noema.open_price - broker_price)
        if price_diff > price_tolerance:
            drifts.append(PositionDrift(
                ticket=noema.ticket,
                symbol=noema.symbol,
                drift_type="price",
                noema_value=noema.open_price,
                broker_value=broker_price,
                severity=DriftSeverity.WARNING,
            ))

        # SL
        broker_sl = float(broker.get("sl", 0))
        if abs(noema.sl - broker_sl) > self.tolerances.sl_tp_absolute and (noema.sl > 0 or broker_sl > 0):
            drifts.append(PositionDrift(
                ticket=noema.ticket,
                symbol=noema.symbol,
                drift_type="sl",
                noema_value=noema.sl,
                broker_value=broker_sl,
                severity=DriftSeverity.WARNING,
            ))

        # TP
        broker_tp = float(broker.get("tp", 0))
        if abs(noema.tp - broker_tp) > self.tolerances.sl_tp_absolute and (noema.tp > 0 or broker_tp > 0):
            drifts.append(PositionDrift(
                ticket=noema.ticket,
                symbol=noema.symbol,
                drift_type="tp",
                noema_value=noema.tp,
                broker_value=broker_tp,
                severity=DriftSeverity.WARNING,
            ))

        return drifts

    # ── Action Determination ─────────────────────────────────

    def _determine_action(
        self,
        drifts: list[PositionDrift],
        severity: DriftSeverity,
    ) -> DriftAction:
        """Decide what action to take based on drift severity and config."""
        if severity == DriftSeverity.CRITICAL:
            return DriftAction.KILL_SWITCH

        if severity == DriftSeverity.INFO:
            return DriftAction.LOG

        # WARNING: auto-correct if enabled and drift is within auto-correct bounds
        if self.auto_correct_enabled:
            auto_correctable = all(
                d.drift_type in ("volume", "sl", "tp") for d in drifts
            )
            if auto_correctable:
                return DriftAction.AUTO_CORRECT

        return DriftAction.ALERT

    # ── Correction ───────────────────────────────────────────

    async def correct_drifts(
        self,
        result: ReconciliationResult,
        broker,  # BrokerBase instance
    ) -> list[str]:
        """Attempt to auto-correct drifts that are within safety bounds.

        Args:
            result: The reconciliation result
            broker: Broker instance for making corrections

        Returns:
            List of correction result strings
        """
        corrections: list[str] = []

        for drift in result.drifts:
            if drift.resolved:
                continue

            if drift.action != DriftAction.AUTO_CORRECT:
                continue

            try:
                if drift.drift_type == "sl" or drift.drift_type == "tp":
                    # Modify SL/TP to match Noema's record
                    sl_val = drift.noema_value if drift.drift_type == "sl" else 0.0
                    tp_val = drift.noema_value if drift.drift_type == "tp" else 0.0
                    # We need the actual values — get from broker
                    success = broker.modify_position(
                        ticket=drift.ticket,
                        sl=sl_val if sl_val > 0 else 0,
                        tp=tp_val if tp_val > 0 else 0,
                    )
                    if success:
                        drift.resolved = True
                        drift.resolution_note = "SL/TP corrected to Noema values"
                        corrections.append(f"Corrected SL/TP for ticket {drift.ticket}")

                elif drift.drift_type == "volume":
                    vol_diff = abs(drift.noema_value - drift.broker_value)
                    if vol_diff < self.tolerances.auto_correct_max_volume:
                        # Close the broker position if Noema has lower volume
                        # (can't increase position automatically for safety)
                        if drift.noema_value < drift.broker_value:
                            # Partial close not universally supported — log only
                            drift.resolution_note = f"Volume drift {vol_diff:.4f} logged (auto partial-close not supported)"
                            corrections.append(f"Volume drift logged for ticket {drift.ticket}")
                        else:
                            # Broker filled less than expected — this is fine, just log
                            drift.resolved = True
                            drift.resolution_note = f"Volume drift accepted (broker filled {vol_diff:.4f} less)"
                            corrections.append(f"Volume drift accepted for ticket {drift.ticket}")

            except Exception as e:
                self._logger.error("drift_correction_failed", ticket=drift.ticket, error=str(e))
                corrections.append(f"FAILED to correct ticket {drift.ticket}: {e}")

        # Handle missing from Noema positions — close them (unknown risk)
        for drift in result.drifts:
            if drift.drift_type == "unknown" and not drift.resolved:
                try:
                    broker.close_position(drift.ticket)
                    drift.resolved = True
                    drift.resolution_note = "Closed unknown position (not in Noema records)"
                    corrections.append(f"Closed unknown position ticket {drift.ticket}")
                except Exception as e:
                    corrections.append(f"FAILED to close unknown ticket {drift.ticket}: {e}")

        if corrections:
            self._logger.info("drift_corrections_applied", count=len(corrections))

        return corrections

    # ── Startup Reconciliation ───────────────────────────────

    async def startup_reconciliation(
        self,
        noema_positions: list[PositionRecord],
        broker,
    ) -> ReconciliationResult:
        """Run reconciliation on startup — more aggressive correction allowed.

        On startup, we're willing to sync state more aggressively since
        there's been no active trading to interfere with.
        """
        broker_positions = broker.get_open_positions()
        broker_dicts = [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": p.type,
                "volume": p.volume,
                "open_price": p.open_price,
                "sl": p.sl,
                "tp": p.tp,
            }
            for p in broker_positions
        ]
        result = self.reconcile(noema_positions, broker_dicts)

        if result.alerts:
            self._logger.warning(
                "startup_drifts_detected",
                count=len(result.alerts),
                details=result.alerts[:5],
            )

        return result

    # ── Scheduled Reconciliation ─────────────────────────────

    async def run_cycle(
        self,
        noema_positions: list[PositionRecord],
        broker,
        cycle_number: int,
    ) -> ReconciliationResult:
        """Run reconciliation as part of a regular decision cycle.

        Args:
            noema_positions: Current Noema position records
            broker: Broker instance
            cycle_number: Current decision cycle number (for logging)
        """
        result = await self.startup_reconciliation(noema_positions, broker)

        if not result.is_clean:
            await self.correct_drifts(result, broker)

        self._logger.info(
            "cycle_reconciliation_complete",
            cycle=cycle_number,
            clean=result.is_clean,
            drifts=result.drifted,
        )

        return result

    # ── Query ────────────────────────────────────────────────

    def get_last_result(self) -> ReconciliationResult | None:
        return self._last_reconciliation

    def get_drift_history(self, limit: int = 100) -> list[PositionDrift]:
        return self._drift_history[-limit:]

    def get_unresolved_drifts(self) -> list[PositionDrift]:
        return [d for d in self._drift_history if not d.resolved]

    def reset_history(self) -> None:
        self._drift_history.clear()
        self._last_reconciliation = None
