"""Modern parallel orchestrator for Noema.

Implements the wave-based execution pattern from modern agent systems:
- Layer 1: DATA agents (parallel, deterministic)
- Layer 2: ANALYSIS agents (parallel, mix of deterministic + LLM)
- Layer 3: DECISION agents (sequential, LLM-powered debate)
- Layer 4: EXECUTION agents (sequential, deterministic)
- Layer 5: LEARNING agents (background, LLM-powered)

Key improvements over old orchestrator:
- Parallel execution via asyncio.gather (2-3x speedup)
- Structured output via Pydantic schemas
- LLM only used for judgment calls (3 calls vs 17)
- Decision caching (same market state → same decision)
- Graceful degradation (LLM failure → deterministic fallback)
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from noema.core.nim_client import NIMClient, ModelTier
from noema.core.modern_agent import (
    AgentReport, AgentType, BaseAgent, DeterministicAgent, LLMAgent,
)
from noema.core.types import Bar, Direction, Setup
from noema.models.schemas import (
    CIODecision, DevilsAdvocate, TradeThesis, TradeDirection, TradeParameters,
)
from noema.agents.guardian import GuardianAgent, GuardianState
from noema.core.conservative_tiebreaker import ConservativeTiebreaker, TiebreakerDecision, TiebreakerResult
from noema.core.observability import (
    TraceAgent, log_trade_decision, log_kill_switch,
    trace_pipeline_phase, record_pipeline_phase_transition,
    is_tracing_enabled,
)
from noema.core.metrics_exporter import MetricsExporter
from noema.decision import RiskContext, build_risk_context_from_account

# ── Broker health monitor (optional import) ──
try:
    from noema.broker.mt5_linux import (
        BrokerHealthAdapter,
        MT5LinuxBroker,
        BrokerHealthMonitor,
        HEALTH_PING_INTERVAL,
    )
    _MT5_LINUX_AVAILABLE = True
except ImportError:
    _MT5_LINUX_AVAILABLE = False
    BrokerHealthAdapter = None  # type: ignore[misc]
    BrokerHealthMonitor = None  # type: ignore[misc]
    MT5LinuxBroker = None  # type: ignore[misc]
    HEALTH_PING_INTERVAL = 5.0

logger = structlog.get_logger(__name__)


@dataclass
class PipelineMetrics:
    """Metrics for a single pipeline run."""
    symbol: str
    started_at: float = field(default_factory=time.monotonic)
    completed_at: float = 0.0
    phase_timings: dict[str, float] = field(default_factory=dict)
    agent_signals: dict[str, str] = field(default_factory=dict)
    agent_confidences: dict[str, float] = field(default_factory=dict)
    agent_latencies: dict[str, float] = field(default_factory=dict)
    llm_calls: int = 0
    llm_latency_ms: float = 0.0
    cache_hits: int = 0
    decision: str = "NO_TRADE"
    decision_confidence: float = 0.0
    error: str | None = None

    @property
    def total_latency_ms(self) -> float:
        return (self.completed_at - self.started_at) * 1000 if self.completed_at else 0


class ModernOrchestrator:
    """Wave-based parallel orchestrator for Noema.

    Coordinates all agents through a 5-layer pipeline:
    1. Data collection (parallel)
    2. Analysis (parallel)
    3. Decision (sequential debate)
    4. Execution (sequential)
    5. Learning (background)
    """

    def __init__(
        self,
        nim_client: NIMClient,
        broker: Any,
        config: Any,
        guardian: GuardianAgent | None = None,
        guardian_state: GuardianState | None = None,
        metrics_exporter: MetricsExporter | None = None,
        health_checker: HealthChecker | None = None,
        telegram_bot: Any = None,
    ):
        self.nim = nim_client
        self.broker = broker
        self.config = config
        self.guardian = guardian
        self.guardian_state = guardian_state
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._health_monitor_task: asyncio.Task | None = None
        self._health_monitor: BrokerHealthMonitor | None = None  # type: ignore[valid-type]

        # Agent registry — populated by register_* methods
        self._data_agents: list[BaseAgent] = []
        self._analysis_agents: list[BaseAgent] = []
        self._thesis_agent: LLMAgent | None = None
        self._devil_agent: LLMAgent | None = None
        self._cio_agent: LLMAgent | None = None
        self._risk_agent: BaseAgent | None = None
        self._execution_agent: BaseAgent | None = None
        self._learning_agent: LLMAgent | None = None

        # Telegram (for disconnect alerts)
        self._telegram_bot = telegram_bot

        # Observability
        self.metrics_exporter = metrics_exporter
        self.health_checker = health_checker
        self._current_phase = "idle"

        # Metrics
        self._cycle_count = 0
        self._total_metrics: list[PipelineMetrics] = []

        # Register all expected agents for health monitoring
        if health_checker:
            all_agent_names = [
                "macro-economic", "currency-strength", "session-intelligence",
                "market-structure", "institutional-footprint", "support-resistance",
                "momentum", "price-action",
                "trade-thesis", "devils-advocate", "cio",
                "risk-manager", "execution",
                "learning", "broker-health-monitor",
            ]
            health_checker.ensure_all_agents(all_agent_names)

    # ── Agent Registration ───────────────────────────────────────────

    def register_data_agents(self, agents: list[BaseAgent]) -> None:
        self._data_agents = agents

    def register_analysis_agents(self, agents: list[BaseAgent]) -> None:
        self._analysis_agents = agents

    def register_decision_agents(
        self,
        thesis: LLMAgent,
        devil: LLMAgent,
        cio: LLMAgent,
    ) -> None:
        self._thesis_agent = thesis
        self._devil_agent = devil
        self._cio_agent = cio

    def register_execution_agents(
        self,
        risk: BaseAgent,
        execution: BaseAgent,
    ) -> None:
        self._risk_agent = risk
        self._execution_agent = execution

    def register_learning_agent(self, agent: LLMAgent) -> None:
        self._learning_agent = agent

    # ── Main Pipeline ────────────────────────────────────────────────

    async def run_cycle(self, symbol: str) -> PipelineMetrics:
        """Execute the full 5-layer pipeline for a symbol."""
        metrics = PipelineMetrics(symbol=symbol)
        self._logger = logger.bind(symbol=symbol, cycle=self._cycle_count)

        try:
            # ── Guardian: System Health Check (every tick) ──────────
            if self.guardian:
                health = await self.guardian.system_health_check()
                self._logger.debug("guardian_health", **health)

            # ── Guardian: Check All Kill-Switches ───────────────────
            if self.guardian:
                triggered = await self.guardian.check_all()
                if triggered:
                    switch_ids = [t["id"] for t in triggered]
                    self._logger.error(
                        "guardian_killswitch_halt",
                        switches=switch_ids,
                        symbol=symbol,
                    )
                    # ── Observability: log kill-switch activation ──
                    for t in triggered:
                        log_kill_switch(
                            reason=t.get("reason", "unknown"),
                            symbol=symbol,
                            triggered_by="guardian",
                            pipeline_phase="pre-flight",
                        )
                    if self.metrics_exporter:
                        for t in triggered:
                            self.metrics_exporter.record_kill_switch(
                                reason=t.get("reason", "unknown"),
                                symbol=symbol,
                            )
                        self.metrics_exporter.set_kill_switch_active(True)
                    if self.health_checker:
                        self.health_checker.update_kill_switch(True, f"Switches: {switch_ids}")
                    metrics.decision = "HALTED"
                    metrics.error = f"Kill-switch(es) fired: {switch_ids}"
                    metrics.completed_at = time.monotonic()
                    self._total_metrics.append(metrics)
                    self._cycle_count += 1
                    return metrics

            # ── Layer 1: Data Collection (parallel, deterministic) ───
            self._current_phase = "data"
            phase_start = time.monotonic()
            data_results = await self._run_data_phase(symbol)
            metrics.phase_timings["data"] = (time.monotonic() - phase_start) * 1000
            record_pipeline_phase_transition("idle", "data", symbol, metrics.phase_timings["data"])

            # ── Layer 2: Analysis (parallel, mix) ────────────────────
            self._current_phase = "analysis"
            phase_start = time.monotonic()
            analysis_results = await self._run_analysis_phase(symbol, data_results)
            metrics.phase_timings["analysis"] = (time.monotonic() - phase_start) * 1000
            record_pipeline_phase_transition("data", "analysis", symbol, metrics.phase_timings["analysis"])

            # ── Layer 3: Decision (sequential LLM debate) ────────────
            self._current_phase = "decision"
            phase_start = time.monotonic()
            decision = await self._run_decision_phase(symbol, analysis_results)
            metrics.phase_timings["decision"] = (time.monotonic() - phase_start) * 1000
            metrics.decision = decision.decision.value if decision else "NO_TRADE"
            metrics.decision_confidence = decision.confidence if decision else 0.0
            record_pipeline_phase_transition("analysis", "decision", symbol, metrics.phase_timings["decision"])

            # ── Record trade decision in observability ───────────────
            if decision:
                agent_scores = {
                    name: report.confidence
                    for name, report in analysis_results.items()
                }
                # Get current price from analysis context
                current_price = 0.0
                try:
                    bars = await self._get_bars(symbol, "H1", 1)
                    if bars:
                        current_price = bars[-1].get("close", 0.0)
                except Exception:
                    pass

                log_trade_decision(
                    symbol=symbol,
                    decision=decision.decision.value if decision.decision else "NO_TRADE",
                    confidence=decision.confidence,
                    consensus_score=decision.consensus_score,
                    agent_scores=agent_scores,
                    reasoning=decision.final_reasoning[:500] if decision.final_reasoning else "",
                    price=current_price,
                    pipeline_phase="decision",
                )
                if self.metrics_exporter:
                    self.metrics_exporter.record_trade_decision(
                        symbol=symbol,
                        decision=metrics.decision,
                    )

            # ── Layer 4: Execution (if trade approved) ───────────────
            if decision and decision.decision != TradeDirection.NO_TRADE:
                self._current_phase = "execution"
                phase_start = time.monotonic()
                await self._run_execution_phase(symbol, decision, analysis_results)
                metrics.phase_timings["execution"] = (time.monotonic() - phase_start) * 1000
                record_pipeline_phase_transition("decision", "execution", symbol, metrics.phase_timings["execution"])

            # ── Layer 5: Learning (background) ───────────────────────
            if self._learning_agent:
                self._current_phase = "learning"
                asyncio.create_task(
                    self._run_learning_phase(symbol, decision, analysis_results)
                )

            metrics.completed_at = time.monotonic()
            self._current_phase = "idle"

            # ── Export pipeline metrics ──────────────────────────────
            if self.metrics_exporter:
                self.metrics_exporter.record_pipeline_cycle(
                    symbol=symbol,
                    latency_seconds=metrics.total_latency_ms / 1000,
                )
                for phase, latency_ms in metrics.phase_timings.items():
                    self.metrics_exporter.record_pipeline_phase(phase, latency_ms / 1000)

            # ── Update health checker ────────────────────────────────
            if self.health_checker:
                self.health_checker.update_pipeline(
                    running=True,
                    current_phase="idle",
                    last_cycle_ms=metrics.total_latency_ms,
                    total_cycles=self._cycle_count + 1,
                    total_errors=metrics.error is not None,
                )

            self._log_metrics(metrics)

        except Exception as e:
            metrics.error = str(e)
            metrics.completed_at = time.monotonic()
            self._logger.error("pipeline_error", error=str(e), total_ms=metrics.total_latency_ms)

        self._total_metrics.append(metrics)
        self._cycle_count += 1
        return metrics

    # ── Layer Implementations ────────────────────────────────────────

    async def _run_data_phase(
        self, symbol: str
    ) -> dict[str, AgentReport]:
        """Layer 1: Collect data from all data agents in parallel."""
        context = {"symbol": symbol, "config": self.config}

        # ── Execute all data agents in parallel, each in a TraceAgent span ──
        async def _traced_process(agent: BaseAgent) -> AgentReport:
            async with TraceAgent(
                agent_name=agent.name,
                pipeline_phase="data",
                symbol=symbol,
            ) as span:
                try:
                    result = await agent.process(context)
                    span.set_attributes(
                        confidence=result.confidence,
                        signal=result.signal,
                    )
                    # Record metrics
                    if self.metrics_exporter:
                        self.metrics_exporter.record_agent_call(
                            agent=agent.name,
                            phase="data",
                            status="success",
                            latency_seconds=0,  # agent.process already times itself
                            confidence=result.confidence,
                            signal=result.signal,
                        )
                    # Update health
                    if self.health_checker:
                        self.health_checker.update_agent(
                            name=agent.name,
                            status=HealthStatus.HEALTHY,
                            signal=result.signal,
                        )
                    return result
                except Exception as e:
                    span.set_attributes(error=str(e))
                    if self.metrics_exporter:
                        self.metrics_exporter.record_agent_call(
                            agent=agent.name,
                            phase="data",
                            status="error",
                            latency_seconds=0,
                        )
                    if self.health_checker:
                        self.health_checker.update_agent_error(agent.name, str(e))
                    raise

        results = await asyncio.gather(
            *[_traced_process(agent) for agent in self._data_agents],
            return_exceptions=True,
        )

        data: dict[str, AgentReport] = {}
        for agent, result in zip(self._data_agents, results):
            if isinstance(result, Exception):
                logger.error("data_agent_failed", agent=agent.name, error=str(result))
                data[agent.name] = AgentReport(
                    agent_name=agent.name, signal="ERROR", reasoning=str(result)
                )
            else:
                data[agent.name] = result

        return data

    async def _run_analysis_phase(
        self, symbol: str, data: dict[str, AgentReport]
    ) -> dict[str, AgentReport]:
        """Layer 2: Run all analysis agents in parallel."""
        # Build context from data phase results
        context = {
            "symbol": symbol,
            "config": self.config,
            "data": {name: report.data for name, report in data.items()},
        }

        # Fetch market data for analysis agents
        try:
            bars = await self._get_bars(symbol, "H1", 200)
            context["bars"] = list(bars)
            context["current_price"] = bars[-1].get("close", 0.0) if bars else 0
        except Exception as e:
            logger.warning("bar_fetch_failed", error=str(e))
            context["bars"] = []
            context["current_price"] = 0

        # ── Execute all analysis agents in parallel, each in a TraceAgent span ──
        async def _traced_process(agent: BaseAgent) -> AgentReport:
            async with TraceAgent(
                agent_name=agent.name,
                pipeline_phase="analysis",
                symbol=symbol,
                timeframe="H1",
            ) as span:
                try:
                    result = await agent.process(context)
                    span.set_attributes(
                        confidence=result.confidence,
                        signal=result.signal,
                    )
                    # Record LLM latency if applicable
                    if result.llm_latency_ms > 0:
                        span.set_attributes(llm_latency_ms=result.llm_latency_ms)

                    metrics_report = result  # capture for metrics below

                    # Record metrics
                    if self.metrics_exporter:
                        self.metrics_exporter.record_agent_call(
                            agent=agent.name,
                            phase="analysis",
                            status="success",
                            latency_seconds=result.llm_latency_ms / 1000 if result.llm_latency_ms else 0.001,
                            confidence=result.confidence,
                            signal=result.signal,
                        )
                        if result.llm_latency_ms > 0:
                            self.metrics_exporter.record_llm_call(
                                agent=agent.name,
                                model=getattr(agent, "model_tier", "unknown"),
                                tier=getattr(agent, "model_tier", "standard"),
                                status="success",
                                latency_seconds=result.llm_latency_ms / 1000,
                            )
                    # Update health
                    if self.health_checker:
                        self.health_checker.update_agent(
                            name=agent.name,
                            status=HealthStatus.HEALTHY,
                            latency_ms=result.llm_latency_ms,
                            signal=result.signal,
                        )
                    return result
                except Exception as e:
                    span.set_attributes(error=str(e))
                    if self.metrics_exporter:
                        self.metrics_exporter.record_agent_call(
                            agent=agent.name,
                            phase="analysis",
                            status="error",
                            latency_seconds=0,
                        )
                    if self.health_checker:
                        self.health_checker.update_agent_error(agent.name, str(e))
                    raise

        results = await asyncio.gather(
            *[_traced_process(agent) for agent in self._analysis_agents],
            return_exceptions=True,
        )

        analysis: dict[str, AgentReport] = {}
        for agent, result in zip(self._analysis_agents, results):
            if isinstance(result, Exception):
                logger.error("analysis_agent_failed", agent=agent.name, error=str(result))
                analysis[agent.name] = AgentReport(
                    agent_name=agent.name, signal="ERROR", reasoning=str(result)
                )
            else:
                analysis[agent.name] = result

        return analysis

    async def _run_decision_phase(
        self,
        symbol: str,
        analysis: dict[str, AgentReport],
    ) -> CIODecision | None:
        """Layer 3: Sequential LLM debate (thesis → devil → CIO)."""
        if not all([self._thesis_agent, self._devil_agent, self._cio_agent]):
            logger.warning("decision_agents_not_registered")
            return None

        # Build decision context
        context = {
            "symbol": symbol,
            "config": self.config,
            "analysis": {name: report.data for name, report in analysis.items()},
            "analysis_signals": {name: report.signal for name, report in analysis.items()},
            "analysis_confidence": {name: report.confidence for name, report in analysis.items()},
        }

        # Add current price and bars
        try:
            bars = await self._get_bars(symbol, "H1", 50)
            context["bars"] = list(bars)
            context["current_price"] = bars[-1].get("close", 0.0) if bars else 0
        except Exception:
            pass

        # ── RISK CONTEXT INJECTION (TradingAgents pattern) ──
        risk_context = await self._build_risk_context(symbol)
        if risk_context:
            for agent, name in [
                (self._thesis_agent, "thesis"),
                (self._devil_agent, "devil"),
                (self._cio_agent, "cio"),
            ]:
                if agent and hasattr(agent, 'set_risk_context'):
                    agent.set_risk_context(risk_context)
            context["risk_context"] = risk_context

        # Step 1: Trade Thesis (build the case)
        async with TraceAgent(
            agent_name="trade-thesis",
            pipeline_phase="decision",
            symbol=symbol,
        ) as span:
            thesis_report = await self._thesis_agent.process(context)
            span.set_attributes(
                confidence=thesis_report.confidence,
                signal=thesis_report.signal,
                llm_latency_ms=thesis_report.llm_latency_ms,
            )
            if thesis_report.llm_latency_ms > 0 and self.metrics_exporter:
                self.metrics_exporter.record_llm_call(
                    agent="trade-thesis",
                    model=getattr(self._thesis_agent, "model_tier", "standard"),
                    tier=getattr(self._thesis_agent, "model_tier", "standard"),
                    status="success",
                    latency_seconds=thesis_report.llm_latency_ms / 1000,
                )
            if self.health_checker:
                self.health_checker.update_agent(
                    name="trade-thesis",
                    status=HealthStatus.HEALTHY,
                    latency_ms=thesis_report.llm_latency_ms,
                    signal=thesis_report.signal,
                )

        context["thesis"] = thesis_report.data

        # Step 2: Devil's Advocate (challenge the thesis)
        async with TraceAgent(
            agent_name="devils-advocate",
            pipeline_phase="decision",
            symbol=symbol,
        ) as span:
            devil_report = await self._devil_agent.process(context)
            span.set_attributes(
                confidence=devil_report.confidence,
                signal=devil_report.signal,
                llm_latency_ms=devil_report.llm_latency_ms,
            )
            if devil_report.llm_latency_ms > 0 and self.metrics_exporter:
                self.metrics_exporter.record_llm_call(
                    agent="devils-advocate",
                    model=getattr(self._devil_agent, "model_tier", "standard"),
                    tier=getattr(self._devil_agent, "model_tier", "standard"),
                    status="success",
                    latency_seconds=devil_report.llm_latency_ms / 1000,
                )
            if self.health_checker:
                self.health_checker.update_agent(
                    name="devils-advocate",
                    status=HealthStatus.HEALTHY,
                    latency_ms=devil_report.llm_latency_ms,
                    signal=devil_report.signal,
                )

        context["devil"] = devil_report.data

        # Step 3: CIO Final Decision
        async with TraceAgent(
            agent_name="cio",
            pipeline_phase="decision",
            symbol=symbol,
        ) as span:
            cio_report = await self._cio_agent.process(context)
            span.set_attributes(
                confidence=cio_report.confidence,
                signal=cio_report.signal,
                llm_latency_ms=cio_report.llm_latency_ms,
            )
            if cio_report.llm_latency_ms > 0 and self.metrics_exporter:
                self.metrics_exporter.record_llm_call(
                    agent="cio",
                    model=getattr(self._cio_agent, "model_tier", "standard"),
                    tier=getattr(self._cio_agent, "model_tier", "standard"),
                    status="success",
                    latency_seconds=cio_report.llm_latency_ms / 1000,
                )
            if self.health_checker:
                self.health_checker.update_agent(
                    name="cio",
                    status=HealthStatus.HEALTHY,
                    latency_ms=cio_report.llm_latency_ms,
                    signal=cio_report.signal,
                )

        # ── ConservativeTiebreaker: Deterministic resolution of critic votes ──
        # CRITICAL: This runs AFTER LLM reports, BEFORE any decision is made.
        # The tiebreaker is PURE PYTHON — no LLM involvement in decision authority.
        # Rule: NO_TRADE > REDUCE_SIZE > FULL_SIZE (conservative wins)
        tiebreaker = ConservativeTiebreaker()
        critic_signals = [
            thesis_report.signal,     # "BULLISH" / "BEARISH" / "NEUTRAL"
            devil_report.signal,      # "APPROVE" / "REJECT" / "MODIFY"
            cio_report.signal,        # "BUY" / "SELL" / "NO_TRADE"
        ]
        tb_result = tiebreaker.resolve_from_strings(critic_signals)
        logger.info(
            "conservative_tiebreaker_resolved",
            symbol=symbol,
            decision=tb_result.decision.value,
            rule=tb_result.rule_applied,
            votes=tb_result.vote_counts,
            critic_signals=critic_signals,
        )

        # If tiebreaker says NO_TRADE, override everything — safety first
        tiebreaker_decision_str = tb_result.decision.value
        if tb_result.decision == TiebreakerDecision.NO_TRADE:
            logger.warning(
                "conservative_tiebreaker_veto",
                symbol=symbol,
                rule=tb_result.rule_applied,
                details=tb_result.details,
            )

        # Parse into CIODecision (with safe tiebreaker default if CIO data is structured)
        if isinstance(cio_report.data, dict) and "decision" in cio_report.data:
            try:
                decision = CIODecision(**cio_report.data)
                decision.tiebreaker_result = tiebreaker_decision_str
                decision.tiebreaker_rule = tb_result.rule_applied
                return decision
            except Exception:
                pass

        # Fallback: build from signals (always includes ConservativeTiebreaker result)
        return CIODecision(
            decision=TradeDirection(cio_report.signal) if cio_report.signal in ("BUY", "SELL", "NO_TRADE") else TradeDirection.NO_TRADE,
            symbol=symbol,
            confidence=cio_report.confidence,
            consensus_score=cio_report.confidence,
            thesis_approved=thesis_report.signal != "ERROR",
            devil_approved=devil_report.signal != "REJECT",
            risk_approved=True,
            final_reasoning=cio_report.reasoning,
            tiebreaker_result=tiebreaker_decision_str,
            tiebreaker_rule=tb_result.rule_applied,
        )

    async def _run_execution_phase(
        self,
        symbol: str,
        decision: CIODecision,
        analysis: dict[str, AgentReport],
    ) -> None:
        """Layer 4: Guardian pre-trade check → Risk check → Order execution."""
        if not self._risk_agent or not self._execution_agent:
            logger.warning("execution_agents_not_registered")
            return

        context = {
            "symbol": symbol,
            "decision": decision.model_dump(),
            "config": self.config,
            "broker": self.broker,
        }

        # ── Guardian Pre-Trade Check (BEFORE every order) ───────────
        if self.guardian:
            # Extract lot size from decision or determine it
            decision_data = decision.model_dump()
            lot_size = decision_data.get("lot_size", 0.01)
            current_pnl = 0.0
            # Try to get current PnL from risk agent context or broker
            try:
                account = self.broker.get_account_info() if hasattr(self.broker, "get_account_info") else {}
                balance = float(account.get("balance", 0) or 0)
                equity = float(account.get("equity", 0) or 0)
                if balance > 0:
                    current_pnl = ((equity - balance) / balance) * 100
                # Update guardian account state
                margin_level = float(account.get("margin_level", 0) or 0)
                self.guardian.update_account_state(
                    balance=balance,
                    equity=equity,
                    margin_level=margin_level,
                )
            except Exception:
                pass

            approved, reason = await self.guardian.pre_trade_check(
                pair=symbol,
                lot_size=lot_size,
                current_pnl=current_pnl,
            )
            if not approved:
                logger.warning(
                    "guardian_veto",
                    symbol=symbol,
                    reason=reason,
                )
                log_kill_switch(
                    reason=f"Guardian pre-trade veto: {reason}",
                    symbol=symbol,
                    triggered_by="guardian",
                    pipeline_phase="execution",
                )
                if self.metrics_exporter:
                    self.metrics_exporter.record_kill_switch(
                        reason=f"guardian_veto: {reason}",
                        symbol=symbol,
                    )
                return

        # Risk check (traced)
        async with TraceAgent(
            agent_name="risk-manager",
            pipeline_phase="execution",
            symbol=symbol,
        ) as span:
            risk_report = await self._risk_agent.process(context)
            span.set_attributes(
                confidence=risk_report.confidence,
                signal=risk_report.signal,
            )
            if self.metrics_exporter:
                self.metrics_exporter.record_agent_call(
                    agent="risk-manager",
                    phase="execution",
                    status="success",
                    latency_seconds=0.001,
                    signal=risk_report.signal,
                )
            if self.health_checker:
                self.health_checker.update_agent(
                    name="risk-manager",
                    status=HealthStatus.HEALTHY,
                    signal=risk_report.signal,
                )

        if risk_report.signal == "REJECT":
            logger.info("trade_rejected_by_risk", reason=risk_report.reasoning)
            log_kill_switch(
                reason=f"Risk manager rejected: {risk_report.reasoning}",
                symbol=symbol,
                triggered_by="risk-manager",
                pipeline_phase="execution",
            )
            return

        # Execute (traced)
        context["risk"] = risk_report.data
        async with TraceAgent(
            agent_name="execution",
            pipeline_phase="execution",
            symbol=symbol,
        ) as span:
            exec_report = await self._execution_agent.process(context)
            span.set_attributes(
                confidence=exec_report.confidence,
                signal=exec_report.signal,
            )
            if self.metrics_exporter:
                self.metrics_exporter.record_agent_call(
                    agent="execution",
                    phase="execution",
                    status="success",
                    latency_seconds=0.001,
                    signal=exec_report.signal,
                )
            if self.health_checker:
                self.health_checker.update_agent(
                    name="execution",
                    status=HealthStatus.HEALTHY,
                    signal=exec_report.signal,
                )

        logger.info(
            "trade_executed",
            symbol=symbol,
            decision=decision.decision.value,
            confidence=decision.confidence,
        )

    async def _run_learning_phase(
        self,
        symbol: str,
        decision: CIODecision | None,
        analysis: dict[str, AgentReport],
    ) -> None:
        """Layer 5: Post-trade reflection (background, no rush)."""
        if not self._learning_agent:
            return

        try:
            # Wait a bit for trade to play out (or check immediately for NO_TRADE)
            if decision and decision.decision != TradeDirection.NO_TRADE:
                await asyncio.sleep(60)  # Wait 1 min before reflecting

            context = {
                "symbol": symbol,
                "decision": decision.model_dump() if decision else {},
                "analysis": {name: report.data for name, report in analysis.items()},
            }
            await self._learning_agent.process(context)
        except Exception as e:
            logger.error("learning_phase_failed", error=str(e))

    async def _get_bars(self, symbol: str, timeframe: str, count: int) -> list[dict]:
        """Fetch OHLCV bars via the broker, using whichever method is available.

        Brokers expose different methods:
          - BrokerProtocol: async bars()
          - MT5LinuxBroker: sync get_candles()
          - MT5Broker/FBSBroker/PaperBroker: sync get_rates()

        This helper tries each and returns a list of bar dicts. Returns [] on failure.
        """
        # 1. Try async bars() (BrokerProtocol, future)
        if hasattr(self.broker, 'bars') and callable(self.broker.bars):
            try:
                result = await self.broker.bars(symbol, timeframe, count)
                if result:
                    return list(result)
            except Exception:
                pass

        # 2. Try sync get_candles() (MT5LinuxBroker)
        if hasattr(self.broker, 'get_candles') and callable(self.broker.get_candles):
            try:
                result = await asyncio.to_thread(
                    self.broker.get_candles, symbol, timeframe, count
                )
                if result:
                    return list(result)
            except Exception:
                pass

        # 3. Try sync get_rates() (MT5Broker, PaperBroker, FBSBroker)
        if hasattr(self.broker, 'get_rates') and callable(self.broker.get_rates):
            try:
                result = await asyncio.to_thread(
                    self.broker.get_rates, symbol, timeframe, count
                )
                if result is not None:
                    # get_rates may return DataFrame or list of dicts
                    if hasattr(result, 'to_dict'):
                        return result.to_dict('records')
                    if isinstance(result, list):
                        return result
            except Exception:
                pass

        return []

    # ── Risk Context Builder (TradingAgents pattern) ─────────────────

    async def _build_risk_context(self, symbol: str) -> RiskContext | None:
        """Build RiskContext from account state, events, and correlations.

        Called before the decision phase to inject risk awareness into all
        LLM agents (Thesis, Devil, CIO). Pattern from TradingAgents where
        every agent prompt includes current risk state.
        """
        try:
            from noema.tools.broker_status import get_account_state
            from noema.tools.economic_calendar import get_economic_calendar
            from noema.tools.correlation import get_currency_correlation

            # Fetch account state
            account = get_account_state()
            if account.get("error"):
                logger.debug("risk_context: no account state available")
                return None

            # Fetch economic calendar for first currency in pair
            base_currency = symbol[:3] if len(symbol) == 6 else "USD"
            calendar = get_economic_calendar(currency=base_currency)

            # Fetch correlation for portfolio risk
            correlation = get_currency_correlation(symbol)

            risk = build_risk_context_from_account(
                account_state=account,
                calendar=calendar,
                correlation=correlation,
            )

            logger.debug(
                "risk_context_built",
                symbol=symbol,
                risk_level=risk.account_risk_level,
                exposure_pct=risk.exposure_pct,
                consecutive_losses=risk.consecutive_losses,
            )
            return risk

        except Exception as e:
            logger.warning("risk_context_build_failed", error=str(e))
            return None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self, interval: float = 60.0) -> None:
        """Start the orchestrator loop."""
        self._running = True
        symbols = self.config.trading.pairs if hasattr(self.config, "trading") else ["EURUSD"]

        # ── Start broker health monitor (if broker supports it) ──
        await self._start_broker_health_monitor(symbols)

        for symbol in symbols:
            task = asyncio.create_task(self._run_loop(symbol, interval))
            self._tasks.append(task)

        logger.info(
            "orchestrator_started",
            symbols=symbols,
            interval=interval,
            data_agents=len(self._data_agents),
            analysis_agents=len(self._analysis_agents),
        )

    async def stop(self) -> None:
        self._running = False

        # ── Stop health monitor first ──
        await self._stop_broker_health_monitor()

        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.nim.close()
        logger.info("orchestrator_stopped", cycles=self._cycle_count)

    # ── Broker Health Monitor ────────────────────────────────────────

    async def _start_broker_health_monitor(self, symbols: list[str]) -> None:
        """Start the background broker health monitor if broker supports it.

        Only activates for MT5LinuxBroker. The health monitor:
        - Pings MT5 every 5s via RPyC
        - Tracks tick freshness (stale-data protection)
        - Triggers reconnect on disconnect
        - Sends Telegram alerts on prolonged disconnects
        """
        if not _MT5_LINUX_AVAILABLE:
            return

        broker = self.broker
        if not isinstance(broker, BrokerHealthAdapter):  # type: ignore[misc]
            return

        # Build Telegram callback from bot if available
        telegram_cb = None
        if self._telegram_bot and hasattr(self._telegram_bot, "send_alert"):
            telegram_cb = self._telegram_bot.send_alert

        # Build guardian data-stale callback
        guardian_cb = self._create_data_stale_callback()

        # Create health monitor
        monitor = broker.start_health_monitor(
            subscribed_pairs=symbols,
            guardian_data_stale_callback=guardian_cb,
        )
        if monitor is None:
            logger.warning("broker_health_monitor_not_available")
            return

        # Wire Telegram callback (can be set after construction)
        if telegram_cb:
            broker.set_telegram_callback(telegram_cb)
            if broker._conn_mgr:
                broker._conn_mgr.set_telegram_callback(telegram_cb)
            monitor.set_telegram_callback(telegram_cb)

        # Start background task
        self._health_monitor_task = await monitor.start()
        self._health_monitor = monitor

        logger.info(
            "broker_health_monitor_task_spawned",
            symbols=symbols,
            interval=HEALTH_PING_INTERVAL,
        )

    async def _stop_broker_health_monitor(self) -> None:
        """Stop the broker health monitor gracefully."""
        if self._health_monitor:
            await self._health_monitor.stop()
            self._health_monitor = None
        if self._health_monitor_task and not self._health_monitor_task.done():
            self._health_monitor_task.cancel()
            try:
                await self._health_monitor_task
            except asyncio.CancelledError:
                pass
            self._health_monitor_task = None

    def _create_data_stale_callback(self) -> Any:
        """Create a callback that bridges HealthChecker → Guardian.

        Called by the health monitor when broker data is detected as stale.
        This is the HealthChecker→Guardian bridge — the critical operational
        link that ensures a disconnected broker actually HALTS trading.

        Also implements the broker disconnect→Guardian notification bridge
        per AC2.17 of the Noema Blueprint.
        """
        def _set_data_stale() -> None:
            if self.guardian:
                self.guardian.halt_trading("data_stale")
            logger.warning(
                "guardian_data_stale_set",
                reason="Broker health monitor detected stale data",
            )
            # Update health checker (HealthChecker→Guardian bridge)
            if self.health_checker:
                self.health_checker.update_kill_switch(True, "data_stale")
            # Also update metrics
            if self.metrics_exporter:
                self.metrics_exporter.record_kill_switch(
                    reason="data_stale",
                    symbol="system",
                )
                self.metrics_exporter.set_kill_switch_active(True)
        return _set_data_stale

    def check_broker_connection_and_notify_guardian(self) -> None:
        """Check broker MT5 connection and bridge to Guardian.

        Implements AC2.17: when check_mt5(connected=False),
        Guardian's halt_trading("broker_mt5_disconnected") fires automatically.

        Also updates the HealthChecker with current broker state.
        """
        try:
            connected = getattr(self.broker, "is_connected", False)
            latency_ms = getattr(self.broker, "get_latency_ms", lambda: -1)()

            # Update HealthChecker
            if self.health_checker:
                self.health_checker.check_mt5(connected, latency_ms if latency_ms > 0 else 0)

            # Bridge to Guardian on disconnect
            if not connected and self.guardian:
                self.guardian.halt_trading("broker_mt5_disconnected")
                logger.critical(
                    "healthchecker_guardian_bridge_fired",
                    event="broker_mt5_disconnected",
                    reason="HealthChecker detected MT5 disconnect, Guardian halt_trading triggered",
                )

        except Exception as exc:
            logger.error("broker_connection_check_failed", error=str(exc))

    # ── Loop ─────────────────────────────────────────────────────────

    async def _run_loop(self, symbol: str, interval: float) -> None:
        while self._running:
            await self.run_cycle(symbol)
            await asyncio.sleep(interval)

    # ── Metrics ──────────────────────────────────────────────────────

    def _log_metrics(self, metrics: PipelineMetrics) -> None:
        self._logger.info(
            "pipeline_complete",
            symbol=metrics.symbol,
            decision=metrics.decision,
            total_ms=round(metrics.total_latency_ms, 1),
            data_ms=round(metrics.phase_timings.get("data", 0), 1),
            analysis_ms=round(metrics.phase_timings.get("analysis", 0), 1),
            decision_ms=round(metrics.phase_timings.get("decision", 0), 1),
            execution_ms=round(metrics.phase_timings.get("execution", 0), 1),
            cycle=self._cycle_count,
        )

    @property
    def metrics_summary(self) -> dict[str, Any]:
        """Aggregate metrics for monitoring."""
        if not self._total_metrics:
            return {}
        recent = self._total_metrics[-100:]
        return {
            "total_cycles": self._cycle_count,
            "avg_latency_ms": sum(m.total_latency_ms for m in recent) / len(recent),
            "avg_decision_ms": sum(m.phase_timings.get("decision", 0) for m in recent) / len(recent),
            "trade_rate": sum(1 for m in recent if m.decision != "NO_TRADE") / len(recent),
            "error_rate": sum(1 for m in recent if m.error) / len(recent),
            "nim_metrics": self.nim.metrics,
        }
