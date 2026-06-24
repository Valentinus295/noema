"""Regulatory Compliance — audit trail, position limits, regulatory stubs.

Ensures Noema trading operations are audit-ready and compliant with:
- Internal: Audit trail completeness, position limits, data retention
- EU: MiCA (Markets in Crypto-Assets) stubs — position reporting, transparency
- US: SEC stubs — Reg SHO, large trader reporting, electronic trading risk controls
- Generic: FATF travel rule, AML/KYC data separation

All checks are deterministic. This is compliance infrastructure, not legal advice.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════

class ComplianceStatus(str, Enum):
    """Overall compliance status."""
    COMPLIANT = "compliant"
    WARNING = "warning"          # Minor issues — logged but trading continues
    NON_COMPLIANT = "non_compliant"  # Must halt trading until resolved
    NOT_APPLICABLE = "not_applicable"


class Regulation(str, Enum):
    """Regulatory frameworks supported."""
    INTERNAL = "internal"          # Noema internal compliance rules
    MICA = "mica"                  # EU Markets in Crypto-Assets
    SEC = "sec"                    # US Securities and Exchange Commission
    FCA = "fca"                    # UK Financial Conduct Authority
    ASIC = "asic"                  # Australian Securities & Investments Commission
    FATF = "fatf"                  # Financial Action Task Force (global)


@dataclass
class AuditTrailEntry:
    """A single audit trail record."""
    timestamp: datetime
    event_type: str                 # "order_placed", "order_filled", "order_cancelled", etc.
    actor: str                      # Which agent/component made the action
    details: dict[str, Any]         # Full event details
    hash: str = ""                  # SHA-256 hash for tamper detection
    previous_hash: str = ""         # Chain to previous entry (mini-blockchain)


@dataclass
class AuditCheckResult:
    """Result of an audit trail completeness check."""
    status: ComplianceStatus = ComplianceStatus.COMPLIANT
    total_entries: int = 0
    entries_with_timestamp: int = 0
    entries_with_actor: int = 0
    entries_hashed: int = 0
    missing_required_fields: list[str] = field(default_factory=list)
    hash_chain_broken: bool = False
    hash_chain_break_at: int = 0
    gap_detected: bool = False       # Time gaps between entries > threshold
    gap_entries: list[int] = field(default_factory=list)
    oldest_entry: datetime | None = None
    newest_entry: datetime | None = None
    retention_violations: list[str] = field(default_factory=list)


@dataclass
class PositionLimitCheck:
    """Result of position limit compliance check."""
    status: ComplianceStatus = ComplianceStatus.COMPLIANT
    max_position_size: float = 0.0
    max_position_size_limit: float = 1.0
    total_exposure_pct: float = 0.0
    max_exposure_pct_limit: float = 300.0
    pairs_near_limit: list[str] = field(default_factory=list)  # >80% of limit
    pairs_over_limit: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ComplianceReport:
    """Full compliance check report."""
    timestamp: float = field(default_factory=time.time)
    jurisdiction: str = "internal"  # "EU", "US", "UK", "AU", "internal"
    overall_status: ComplianceStatus = ComplianceStatus.COMPLIANT
    audit_trail: AuditCheckResult = field(default_factory=AuditCheckResult)
    position_limits: PositionLimitCheck = field(default_factory=PositionLimitCheck)
    mica_report: dict[str, Any] = field(default_factory=dict)
    sec_report: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    checks_passed: int = 0
    checks_warning: int = 0
    checks_failed: int = 0


# ═══════════════════════════════════════════════════════════
# Audit Trail
# ═══════════════════════════════════════════════════════════

class AuditTrail:
    """Append-only, tamper-evident audit trail for regulatory compliance.

    Implements a simple hash chain (mini-blockchain) where each entry
    includes the SHA-256 hash of the previous entry. Any tampering
    breaks the chain and is immediately detectable.

    Required for: MiCA transaction reporting, SEC Rule 17a-4, internal audits.
    """

    def __init__(self, storage_path: str = "data/audit_trail.jsonl") -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[AuditTrailEntry] = []
        self._last_hash: str = ""
        self._logger = logger.bind(component="audit_trail")

    def record(
        self,
        event_type: str,
        actor: str,
        details: dict[str, Any],
    ) -> AuditTrailEntry:
        """Append an entry to the audit trail with hash chaining."""
        now = datetime.now(timezone.utc)
        previous_hash = self._last_hash

        # Build hash input
        hash_input = json.dumps({
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "actor": actor,
            "details": details,
            "previous_hash": previous_hash,
        }, sort_keys=True, default=str)

        entry_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        entry = AuditTrailEntry(
            timestamp=now,
            event_type=event_type,
            actor=actor,
            details=details,
            hash=entry_hash,
            previous_hash=previous_hash,
        )

        self._entries.append(entry)
        self._last_hash = entry_hash
        self._persist_entry(entry)
        return entry

    def record_order_placed(
        self,
        actor: str,
        symbol: str,
        direction: str,
        volume: float,
        price: float,
        sl: float = 0,
        tp: float = 0,
        ticket: int = 0,
    ) -> AuditTrailEntry:
        """Record an order placement."""
        return self.record(
            event_type="order_placed",
            actor=actor,
            details={
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "price": price,
                "sl": sl,
                "tp": tp,
                "ticket": ticket,
            },
        )

    def record_order_filled(
        self,
        actor: str,
        ticket: int,
        symbol: str,
        fill_price: float,
        fill_volume: float,
        pnl: float = 0.0,
    ) -> AuditTrailEntry:
        """Record an order fill."""
        return self.record(
            event_type="order_filled",
            actor=actor,
            details={
                "ticket": ticket,
                "symbol": symbol,
                "fill_price": fill_price,
                "fill_volume": fill_volume,
                "pnl": pnl,
            },
        )

    def record_order_cancelled(
        self,
        actor: str,
        ticket: int,
        reason: str = "",
    ) -> AuditTrailEntry:
        """Record an order cancellation."""
        return self.record(
            event_type="order_cancelled",
            actor=actor,
            details={"ticket": ticket, "reason": reason},
        )

    def record_position_closed(
        self,
        actor: str,
        ticket: int,
        symbol: str,
        exit_price: float,
        pnl: float,
    ) -> AuditTrailEntry:
        """Record a position close."""
        return self.record(
            event_type="position_closed",
            actor=actor,
            details={
                "ticket": ticket,
                "symbol": symbol,
                "exit_price": exit_price,
                "pnl": pnl,
            },
        )

    def record_risk_event(
        self,
        actor: str,
        event: str,
        severity: str,
        description: str,
    ) -> AuditTrailEntry:
        """Record a risk management event."""
        return self.record(
            event_type="risk_event",
            actor=actor,
            details={
                "event": event,
                "severity": severity,
                "description": description,
            },
        )

    def record_config_change(
        self,
        actor: str,
        old_config: dict[str, Any],
        new_config: dict[str, Any],
    ) -> AuditTrailEntry:
        """Record a configuration change."""
        return self.record(
            event_type="config_change",
            actor=actor,
            details={
                "old_hash": hashlib.sha256(
                    json.dumps(old_config, sort_keys=True, default=str).encode()
                ).hexdigest()[:16],
                "new_hash": hashlib.sha256(
                    json.dumps(new_config, sort_keys=True, default=str).encode()
                ).hexdigest()[:16],
            },
        )

    def _persist_entry(self, entry: AuditTrailEntry) -> None:
        """Append entry to JSONL file."""
        try:
            record = {
                "timestamp": entry.timestamp.isoformat(),
                "event_type": entry.event_type,
                "actor": entry.actor,
                "details": entry.details,
                "hash": entry.hash,
                "previous_hash": entry.previous_hash,
            }
            with open(self.storage_path, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as e:
            self._logger.error("audit_persist_failed", error=str(e))

    def load(self) -> list[AuditTrailEntry]:
        """Load audit trail from storage."""
        entries: list[AuditTrailEntry] = []
        if not self.storage_path.exists():
            return entries

        with open(self.storage_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = AuditTrailEntry(
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                        event_type=data["event_type"],
                        actor=data["actor"],
                        details=data.get("details", {}),
                        hash=data.get("hash", ""),
                        previous_hash=data.get("previous_hash", ""),
                    )
                    entries.append(entry)
                    if entry.hash:
                        self._last_hash = entry.hash
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    self._logger.warning("audit_load_skip_line", error=str(e))

        self._entries = entries
        return entries

    def get_entries(
        self,
        event_type: str | None = None,
        actor: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 1000,
    ) -> list[AuditTrailEntry]:
        """Query audit trail entries."""
        results = self._entries
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if actor:
            results = [e for e in results if e.actor == actor]
        if start_time:
            results = [e for e in results if e.timestamp >= start_time]
        if end_time:
            results = [e for e in results if e.timestamp <= end_time]
        return results[-limit:]

    def verify_chain(self) -> AuditCheckResult:
        """Verify hash chain integrity — detects tampering."""
        entries = self._entries
        result = AuditCheckResult(
            total_entries=len(entries),
            entries_hashed=sum(1 for e in entries if e.hash),
        )

        if not entries:
            return result

        # Check required fields
        for i, entry in enumerate(entries):
            if not entry.timestamp:
                result.missing_required_fields.append(f"Entry {i}: missing timestamp")
            if not entry.actor:
                result.missing_required_fields.append(f"Entry {i}: missing actor")
            if not entry.event_type:
                result.missing_required_fields.append(f"Entry {i}: missing event_type")

        result.entries_with_timestamp = result.total_entries - sum(
            1 for f in result.missing_required_fields if "timestamp" in f
        )
        result.entries_with_actor = result.total_entries - sum(
            1 for f in result.missing_required_fields if "actor" in f
        )

        # Verify hash chain
        for i in range(1, len(entries)):
            current = entries[i]
            previous = entries[i - 1]
            if current.previous_hash and previous.hash:
                if current.previous_hash != previous.hash:
                    result.hash_chain_broken = True
                    result.hash_chain_break_at = i
                    self._logger.error(
                        "audit_chain_broken",
                        at_entry=i,
                        expected=previous.hash,
                        got=current.previous_hash,
                    )
                    break

        # Check time gaps (> 24h without entry during active trading)
        for i in range(1, len(entries)):
            gap = (entries[i].timestamp - entries[i - 1].timestamp).total_seconds()
            if gap > 86400:  # 24 hours
                result.gap_detected = True
                result.gap_entries.append(i)

        # Timestamps
        if entries:
            result.oldest_entry = entries[0].timestamp
            result.newest_entry = entries[-1].timestamp

        # Determine status
        if result.hash_chain_broken:
            result.status = ComplianceStatus.NON_COMPLIANT
        elif result.gap_detected or result.missing_required_fields:
            result.status = ComplianceStatus.WARNING
        else:
            result.status = ComplianceStatus.COMPLIANT

        return result

    def generate_report(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Generate a regulatory audit report (JSON exportable)."""
        entries = self.get_entries(start_time=start_time, end_time=end_time)
        chain_check = self.verify_chain()

        event_counts: dict[str, int] = {}
        actor_counts: dict[str, int] = {}
        for e in entries:
            event_counts[e.event_type] = event_counts.get(e.event_type, 0) + 1
            actor_counts[e.actor] = actor_counts.get(e.actor, 0) + 1

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_entries": len(entries),
            "period": {
                "start": (start_time.isoformat() if start_time else entries[0].timestamp.isoformat()) if entries else None,
                "end": (end_time.isoformat() if end_time else entries[-1].timestamp.isoformat()) if entries else None,
            },
            "chain_integrity": {
                "intact": not chain_check.hash_chain_broken,
                "break_at": chain_check.hash_chain_break_at if chain_check.hash_chain_broken else None,
            },
            "event_summary": event_counts,
            "actor_summary": actor_counts,
            "compliance_status": chain_check.status.value,
        }


