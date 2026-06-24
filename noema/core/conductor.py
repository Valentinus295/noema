"""Conductor — Meta-Cognition & Strategy Allocation for Noema Nexus.

Phase 2: Noema Nexus component. The Conductor is the strategic brain
that monitors all agent performance, detects anomalies, and adjusts
agent weights to optimize system-wide decision quality.

Components:
- PerformanceAggregator: Win rate, confidence calibration (Brier score), Sharpe
- AnomalyDetector: Signal drift, latency spikes, calibration decay
- StrategyAllocator: Adjusts agent weights based on performance
- FleetManager: Multi-symbol orchestration (Phase 3 preparation)

Anti-hallucination rules:
- All performance metrics are PURE MATH (win rate, Sharpe, drawdown)
- Anomaly detection uses statistical tests (distribution shift, latency Z-score)
- Weight updates are bounded and gradual (no sudden LLM-driven changes)
- NO LLM involvement in any performance/critical path decisions
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════

class ConductorState(str, Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    REBALANCING = "rebalancing"
    ALERTING = "alerting"
    HALTED = "halted"


@dataclass
class AgentPerformance:
    """Per-agent performance record. PURE MATH — no LLM fields."""
    agent_name: str
    team: str = "analysis"

    # Signal accuracy
    total_signals: int = 0
    correct_signals: int = 0
    win_rate_30d: float = 0.0
    win_rate_90d: float = 0.0

    # Confidence calibration (Brier score — lower is better)
    calibration_error: float = 0.0  # Brier score
    avg_confidence: float = 0.0
    overconfidence_score: float = 0.0  # Positive = overconfident
    calibration_stability: float = 1.0  # 1.0 = stable, <0.5 = drifting

    # Risk-adjusted returns
    sharpe_contribution: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_profit_per_signal: float = 0.0

    # Operational
    avg_latency_ms: float = 0.0
    failure_rate: float = 0.0
    consecutive_correct: int = 0
    consecutive_incorrect: int = 0

    # Weight
    current_weight: float = 1.0
    min_weight: float = 0.1
    max_weight: float = 2.0
    last_updated: float = 0.0

    # Signal distribution
    signal_distribution: dict[str, int] = field(default_factory=lambda: {
        "BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0,
    })

    # History (rolling windows)
    recent_predictions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        """Agent is considered reliable if win rate > 0.5 with sufficient samples."""
        return self.total_signals >= 20 and self.win_rate_30d > 0.5

    @property
    def is_calibrated(self) -> bool:
        """Agent is well-calibrated if Brier score < 0.25."""
        return self.calibration_error < 0.25 if self.total_signals > 0 else True

    @property
    def is_stable(self) -> bool:
        """Agent is stable if calibration isn't drifting."""
        return self.calibration_stability > 0.7

    @property
    def health_score(self) -> float:
        """Composite health score 0-100."""
        if self.total_signals < 5:
            return 50.0  # Neutral for agents with insufficient data

        score = 0.0
        score += min(self.win_rate_30d, 0.7) * 40  # Win rate (max 28)
        score += max(0, (1.0 - self.calibration_error)) * 30  # Calibration (max 30)
        score += max(0, self.calibration_stability) * 15  # Stability (max 15)
        score += max(0, min(self.profit_factor, 3.0) / 3.0) * 10  # Profit (max 10)
        score += max(0, (1.0 - self.failure_rate)) * 5  # Reliability (max 5)
        return min(score, 100.0)


@dataclass
class AnomalyRecord:
    """Detected anomaly in agent behavior."""
    agent_name: str
    anomaly_type: str  # "signal_drift", "latency_spike", "confidence_drift", "distribution_shift"
    severity: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    description: str
    detected_at: float = field(default_factory=time.monotonic)
    metric_name: str = ""
    expected_value: float = 0.0
    actual_value: float = 0.0
    z_score: float = 0.0
    resolved: bool = False
    resolved_at: float = 0.0


@dataclass
class FleetStatus:
    """Multi-symbol orchestration status (Phase 3 prep)."""
    symbols_active: list[str] = field(default_factory=list)
    symbols_halted: list[str] = field(default_factory=list)
    per_symbol_health: dict[str, float] = field(default_factory=dict)
    total_exposure_pct: float = 0.0
    correlation_matrix: dict[str, float] = field(default_factory=dict)
    regime_per_symbol: dict[str, str] = field(default_factory=dict)
    last_updated: float = 0.0


# ═══════════════════════════════════════════════════
# Performance Aggregator
# ═══════════════════════════════════════════════════

class PerformanceAggregator:
    """Tracks and aggregates agent performance metrics.

    PURE MATH: Win rate, Brier score, Sharpe ratio, profit factor.
    No LLM involvement — all calculations are deterministic.
    """

    def __init__(self, window_size: int = 30):
        self.window_size = window_size
        self._performances: dict[str, AgentPerformance] = {}
        self._signal_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=window_size)
        )
        self._logger = logger.bind(component="performance_aggregator")

    def get_or_create(self, agent_name: str, team: str = "analysis") -> AgentPerformance:
        """Get or create a performance record for an agent."""
        if agent_name not in self._performances:
            self._performances[agent_name] = AgentPerformance(
                agent_name=agent_name, team=team,
            )
        return self._performances[agent_name]

    def record_signal(
        self,
        agent_name: str,
        signal: str,
        confidence: float,
        outcome: bool | None = None,  # True = correct, False = incorrect, None = pending
        pnl: float = 0.0,
        latency_ms: float = 0.0,
    ) -> AgentPerformance:
        """Record a signal from an agent for performance tracking.

        Args:
            agent_name: Name of the agent.
            signal: Signal direction ("BULLISH", "BEARISH", "NEUTRAL").
            confidence: Agent's confidence (0.0-1.0).
            outcome: Whether the signal was correct (None = pending).
            pnl: Profit/loss associated with this signal.
            latency_ms: Agent processing latency.

        Returns:
            Updated AgentPerformance record.
        """
        perf = self.get_or_create(agent_name)

        # Record signal
        perf.total_signals += 1
        perf.signal_distribution[signal] = perf.signal_distribution.get(signal, 0) + 1
        perf.avg_confidence = (
            (perf.avg_confidence * (perf.total_signals - 1) + confidence)
            / perf.total_signals
            if perf.total_signals > 0 else confidence
        )
        perf.avg_latency_ms = (
            (perf.avg_latency_ms * (perf.total_signals - 1) + latency_ms)
            / perf.total_signals
            if perf.total_signals > 0 else latency_ms
        )

        # Update outcome if known
        if outcome is not None:
            if outcome:
                perf.correct_signals += 1
                perf.consecutive_correct += 1
                perf.consecutive_incorrect = 0
            else:
                perf.consecutive_correct = 0
                perf.consecutive_incorrect += 1

            perf.avg_profit_per_signal = (
                (perf.avg_profit_per_signal * (perf.total_signals - 1) + pnl)
                / perf.total_signals
                if perf.total_signals > 0 else pnl
            )

            # Update win rates
            if perf.total_signals >= 5:
                perf.win_rate_30d = perf.correct_signals / perf.total_signals
            if perf.total_signals >= 50:
                # 90d is approximated from total if we have enough data
                perf.win_rate_90d = perf.correct_signals / perf.total_signals

            # Update Brier score (calibration error)
            self._update_calibration(perf, outcomes_history=None)

        # Store in history
        self._signal_history[agent_name].append({
            "signal": signal,
            "confidence": confidence,
            "outcome": outcome,
            "pnl": pnl,
            "timestamp": time.monotonic(),
        })

        return perf

    def update_calibration_from_history(
        self,
        agent_name: str,
        outcomes: list[dict[str, Any]],
    ) -> None:
        """Update calibration metrics from a batch of signal outcomes.

        Args:
            agent_name: Agent name.
            outcomes: List of {signal, confidence, outcome, pnl} dicts.
        """
        perf = self.get_or_create(agent_name)
        self._update_calibration(perf, outcomes_history=outcomes)

    def _update_calibration(
        self,
        perf: AgentPerformance,
        outcomes_history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Update Brier score and overconfidence metrics.

        Brier score = mean((confidence - outcome)^2) where outcome is 0 or 1.
        Lower Brier = better calibrated.
        Overconfidence = avg_confidence - win_rate (positive = overconfident).
        """
        history = outcomes_history or list(self._signal_history.get(perf.agent_name, []))
        if not history:
            return

        # Filter to outcomes with known results
        known = [h for h in history if h.get("outcome") is not None]
        if len(known) < 3:
            return

        # Brier score
        squared_errors = []
        for h in known:
            outcome_val = 1.0 if h["outcome"] else 0.0
            squared_errors.append((h["confidence"] - outcome_val) ** 2)

        perf.calibration_error = sum(squared_errors) / len(squared_errors)

        # Overconfidence
        win_rate = sum(1 for h in known if h["outcome"]) / len(known) if known else 0.5
        perf.overconfidence_score = perf.avg_confidence - win_rate

        # Profit factor
        total_profit = sum(h["pnl"] for h in known if h["pnl"] > 0)
        total_loss = abs(sum(h["pnl"] for h in known if h["pnl"] < 0))
        perf.profit_factor = total_profit / total_loss if total_loss > 0 else 999.0

        # Sharpe contribution (simplified)
        pnls = [h["pnl"] for h in known if h["pnl"] != 0]
        if len(pnls) >= 5:
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1) if len(pnls) > 1 else 1.0
            if variance > 0:
                perf.sharpe_contribution = mean_pnl / math.sqrt(variance)
            perf.sortino_ratio = self._sortino(pnls)

        # Calibration stability (compare last 10 vs previous 10)
        if len(known) >= 20:
            recent = known[-10:]
            earlier = known[-20:-10]
            recent_error = sum(
                (1.0 if h["outcome"] else 0.0 - h["confidence"]) ** 2
                for h in recent
            ) / len(recent)
            earlier_error = sum(
                (1.0 if h["outcome"] else 0.0 - h["confidence"]) ** 2
                for h in earlier
            ) / len(earlier)
            drift = abs(recent_error - earlier_error)
            perf.calibration_stability = max(0.0, 1.0 - drift * 5)  # Drift > 0.2 = stability < 0

    @staticmethod
    def _sortino(returns: list[float], target: float = 0.0) -> float:
        """Calculate Sortino ratio (downside deviation only)."""
        downside = [r for r in returns if r < target]
        if not downside or len(returns) < 2:
            return 0.0
        mean_return = sum(returns) / len(returns)
        downside_variance = sum((r - target) ** 2 for r in downside) / len(downside)
        if downside_variance == 0:
            return 0.0
        return (mean_return - target) / math.sqrt(downside_variance)

    def get_performance(self, agent_name: str) -> AgentPerformance:
        """Get current performance for an agent."""
        return self.get_or_create(agent_name)

    def get_all_performances(self) -> dict[str, AgentPerformance]:
        """Get all agent performances."""
        return dict(self._performances)

    def get_top_agents(self, n: int = 3) -> list[AgentPerformance]:
        """Get top N agents by health score."""
        sorted_agents = sorted(
            self._performances.values(),
            key=lambda p: p.health_score,
            reverse=True,
        )
        return sorted_agents[:n]

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all performance metrics."""
        if not self._performances:
            return {"agent_count": 0}

        avg_win_rate = sum(
            p.win_rate_30d for p in self._performances.values()
            if p.total_signals >= 10
        )
        count_with_data = sum(
            1 for p in self._performances.values() if p.total_signals >= 10
        )

        return {
            "agent_count": len(self._performances),
            "avg_win_rate_30d": avg_win_rate / max(count_with_data, 1),
            "avg_calibration_error": sum(
                p.calibration_error for p in self._performances.values()
            ) / max(len(self._performances), 1),
            "top_agents": [
                {
                    "name": p.agent_name,
                    "health_score": p.health_score,
                    "win_rate": p.win_rate_30d,
                    "weight": p.current_weight,
                }
                for p in self.get_top_agents(3)
            ],
            "agents_needing_attention": [
                p.agent_name for p in self._performances.values()
                if p.overconfidence_score > 0.2 or p.calibration_stability < 0.5
            ],
        }


# ═══════════════════════════════════════════════════
# Anomaly Detector
# ═══════════════════════════════════════════════════

class AnomalyDetector:
    """Detects anomalies in agent behavior using statistical tests.

    PURE MATH: Z-scores, distribution shifts, drift detection.
    No LLM involvement.
    """

    DRIFT_THRESHOLD = 0.2  # 20% signal distribution shift
    LATENCY_SPIKE_Z = 3.0  # 3 standard deviations
    CONFIDENCE_DRIFT = 0.15  # 15% calibration drift
    FAILURE_RATE_THRESHOLD = 0.3  # 30% failure rate

    def __init__(self):
        self._anomalies: list[AnomalyRecord] = []
        self._latency_history: dict[str, list[float]] = defaultdict(list)
        self._logger = logger.bind(component="anomaly_detector")

    def detect(
        self,
        performances: dict[str, AgentPerformance],
        latency_data: dict[str, float] | None = None,
    ) -> list[AnomalyRecord]:
        """Run anomaly detection across all agents.

        Args:
            performances: Performance records by agent name.
            latency_data: Latest latency readings by agent name.

        Returns:
            List of newly detected anomalies.
        """
        new_anomalies: list[AnomalyRecord] = []

        for agent_name, perf in performances.items():
            # Skip agents with insufficient data
            if perf.total_signals < 10:
                continue

            # ── Signal Distribution Drift ──
            drift = self._detect_signal_drift(agent_name, perf)
            if drift:
                new_anomalies.append(drift)

            # ── Confidence Drift ──
            confidence_anomaly = self._detect_confidence_drift(agent_name, perf)
            if confidence_anomaly:
                new_anomalies.append(confidence_anomaly)

            # ── Calibration Decay ──
            if perf.calibration_stability < 0.5 and perf.total_signals >= 20:
                new_anomalies.append(AnomalyRecord(
                    agent_name=agent_name,
                    anomaly_type="calibration_decay",
                    severity="HIGH" if perf.calibration_stability < 0.3 else "MEDIUM",
                    description=(
                        f"Calibration stability dropping: {perf.calibration_stability:.2f}. "
                        f"Brier score: {perf.calibration_error:.3f}"
                    ),
                    metric_name="calibration_stability",
                    expected_value=0.8,
                    actual_value=perf.calibration_stability,
                ))

            # ── Overconfidence ──
            if perf.overconfidence_score > 0.25:
                new_anomalies.append(AnomalyRecord(
                    agent_name=agent_name,
                    anomaly_type="overconfidence",
                    severity="HIGH" if perf.overconfidence_score > 0.4 else "MEDIUM",
                    description=(
                        f"Agent overconfident by {perf.overconfidence_score:.1%}. "
                        f"Avg confidence: {perf.avg_confidence:.1%}, "
                        f"Win rate: {perf.win_rate_30d:.1%}"
                    ),
                    metric_name="overconfidence_score",
                    expected_value=0.0,
                    actual_value=perf.overconfidence_score,
                ))

            # ── Failure Rate ──
            if perf.failure_rate > self.FAILURE_RATE_THRESHOLD:
                new_anomalies.append(AnomalyRecord(
                    agent_name=agent_name,
                    anomaly_type="high_failure_rate",
                    severity="HIGH" if perf.failure_rate > 0.5 else "MEDIUM",
                    description=f"Agent failure rate at {perf.failure_rate:.0%}",
                    metric_name="failure_rate",
                    expected_value=0.05,
                    actual_value=perf.failure_rate,
                ))

        # ── Latency Spikes ──
        if latency_data:
            for agent_name, current_latency in latency_data.items():
                latency_anomaly = self._detect_latency_spike(agent_name, current_latency)
                if latency_anomaly:
                    new_anomalies.append(latency_anomaly)

        # Store new anomalies
        self._anomalies.extend(new_anomalies)

        if new_anomalies:
            self._logger.warning(
                "anomalies_detected",
                count=len(new_anomalies),
                agents=list(set(a.agent_name for a in new_anomalies)),
            )

        return new_anomalies

    def _detect_signal_drift(
        self, agent_name: str, perf: AgentPerformance
    ) -> AnomalyRecord | None:
        """Detect if signal distribution has shifted significantly."""
        total = sum(perf.signal_distribution.values())
        if total < 20:
            return None

        # Check if one signal type dominates unexpectedly
        for signal_type, count in perf.signal_distribution.items():
            ratio = count / total if total > 0 else 0
            if ratio > self.DRIFT_THRESHOLD + 0.5:  # >70% in one signal
                return AnomalyRecord(
                    agent_name=agent_name,
                    anomaly_type="signal_distribution_drift",
                    severity="MEDIUM",
                    description=(
                        f"Signal distribution skewed: {signal_type} at {ratio:.0%}. "
                        f"Expected balanced distribution."
                    ),
                    metric_name=f"signal_ratio_{signal_type}",
                    expected_value=0.33,
                    actual_value=ratio,
                )

        return None

    def _detect_confidence_drift(
        self, agent_name: str, perf: AgentPerformance
    ) -> AnomalyRecord | None:
        """Detect if confidence has drifted upward or downward."""
        if perf.total_signals < 10:
            return None

        # Check for sustained high confidence with low win rate
        if perf.avg_confidence > 0.8 and perf.win_rate_30d < 0.5:
            return AnomalyRecord(
                agent_name=agent_name,
                anomaly_type="confidence_inflation",
                severity="HIGH",
                description=(
                    f"High avg confidence ({perf.avg_confidence:.0%}) "
                    f"with low win rate ({perf.win_rate_30d:.0%}). "
                    f"Brier: {perf.calibration_error:.3f}"
                ),
                metric_name="confidence_win_mismatch",
                expected_value=perf.win_rate_30d,
                actual_value=perf.avg_confidence,
            )

        return None

    def _detect_latency_spike(
        self, agent_name: str, current_latency: float
    ) -> AnomalyRecord | None:
        """Detect latency spikes using Z-score."""
        history = self._latency_history.get(agent_name, [])
        history.append(current_latency)
        self._latency_history[agent_name] = history[-50:]  # Keep last 50

        if len(history) < 10:
            return None

        mean = sum(history) / len(history)
        variance = sum((l - mean) ** 2 for l in history) / len(history)
        std_dev = math.sqrt(variance) if variance > 0 else 1.0

        z_score = (current_latency - mean) / std_dev if std_dev > 0 else 0

        if z_score > self.LATENCY_SPIKE_Z:
            severity = "CRITICAL" if z_score > 5.0 else "HIGH"
            return AnomalyRecord(
                agent_name=agent_name,
                anomaly_type="latency_spike",
                severity=severity,
                description=(
                    f"Latency spike: {current_latency:.0f}ms "
                    f"(Z={z_score:.1f}, mean={mean:.0f}ms)"
                ),
                metric_name="latency_ms",
                expected_value=mean,
                actual_value=current_latency,
                z_score=z_score,
            )

        return None

    def get_active_anomalies(self) -> list[AnomalyRecord]:
        """Get unresolved anomalies."""
        return [a for a in self._anomalies if not a.resolved]

    def resolve_anomaly(self, agent_name: str, anomaly_type: str) -> None:
        """Mark anomalies as resolved for an agent."""
        for a in self._anomalies:
            if a.agent_name == agent_name and a.anomaly_type == anomaly_type and not a.resolved:
                a.resolved = True
                a.resolved_at = time.monotonic()

    def get_summary(self) -> dict[str, Any]:
        """Get anomaly summary."""
        active = self.get_active_anomalies()
        return {
            "total_anomalies": len(self._anomalies),
            "active_anomalies": len(active),
            "by_severity": {
                sev: sum(1 for a in active if a.severity == sev)
                for sev in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            },
            "by_type": {
                typ: sum(1 for a in active if a.anomaly_type == typ)
                for typ in set(a.anomaly_type for a in active)
            },
            "latest": [
                {
                    "agent": a.agent_name,
                    "type": a.anomaly_type,
                    "severity": a.severity,
                    "description": a.description[:200],
                }
                for a in active[:5]
            ],
        }


# ═══════════════════════════════════════════════════
# Strategy Allocator
# ═══════════════════════════════════════════════════

class StrategyAllocator:
    """Adjusts agent weights based on performance metrics.

    DETERMINISTIC: Weight updates are bounded, gradual, and math-driven.
    No LLM can change weights. All updates go through:
    1. Performance evaluation
    2. Gradual adjustment (<0.1 per update)
    3. Min/max bounds enforcement
    """

    MIN_WEIGHT = 0.1
    MAX_WEIGHT = 3.0
    DEFAULT_WEIGHT = 1.0
    MAX_DELTA_PER_UPDATE = 0.1  # Max weight change per update

    def __init__(self):
        self._weights: dict[str, float] = {}
        self._weight_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self._logger = logger.bind(component="strategy_allocator")

    def get_weight(self, agent_name: str) -> float:
        """Get current weight for an agent."""
        return self._weights.get(agent_name, self.DEFAULT_WEIGHT)

    def set_initial_weight(self, agent_name: str, weight: float) -> None:
        """Set initial weight for an agent."""
        self._weights[agent_name] = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, weight))

    def update_weights(
        self,
        performances: dict[str, AgentPerformance],
        anomalies: list[AnomalyRecord] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Update agent weights based on performance and anomalies.

        Weight formula:
        - Base: health_score / 100 (0-100 → 0-1 weight)
        - Bonus: +0.1 for high calibration (Brier < 0.15)
        - Penalty: -0.1 for each active HIGH/CRITICAL anomaly
        - Bounds: [MIN_WEIGHT, MAX_WEIGHT]
        - Smoothing: max change of MAX_DELTA_PER_UPDATE per update

        Args:
            performances: Agent performance records.
            anomalies: Current anomalies (optional).

        Returns:
            Dictionary of weight changes: {agent_name: {old, new, delta}}
        """
        changes: dict[str, dict[str, float]] = {}
        anomaly_agents = set()
        anomaly_severities: dict[str, str] = {}

        if anomalies:
            for a in anomalies:
                if not a.resolved:
                    anomaly_agents.add(a.agent_name)
                    # Track worst severity per agent
                    current_sev = anomaly_severities.get(a.agent_name, "LOW")
                    sev_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
                    if sev_order.get(a.severity, 0) > sev_order.get(current_sev, 0):
                        anomaly_severities[a.agent_name] = a.severity

        for agent_name, perf in performances.items():
            old_weight = self._weights.get(agent_name, self.DEFAULT_WEIGHT)

            if perf.total_signals < 5:
                new_weight = self.DEFAULT_WEIGHT
            else:
                # Base: proportional to health score
                base_weight = perf.health_score / 100.0

                # Bonus for well-calibrated agents
                if perf.calibration_error < 0.15 and perf.total_signals >= 10:
                    base_weight += 0.1
                if perf.profit_factor > 2.0 and perf.total_signals >= 10:
                    base_weight += 0.1

                # Penalty for anomalous agents
                if agent_name in anomaly_agents:
                    sev = anomaly_severities[agent_name]
                    if sev == "CRITICAL":
                        base_weight -= 0.4
                    elif sev == "HIGH":
                        base_weight -= 0.2
                    elif sev == "MEDIUM":
                        base_weight -= 0.1

                # Penalty for overconfident agents
                if perf.overconfidence_score > 0.2:
                    base_weight -= 0.15

                # Penalty for drifting calibration
                if perf.calibration_stability < 0.5:
                    base_weight -= 0.1

                new_weight = base_weight

            # Enforce bounds
            new_weight = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, new_weight))

            # Gradual adjustment (max delta per update)
            delta = new_weight - old_weight
            if abs(delta) > self.MAX_DELTA_PER_UPDATE:
                delta = self.MAX_DELTA_PER_UPDATE if delta > 0 else -self.MAX_DELTA_PER_UPDATE
                new_weight = old_weight + delta

            # Round to 2 decimal places
            new_weight = round(new_weight, 2)

            if abs(new_weight - old_weight) > 0.01:
                self._weights[agent_name] = new_weight
                self._weight_history[agent_name].append((time.monotonic(), new_weight))

                changes[agent_name] = {
                    "old": old_weight,
                    "new": new_weight,
                    "delta": round(new_weight - old_weight, 2),
                }

                self._logger.info(
                    "weight_updated",
                    agent=agent_name,
                    old=old_weight,
                    new=new_weight,
                    delta=round(new_weight - old_weight, 2),
                    health_score=perf.health_score,
                )

        return changes

    def get_all_weights(self) -> dict[str, float]:
        """Get all current weights."""
        return dict(self._weights)

    def get_weight_history(self, agent_name: str) -> list[tuple[float, float]]:
        """Get weight change history for an agent."""
        return self._weight_history.get(agent_name, [])


# ═══════════════════════════════════════════════════
# Fleet Manager (Phase 3 Preparation)
# ═══════════════════════════════════════════════════

class FleetManager:
    """Manages multi-symbol orchestration — Phase 3 preparation.

    Coordinates trading across multiple symbols, tracks per-symbol health,
    and detects cross-symbol correlation risks.
    """

    def __init__(self):
        self._fleet_status: dict[str, FleetStatus] = {}
        self._symbol_agents: dict[str, list[str]] = defaultdict(list)
        self._logger = logger.bind(component="fleet_manager")

    def register_symbol(
        self,
        symbol: str,
        agents: list[str],
    ) -> None:
        """Register a trading symbol with its agent roster."""
        self._symbol_agents[symbol] = agents
        if symbol not in self._fleet_status:
            self._fleet_status[symbol] = FleetStatus()

    def update_symbol_health(
        self,
        symbol: str,
        health_score: float,
        regime: str = "UNKNOWN",
    ) -> None:
        """Update health status for a symbol."""
        status = self._fleet_status.get(symbol)
        if status:
            status.per_symbol_health[symbol] = health_score
            status.regime_per_symbol[symbol] = regime
            status.last_updated = time.monotonic()

    def halt_symbol(self, symbol: str, reason: str) -> None:
        """Halt trading for a specific symbol."""
        if symbol in self._fleet_status:
            status = self._fleet_status[symbol]
            if symbol not in status.symbols_halted:
                status.symbols_halted.append(symbol)
            if symbol in status.symbols_active:
                status.symbols_active.remove(symbol)
            self._logger.warning("symbol_halted", symbol=symbol, reason=reason)

    def resume_symbol(self, symbol: str) -> None:
        """Resume trading for a specific symbol."""
        if symbol in self._fleet_status:
            status = self._fleet_status[symbol]
            if symbol in status.symbols_halted:
                status.symbols_halted.remove(symbol)
            if symbol not in status.symbols_active:
                status.symbols_active.append(symbol)
            self._logger.info("symbol_resumed", symbol=symbol)

    def get_active_symbols(self) -> list[str]:
        """Get currently active trading symbols."""
        return list(self._fleet_status.keys())

    def get_fleet_summary(self) -> dict[str, Any]:
        """Get a summary of the entire fleet."""
        return {
            "total_symbols": len(self._fleet_status),
            "active_symbols": sum(
                1 for s in self._fleet_status.values()
                if s.symbols_active
            ),
            "halted_symbols": sum(
                1 for s in self._fleet_status.values()
                if s.symbols_halted
            ),
            "regimes": {
                sym: status.regime_per_symbol.get(sym, "UNKNOWN")
                for sym, status in self._fleet_status.items()
            },
        }


# ═══════════════════════════════════════════════════
# Conductor — Central Meta-Cognition
# ═══════════════════════════════════════════════════

class Conductor:
    """Central meta-cognition coordinator for Noema Nexus.

    The Conductor monitors ALL agent performance, detects anomalies,
    adjusts agent weights, and coordinates multi-symbol trading.

    Key properties:
    - All metrics are PURE MATH (no LLM in critical path)
    - Weight adjustments are bounded and gradual
    - Anomaly detection uses statistical tests
    - Fleet management is Phase 3 preparation

    Usage:
        conductor = Conductor()
        conductor.record_signal("bull-analyst", "BULLISH", 0.8, outcome=True, pnl=50)
        conductor.run_diagnostics()  # Returns comprehensive system health
    """

    def __init__(self, config: Any = None):
        self.config = config
        self.state = ConductorState.IDLE
        self.performance = PerformanceAggregator(window_size=30)
        self.anomalies = AnomalyDetector()
        self.allocator = StrategyAllocator()
        self.fleet = FleetManager()
        self._logger = logger.bind(component="conductor")
        self._diagnostic_interval = 3600.0  # 1 hour
        self._last_diagnostics: float = 0.0
        self._team_health: dict[str, Any] = {}

    # ── Signal Recording ────────────────────────────────────────────

    def record_signal(
        self,
        agent_name: str,
        signal: str,
        confidence: float,
        outcome: bool | None = None,
        pnl: float = 0.0,
        latency_ms: float = 0.0,
        team: str = "analysis",
    ) -> AgentPerformance:
        """Record a trading signal for performance tracking.

        Args:
            agent_name: Agent name.
            signal: Signal direction.
            confidence: Agent confidence (0.0-1.0).
            outcome: Whether signal was correct.
            pnl: Profit/loss in account currency.
            latency_ms: Processing latency.
            team: Agent's team (analysis, critic, execution).

        Returns:
            Updated AgentPerformance.
        """
        return self.performance.record_signal(
            agent_name=agent_name,
            signal=signal,
            confidence=confidence,
            outcome=outcome,
            pnl=pnl,
            latency_ms=latency_ms,
        )

    async def record_team_health(
        self,
        team_type: str,
        health_score: float,
        agent_count: int,
        healthy_count: int,
        avg_latency_ms: float,
    ) -> None:
        """Record team-level health metrics.

        Called by TeamManager to feed team health into meta-cognition.
        """
        self._team_health[team_type] = {
            "health_score": health_score,
            "agent_count": agent_count,
            "healthy_count": healthy_count,
            "avg_latency_ms": avg_latency_ms,
            "updated_at": time.monotonic(),
        }

    # ── Diagnostics ─────────────────────────────────────────────────

    async def run_diagnostics(self) -> dict[str, Any]:
        """Run comprehensive system diagnostics.

        Returns a complete health picture of the entire agent system.
        PURE MATH — no LLM involvement.

        Returns:
            Dictionary with performance, anomalies, weights, fleet status.
        """
        self.state = ConductorState.MONITORING
        self._last_diagnostics = time.monotonic()

        # ── Collect all performance data ──
        all_performances = self.performance.get_all_performances()

        # ── Detect anomalies ──
        latency_data = {}
        for name, perf in all_performances.items():
            if perf.avg_latency_ms > 0:
                latency_data[name] = perf.avg_latency_ms
        detected = self.anomalies.detect(all_performances, latency_data)

        # ── Update weights ──
        weight_changes = self.allocator.update_weights(all_performances, detected)

        # ── Build comprehensive report ──
        report = {
            "timestamp": time.monotonic(),
            "state": self.state.value,
            "performance": self.performance.get_summary(),
            "anomalies": self.anomalies.get_summary(),
            "weights": self.allocator.get_all_weights(),
            "weight_changes": weight_changes,
            "fleet": self.fleet.get_fleet_summary(),
            "team_health": dict(self._team_health),
        }

        self._logger.info(
            "diagnostics_complete",
            agents=len(all_performances),
            anomalies=len(detected),
            weight_changes=len(weight_changes),
        )

        if detected:
            self.state = ConductorState.ALERTING
        else:
            self.state = ConductorState.IDLE

        return report

    async def run_continuous_monitoring(self, interval: float = 300.0) -> None:
        """Run continuous monitoring loop (background task).

        Args:
            interval: Seconds between diagnostic runs (default 5 min).
        """
        self.state = ConductorState.MONITORING
        while self.state != ConductorState.HALTED:
            try:
                await self.run_diagnostics()
            except Exception as e:
                self._logger.error("conductor_monitoring_error", error=str(e))
            await asyncio.sleep(interval)

    def halt(self) -> None:
        """Halt the conductor monitoring."""
        self.state = ConductorState.HALTED
        self._logger.info("conductor_halted")

    # ── Utility ─────────────────────────────────────────────────────

    def get_agent_health_report(self, agent_name: str) -> dict[str, Any]:
        """Get a detailed health report for a specific agent."""
        perf = self.performance.get_performance(agent_name)
        anomalies = [
            a for a in self.anomalies.get_active_anomalies()
            if a.agent_name == agent_name
        ]
        weight = self.allocator.get_weight(agent_name)

        return {
            "agent_name": agent_name,
            "team": perf.team,
            "performance": {
                "total_signals": perf.total_signals,
                "win_rate_30d": perf.win_rate_30d,
                "win_rate_90d": perf.win_rate_90d,
                "calibration_error": perf.calibration_error,
                "overconfidence_score": perf.overconfidence_score,
                "calibration_stability": perf.calibration_stability,
                "sharpe_contribution": perf.sharpe_contribution,
                "profit_factor": perf.profit_factor,
                "avg_latency_ms": perf.avg_latency_ms,
                "health_score": perf.health_score,
            },
            "weight": weight,
            "weight_history": self.allocator.get_weight_history(agent_name)[-10:],
            "anomalies": [
                {
                    "type": a.anomaly_type,
                    "severity": a.severity,
                    "description": a.description,
                    "resolved": a.resolved,
                }
                for a in anomalies
            ],
            "signal_distribution": perf.signal_distribution,
        }

    def adjust_weight(
        self,
        agent_name: str,
        factor: float,
        reason: str = "manual",
    ) -> float:
        """Manually adjust an agent's weight (for human overrides).

        Args:
            agent_name: Agent to adjust.
            factor: Multiplier (1.0 = no change, 0.5 = half, 2.0 = double).
            reason: Reason for the adjustment.

        Returns:
            New weight.
        """
        current = self.allocator.get_weight(agent_name)
        new_weight = round(current * factor, 2)
        new_weight = max(StrategyAllocator.MIN_WEIGHT, min(StrategyAllocator.MAX_WEIGHT, new_weight))
        self.allocator.set_initial_weight(agent_name, new_weight)
        self._logger.info(
            "manual_weight_adjustment",
            agent=agent_name,
            old=current,
            new=new_weight,
            factor=factor,
            reason=reason,
        )
        return new_weight