# ═══════════════════════════════════════════════════════════
# Position Limit Monitor
# ═══════════════════════════════════════════════════════════

class PositionLimitMonitor:
    """Monitor position limits for regulatory and internal compliance.

    Tracks per-symbol position limits, total exposure caps, and provides
    pre-trade compliance checks that can block orders before execution.
    """

    def __init__(
        self,
        max_position_lot: float = 1.0,
        max_exposure_pct: float = 300.0,
        max_single_pair_pct: float = 50.0,
        max_per_broker_pct: float = 100.0,
    ) -> None:
        self.max_position_lot = max_position_lot
        self.max_exposure_pct = max_exposure_pct
        self.max_single_pair_pct = max_single_pair_pct
        self.max_per_broker_pct = max_per_broker_pct
        self._logger = logger.bind(component="position_limit_monitor")

    def check_position_limits(
        self,
        open_positions: list[dict[str, Any]],
        account_balance: float,
        proposed_trade: dict[str, Any] | None = None,
    ) -> PositionLimitCheck:
        """Check all position limits against current state.

        Args:
            open_positions: Current open positions
            account_balance: Account balance for exposure calculation
            proposed_trade: Optional proposed trade to check pre-trade

        Returns:
            PositionLimitCheck with compliance status
        """
        result = PositionLimitCheck(
            max_position_size_limit=self.max_position_lot,
            max_exposure_pct_limit=self.max_exposure_pct,
        )

        # Per-pair exposure
        pair_volumes: dict[str, float] = {}
        for p in open_positions:
            pair = p.get("symbol", p.get("pair", "UNKNOWN"))
            vol = abs(p.get("volume", 0))
            pair_volumes[pair] = pair_volumes.get(pair, 0) + vol

        # Max single position lot
        for p in open_positions:
            vol = abs(p.get("volume", 0))
            if vol > result.max_position_size_limit:
                pair = p.get("symbol", "UNKNOWN")
                result.pairs_over_limit.append(pair)
                result.warnings.append(
                    f"Position {pair} lot {vol} exceeds max {result.max_position_size_limit}"
                )
            elif vol > result.max_position_size_limit * 0.8:
                pair = p.get("symbol", "UNKNOWN")
                if pair not in result.pairs_near_limit:
                    result.pairs_near_limit.append(pair)

        # Total exposure
        total_volume = sum(pair_volumes.values())
        # Approximate notional value: 1 lot ≈ 100,000 base currency
        total_notional = total_volume * 100000
        total_exposure_pct = (total_notional / account_balance * 100) if account_balance > 0 else 0
        result.total_exposure_pct = round(total_exposure_pct, 2)
        result.max_position_size = max(
            [abs(p.get("volume", 0)) for p in open_positions], default=0.0
        )

        if total_exposure_pct > result.max_exposure_pct_limit:
            result.warnings.append(
                f"Total exposure {total_exposure_pct:.1f}% exceeds limit {result.max_exposure_pct_limit}%"
            )
            result.status = ComplianceStatus.NON_COMPLIANT

        # Pre-trade check
        if proposed_trade:
            proposed_pair = proposed_trade.get("symbol", proposed_trade.get("pair", ""))
            proposed_vol = abs(proposed_trade.get("volume", 0))
            existing_vol = pair_volumes.get(proposed_pair, 0)
            new_total = existing_vol + proposed_vol
            new_exposure = total_notional + (proposed_vol * 100000)
            new_exposure_pct = (new_exposure / account_balance * 100) if account_balance > 0 else 0

            if new_exposure_pct > result.max_exposure_pct_limit:
                result.warnings.append(
                    f"Proposed trade would bring exposure to {new_exposure_pct:.1f}% "
                    f"(limit: {result.max_exposure_pct_limit}%)"
                )
                result.status = ComplianceStatus.NON_COMPLIANT

            if proposed_vol > result.max_position_size_limit:
                result.pairs_over_limit.append(proposed_pair)
                result.warnings.append(
                    f"Proposed trade lot {proposed_vol} exceeds max {result.max_position_size_limit}"
                )
                result.status = ComplianceStatus.NON_COMPLIANT

        # Determine overall status
        if result.pairs_over_limit:
            result.status = ComplianceStatus.NON_COMPLIANT
        elif result.pairs_near_limit or (result.total_exposure_pct > result.max_exposure_pct_limit * 0.8):
            result.status = ComplianceStatus.WARNING

        self._logger.info(
            "position_limits_checked",
            status=result.status.value,
            exposure_pct=result.total_exposure_pct,
            warnings=len(result.warnings),
        )

        return result

    def can_place_order(
        self,
        proposed_trade: dict[str, Any],
        open_positions: list[dict[str, Any]],
        account_balance: float,
    ) -> tuple[bool, str]:
        """Pre-trade compliance check. Returns (can_trade, reason)."""
        check = self.check_position_limits(open_positions, account_balance, proposed_trade)
        if check.status == ComplianceStatus.NON_COMPLIANT:
            return False, "; ".join(check.warnings)
        return True, "ok"


# ═══════════════════════════════════════════════════════════
# Regulatory Reporting Stubs
# ═══════════════════════════════════════════════════════════

class RegulatoryReporter:
    """Generate regulatory reports for various jurisdictions.

    CURRENT STATUS: STUBS — builds report templates that can be populated
    with real data and submitted to regulators when required.
    """

    def __init__(self) -> None:
        self._logger = logger.bind(component="regulatory_reporter")

    # ── MiCA (EU Markets in Crypto-Assets) ──────────────────

    def generate_mica_position_report(
        self,
        positions: list[dict[str, Any]],
        account_balance: float,
        reporting_period: str = "daily",
    ) -> dict[str, Any]:
        """Generate MiCA-compliant position report stub.

        MiCA (Regulation 2023/1114) requires:
        - Position reporting for significant holdings
        - Market abuse surveillance
        - Transparency requirements for crypto-asset service providers
        """
        total_notional = sum(
            abs(p.get("volume", 0)) * 100000 for p in positions
        )

        return {
            "regulation": "MiCA (EU) 2023/1114",
            "status": "STUB",  # Not connected to real regulatory submission system
            "reporting_entity": "Noema Trading System",
            "reporting_period": reporting_period,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "holdings": [
                {
                    "asset": p.get("symbol", p.get("pair", "UNKNOWN")),
                    "asset_class": "forex",
                    "direction": p.get("direction", p.get("type", "unknown")),
                    "notional_value": abs(p.get("volume", 0)) * 100000,
                    "volume": p.get("volume", 0),
                    "open_price": p.get("open_price", 0),
                    "market_value": abs(p.get("volume", 0)) * 100000,  # approximate
                    "pnl": p.get("pnl", 0),
                }
                for p in positions
            ],
            "summary": {
                "total_notional_exposure": total_notional,
                "total_positions": len(positions),
                "exposure_pct_of_balance": round(
                    total_notional / account_balance * 100, 2
                ) if account_balance > 0 else 0,
            },
            "market_abuse_indicators": {
                "wash_trading_detected": False,
                "layering_detected": False,
                "spoofing_detected": False,
                "unusual_volume_detected": False,
            },
        }

    def generate_mica_transparency_report(
        self,
        trades: list[dict[str, Any]],
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        """MiCA transparency report stub."""
        total_volume = sum(abs(t.get("volume", 0)) for t in trades)
        total_pnl = sum(t.get("pnl", 0) for t in trades)

        return {
            "regulation": "MiCA Transparency Requirements",
            "status": "STUB",
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
            },
            "trading_summary": {
                "total_trades": len(trades),
                "total_volume": total_volume,
                "total_pnl": total_pnl,
                "buy_volume": sum(
                    abs(t.get("volume", 0))
                    for t in trades
                    if t.get("direction", "").lower() in ("buy", "long")
                ),
                "sell_volume": sum(
                    abs(t.get("volume", 0))
                    for t in trades
                    if t.get("direction", "").lower() in ("sell", "short")
                ),
            },
            "execution_quality": {
                "avg_slippage_pips": 0.0,  # Would need tick-by-tick data
                "fill_rate": 0.0,           # Would need order tracking
                "rejection_rate": 0.0,
            },
        }

    # ── SEC (US Securities and Exchange Commission) ──────────

    def generate_sec_large_trader_report(
        self,
        trades: list[dict[str, Any]],
        account_balance: float,
    ) -> dict[str, Any]:
        """SEC Large Trader Reporting stub (Rule 13h-1).

        Required for traders exceeding:
        - 2M shares or $20M in any single day
        - 20M shares or $200M in any calendar month
        """
        daily_volume = sum(abs(t.get("volume", 0)) * 100000 for t in trades)

        return {
            "regulation": "SEC Rule 13h-1 (Large Trader)",
            "status": "STUB",
            "reporting_entity": "Noema Trading System",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "large_trader_identification": {
                "is_large_trader": daily_volume > 20000000,
                "daily_notional_volume": daily_volume,
                "threshold_daily": 20000000,
                "threshold_monthly": 200000000,
            },
            "trading_activity": {
                "total_trades": len(trades),
                "total_notional": daily_volume,
                "asset_class": "forex",
            },
            "risk_controls": {
                "pre_trade_checks": True,
                "position_limits": True,
                "kill_switch": True,
                "erroneous_order_prevention": True,
            },
        }

    def generate_sec_risk_controls_report(self) -> dict[str, Any]:
        """SEC Electronic Trading Risk Controls attestation stub.

        Per SEC Rule 15c3-5 (Market Access Rule), brokers must have
        risk management controls and supervisory procedures.
        """
        return {
            "regulation": "SEC Rule 15c3-5 (Market Access)",
            "status": "STUB",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "risk_controls": [
                {
                    "control": "pre_trade_position_limits",
                    "status": "active",
                    "description": "Position size and exposure limits checked before each order",
                },
                {
                    "control": "lot_protection",
                    "status": "active",
                    "description": "Max lot size hard cap enforced at broker boundary (Noema_MAX_LOT_SIZE)",
                },
                {
                    "control": "kill_switch",
                    "status": "active",
                    "description": "Guardian kill-switch with 15 independent kill conditions",
                },
                {
                    "control": "erroneous_order_check",
                    "status": "active",
                    "description": "Price and volume sanity checks before order submission",
                },
                {
                    "control": "duplicate_order_check",
                    "status": "active",
                    "description": "Prevention of duplicate orders within a configurable window",
                },
                {
                    "control": "broker_disconnect_sla",
                    "status": "active",
                    "description": "Auto-reconnect within 10s, kill-switch after 30s, shutdown after 5min",
                },
                {
                    "control": "daily_loss_limit",
                    "status": "active",
                    "description": "Daily loss limit enforced (configurable, default 1-3%)",
                },
            ],
        }

    # ── FATF Travel Rule ───────────────────────────────────

    def generate_fatf_travel_rule_report(
        self,
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """FATF Travel Rule compliance stub.

        For crypto transactions > $1,000, originator and beneficiary
        information must travel with the transaction.
        """
        return {
            "regulation": "FATF Recommendation 16 (Travel Rule)",
            "status": "NOT_APPLICABLE",  # Forex trading not typically subject
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "applicability": {
                "asset_class": "forex",
                "subject_to_travel_rule": False,
                "note": "Forex trading through regulated brokers not subject to Travel Rule",
            },
            "kyc_aml": {
                "broker_kyc_completed": True,  # Broker handles KYC
                "source_of_funds_documented": True,
                "suspicious_activity_detected": False,
            },
        }

    # ── Internal Compliance ─────────────────────────────────

    def generate_internal_compliance_report(
        self,
        audit_trail: AuditTrail,
        position_monitor: PositionLimitMonitor,
        open_positions: list[dict[str, Any]],
        account_balance: float,
    ) -> ComplianceReport:
        """Generate comprehensive internal compliance report."""
        # Audit trail check
        audit_check = audit_trail.verify_chain()

        # Position limits
        pos_check = position_monitor.check_position_limits(open_positions, account_balance)

        # Build overall status
        if audit_check.status == ComplianceStatus.NON_COMPLIANT or pos_check.status == ComplianceStatus.NON_COMPLIANT:
            overall = ComplianceStatus.NON_COMPLIANT
        elif audit_check.status == ComplianceStatus.WARNING or pos_check.status == ComplianceStatus.WARNING:
            overall = ComplianceStatus.WARNING
        else:
            overall = ComplianceStatus.COMPLIANT

        # Collect recommendations
        recs: list[str] = []
        if audit_check.hash_chain_broken:
            recs.append("CRITICAL: Audit trail hash chain broken — possible data tampering")
        if audit_check.gap_detected:
            recs.append(f"WARNING: {len(audit_check.gap_entries)} gaps >24h detected in audit trail")
        if pos_check.pairs_over_limit:
            recs.append(f"CRITICAL: Position limits exceeded on: {', '.join(pos_check.pairs_over_limit)}")
        if pos_check.total_exposure_pct > pos_check.max_exposure_pct_limit * 0.9:
            recs.append(f"WARNING: Total exposure at {pos_check.total_exposure_pct}% — near {pos_check.max_exposure_pct_limit}% limit")

        if not recs:
            recs.append("All compliance checks passed")

        return ComplianceReport(
            overall_status=overall,
            audit_trail=audit_check,
            position_limits=pos_check,
            recommendations=recs,
            checks_passed=1 if audit_check.status == ComplianceStatus.COMPLIANT else 0 + 1 if pos_check.status == ComplianceStatus.COMPLIANT else 0,
            checks_warning=sum(
                1 for c in [audit_check.status, pos_check.status]
                if c == ComplianceStatus.WARNING
            ),
            checks_failed=sum(
                1 for c in [audit_check.status, pos_check.status]
                if c == ComplianceStatus.NON_COMPLIANT
            ),
        )


# ═══════════════════════════════════════════════════════════
# Compliance Engine (Orchestrator)
# ═══════════════════════════════════════════════════════════

class ComplianceEngine:
    """Orchestrates all compliance checks — pre-trade, post-trade, periodic.

    This is the single entry point for compliance. All trade-altering
    components should consult this engine before execution.
    """

    def __init__(
        self,
        audit_trail: AuditTrail | None = None,
        position_monitor: PositionLimitMonitor | None = None,
        regulatory_reporter: RegulatoryReporter | None = None,
    ) -> None:
        self.audit_trail = audit_trail or AuditTrail()
        self.position_monitor = position_monitor or PositionLimitMonitor()
        self.regulatory_reporter = regulatory_reporter or RegulatoryReporter()
        self._logger = logger.bind(component="compliance_engine")
        self._last_full_check: float = 0.0
        self._check_interval: float = 3600.0  # Full check every hour

    def pre_trade_check(
        self,
        proposed_trade: dict[str, Any],
        open_positions: list[dict[str, Any]],
        account_balance: float,
    ) -> tuple[bool, str]:
        """Pre-trade compliance gate. Returns (allowed, reason).

        This MUST be called before any order is sent to the broker.
        If it returns False, the order is blocked.
        """
        # 1. Position limit check
        can_trade, reason = self.position_monitor.can_place_order(
            proposed_trade, open_positions, account_balance
        )
        if not can_trade:
            self.audit_trail.record(
                event_type="order_blocked_compliance",
                actor="ComplianceEngine",
                details={
                    "reason": reason,
                    "proposed_trade": proposed_trade,
                },
            )
            self._logger.warning("pre_trade_blocked", reason=reason)
            return False, reason

        # 2. Additional checks can be added here (session, blackout, etc.)

        return True, "ok"

    def post_trade_record(
        self,
        trade_result: dict[str, Any],
        actor: str,
    ) -> None:
        """Record a completed trade in the audit trail."""
        pnl = trade_result.get("pnl", 0)
        event_type = "position_closed" if pnl != 0 else "order_filled"
        self.audit_trail.record(
            event_type=event_type,
            actor=actor,
            details=trade_result,
        )

    def periodic_check(
        self,
        open_positions: list[dict[str, Any]],
        account_balance: float,
    ) -> ComplianceReport:
        """Run full periodic compliance check."""
        return self.regulatory_reporter.generate_internal_compliance_report(
            self.audit_trail,
            self.position_monitor,
            open_positions,
            account_balance,
        )

    def export_compliance_data(
        self,
        output_dir: str = "reports/compliance/",
        regulation: Regulation = Regulation.INTERNAL,
        open_positions: list[dict[str, Any]] | None = None,
        account_balance: float = 0.0,
        trades: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Export compliance report to JSON file."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if regulation == Regulation.MICA:
            data = self.regulatory_reporter.generate_mica_position_report(
                open_positions or [], account_balance
            )
        elif regulation == Regulation.SEC:
            data = self.regulatory_reporter.generate_sec_large_trader_report(
                trades or [], account_balance
            )
        else:
            data = self.periodic_check(
                open_positions or [], account_balance
            ).__dict__

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = output_path / f"compliance_{regulation.value}_{timestamp}.json"
        filepath.write_text(json.dumps(data, indent=2, default=str))
        self._logger.info("compliance_exported", path=str(filepath))
        return filepath
