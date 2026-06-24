"""Symbol Orchestrator — Per-symbol independent trading pipeline.

Phase 3 component. Each traded symbol gets its own SymbolOrchestrator with:
- Independent agent teams (analysis, critic, execution)
- Symbol-specific Guardian state
- Symbol-level P&L tracking
- Multi-timeframe awareness via TimeframeManager
- Correlation awareness via CorrelationMatrix (cross-symbol risk)

The SymbolOrchestrator is the unit of trading parallelism: one per symbol,
all running concurrently, coordinated by the Fleet Manager (conductor.py).

Key design:
- Each symbol runs its OWN pipeline independently
- Guardian is per-symbol (a single bad symbol doesn't halt everything)
- P&L tracked per symbol for attribution analysis
- Correlation checks prevent cross-symbol conflicts

PURE MATH where possible. LLM only in decision phase.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from noema.core.modern_agent import AgentReport
from noema.core.timeframe_manager import (
    TimeframeManager,
    MultiTimeframeResult,
    TrendDirection,
    VolatilityRegime,
    TimeframeAlignment,
)
from noema.data.correlation import CorrelationMatrix
from noema.agents.guardian import GuardianAgent, GuardianState

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════

class SymbolState(str, Enum):
    """Lifecycle state of a symbol orchestrator."""
    INIT = "init"
    WARMING = "warming"        # Loading initial data
    ACTIVE = "active"           # Trading normally
    PAUSED = "paused"           # Temporarily paused (correlation, volatility)
    HALTED = "halted"           # Stopped by Guardian
    ERROR = "error"             # Fatal error — needs intervention


@dataclass
class SymbolPnL:
    """Per-symbol profit and loss tracking."""
    symbol: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0    # In account currency
    total_loss: float = 0.0
    max_drawdown: float = 0.0    # Peak-to-trough (%)
    current_drawdown: float = 0.0
    peak_equity: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    last_trade_at: float = 0.0
    trade_history: list[dict[str, Any]] = field(default_factory=list)

    def record_trade(self, pnl: float, entry_price: float, exit_price: float) -> None:
        """Record a completed trade."""
        self.total_trades += 1
        won = pnl > 0
        if won:
            self.winning_trades += 1
            self.total_profit += pnl
        else:
            self.losing_trades += 1
            self.total_loss += abs(pnl)

        self.last_trade_at = time.monotonic()

        # Update averages
        if self.winning_trades > 0:
            self.average_win = self.total_profit / self.winning_trades
        if self.losing_trades > 0:
            self.average_loss = self.total_loss / self.losing_trades

        # Win rate
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades

        # Profit factor
        if self.total_loss > 0:
            self.profit_factor = self.total_profit / self.total_loss
        elif self.total_profit > 0:
            self.profit_factor = 999.0  # No losses → infinite

        # Store in history
        self.trade_history.append({
            "pnl": pnl,
            "entry": entry_price,
            "exit": exit_price,
            "won": won,
            "timestamp": time.monotonic(),
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
        })

        # Keep last 100 trades
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]

    def update_drawdown(self, current_equity_contribution: float) -> None:
        """Update drawdown metrics with current equity contribution.

        Args:
            current_equity_contribution: This symbol's current equity value
                (or proportion of total equity from broker).
        """
        if current_equity_contribution > self.peak_equity:
            self.peak_equity = current_equity_contribution

        if self.peak_equity > 0:
            self.current_drawdown = (
                (self.peak_equity - current_equity_contribution) / self.peak_equity
            ) * 100
            self.max_drawdown = max(self.max_drawdown, self.current_drawdown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "total_trades": self.total_trades,
            "winning": self.winning_trades,
            "losing": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 2),
            "total_profit": round(self.total_profit, 2),
            "total_loss": round(self.total_loss, 2),
            "net_pnl": round(self.total_profit - self.total_loss, 2),
            "average_win": round(self.average_win, 2),
            "average_loss": round(self.average_loss, 2),
            "max_drawdown_pct": round(self.max_drawdown, 2),
            "current_drawdown_pct": round(self.current_drawdown, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
        }


@dataclass
class SymbolHealth:
    """Health status for a single symbol's orchestration."""
    symbol: str
    state: SymbolState = SymbolState.INIT
    is_operational: bool = False
    agent_health: dict[str, str] = field(default_factory=dict)  # agent_name → status
    guardian_ok: bool = True
    last_cycle_at: float = 0.0
    cycles_completed: int = 0
    cycles_failed: int = 0
    last_decision: str = "NONE"
    last_error: str = ""
    avg_cycle_latency_ms: float = 0.0
    timeframe_alignment: TimeframeAlignment = TimeframeAlignment.UNKNOWN
    timeframe_alignment_score: float = 0.0


# ═══════════════════════════════════════════════════
# Symbol Orchestrator
# ═══════════════════════════════════════════════════

class SymbolOrchestrator:
    """Per-symbol independent trading orchestrator.

    Each instance manages all trading logic for ONE symbol, including:
    - Multi-timeframe analysis (trend + timing)
    - Agent pipeline execution (analysis → decision → execution)
    - Symbol-specific risk via its own GuardianState
    - P&L tracking and attribution
    - Correlation awareness (fed by FleetManager)

    Usage:
        orch = SymbolOrchestrator(
            symbol="EURUSD",
            broker=broker,
            config=config,
            modern_orch=modern,  # Shared ModernOrchestrator for agent execution
        )
        await orch.warm_up()
        await orch.run_cycle()
    """

    def __init__(
        self,
        symbol: str,
        broker: Any,
        config: Any,
        modern_orchestrator: Any = None,  # ModernOrchestrator for agent pipeline
        guardian: GuardianAgent | None = None,
        guardian_state: GuardianState | None = None,
        correlation_matrix: CorrelationMatrix | None = None,
        metrics_exporter: Any = None,
    ):
        self.symbol = symbol
        self.broker = broker
        self.config = config
        self._modern_orch = modern_orchestrator

        # ── Guardian (per-symbol state) ──
        self.guardian = guardian
        self.guardian_state = guardian_state or GuardianState()

        # ── Timeframe Manager ──
        self.timeframe_mgr = TimeframeManager(config=config)

        # ── Correlation (shared — set by FleetManager) ──
        self._correlation = correlation_matrix

        # ── P&L ──
        self.pnl = SymbolPnL(symbol=symbol)

        # ── Health ──
        self.health = SymbolHealth(symbol=symbol)

        # ── State ──
        self.state = SymbolState.INIT
        self._running = False
        self._last_tf_result: MultiTimeframeResult | None = None

        # ── Observability ──
        self._metrics_exporter = metrics_exporter

        self._logger = logger.bind(symbol=symbol, component="symbol_orchestrator")

    # ── Lifecycle ──────────────────────────────────────────────────

    async def warm_up(self) -> bool:
        """Load initial data and validate the symbol can trade.

        Returns True if warm-up succeeded and symbol can trade.
        """
        self.state = SymbolState.WARMING
        self._logger.info("symbol_warming_up")

        try:
            # Fetch multi-timeframe data
            bars_ok = await self._fetch_bars_for_all_timeframes()
            if not bars_ok:
                self._logger.warning("warm_up_no_data")
                self._set_error("No bar data available — cannot trade")
                return False

            # Check symbol is tradeable (spread, min lot, etc.)
            tradeable = await self._check_tradeable()
            if not tradeable:
                self._logger.warning("warm_up_not_tradeable")
                self._set_error("Symbol not tradeable")
                return False

            self.state = SymbolState.ACTIVE
            self.health.state = self.state
            self.health.is_operational = True
            self._logger.info("symbol_warmed_up")
            return True

        except Exception as e:
            self._logger.error("warm_up_failed", error=str(e))
            self.state = SymbolState.ERROR
            self.health.last_error = str(e)
            return False

    async def run_cycle(self) -> dict[str, Any]:
        """Execute one complete trading cycle for this symbol.

        Steps:
        1. Multi-timeframe analysis (D1 → H4 → H1 → M15)
        2. Correlation check (cross-symbol risk)
        3. Guardian health check
        4. Agent pipeline (via ModernOrchestrator)
        5. Post-trade PnL update

        Returns:
            Dictionary with cycle results.
        """
        if self.state != SymbolState.ACTIVE:
            self._logger.info("cycle_skipped", state=self.state.value)
            return {"symbol": self.symbol, "skipped": True, "reason": self.state.value}

        cycle_start = time.monotonic()
        result: dict[str, Any] = {"symbol": self.symbol}

        try:
            # ── Step 1: Multi-Timeframe Analysis ──
            self._last_tf_result = await self.timeframe_mgr.analyze_from_broker(
                self.symbol, self.broker
            )
            result["timeframe"] = self._last_tf_result.to_dict()

            # Check timeframe alignment
            if self._last_tf_result.htF_conflict:
                self._logger.info(
                    "htf_ltf_conflict",
                    htf=self._last_tf_result.htf_trend.value,
                    ltf=self._last_tf_result.ltf_trend.value,
                )
                result["skipped"] = True
                result["reason"] = "htf_ltf_conflict"
                self.health.last_decision = "CONFLICT"
                return result

            if not self._last_tf_result.can_trade:
                result["skipped"] = True
                result["reason"] = " ".join(self._last_tf_result.warnings)
                self.health.last_decision = "BLOCKED"
                return result

            # ── Step 2: Correlation Check ──
            if self._correlation and self._correlation.is_ready:
                analysis = self._correlation.analyze()
                result["correlation"] = {
                    "usd_exposure": analysis.usd_exposure,
                    "recommendations": analysis.basket_recommendations[:3],
                }

                # Check USD exposure
                if analysis.usd_exposure > CorrelationMatrix.USD_EXPOSURE_CRITICAL:
                    self._logger.warning(
                        "usd_exposure_critical",
                        exposure=analysis.usd_exposure,
                    )
                    # Don't halt — just log. FleetManager handles cross-symbol decisions.

            # ── Step 3: Guardian Health Check ──
            if self.guardian:
                triggered = await self.guardian.check_all()
                if triggered:
                    self.state = SymbolState.HALTED
                    self._logger.error(
                        "guardian_killswitch",
                        switches=[t["id"] for t in triggered],
                    )
                    result["skipped"] = True
                    result["reason"] = f"Kill-switch(es): {[t['id'] for t in triggered]}"
                    result["kill_switches"] = triggered
                    return result

            # ── Step 4: Agent Pipeline ──
            if self._modern_orch:
                from noema.core.orchestrator_modern import PipelineMetrics

                pipeline_metrics: PipelineMetrics = await self._modern_orch.run_cycle(self.symbol)
                result["decision"] = pipeline_metrics.decision
                result["confidence"] = pipeline_metrics.decision_confidence
                result["pipeline_latency_ms"] = pipeline_metrics.total_latency_ms
                self.health.last_decision = pipeline_metrics.decision
            else:
                result["decision"] = "NO_TRADE"
                result["reason"] = "no modern orchestrator configured"

            # ── Step 5: Update Health ──
            self.health.last_cycle_at = time.monotonic()
            self.health.cycles_completed += 1
            cycle_latency = (time.monotonic() - cycle_start) * 1000
            # Exponential moving average of cycle latency
            alpha = 0.1
            self.health.avg_cycle_latency_ms = (
                alpha * cycle_latency + (1 - alpha) * self.health.avg_cycle_latency_ms
            )
            self.health.timeframe_alignment = (
                self._last_tf_result.alignment if self._last_tf_result
                else TimeframeAlignment.UNKNOWN
            )
            self.health.timeframe_alignment_score = (
                self._last_tf_result.alignment_score if self._last_tf_result
                else 0.0
            )

            # ── Export metrics ──
            if self._metrics_exporter:
                try:
                    self._metrics_exporter.record_pipeline_cycle(
                        symbol=self.symbol,
                        latency_seconds=cycle_latency / 1000,
                    )
                except Exception:
                    pass

            return result

        except Exception as e:
            self._logger.error("cycle_error", error=str(e))
            self.health.cycles_failed += 1
            self.health.last_error = str(e)
            return {"symbol": self.symbol, "error": str(e), "skipped": True}

    # ── PnL Management ────────────────────────────────────────────

    def record_trade_result(
        self,
        pnl: float,
        entry_price: float,
        exit_price: float,
    ) -> None:
        """Record a trade result for this symbol's P&L tracking.

        Also notifies the Guardian to update kill-switch state.
        """
        self.pnl.record_trade(pnl, entry_price, exit_price)

        # Notify Guardian
        if self.guardian:
            won = pnl > 0
            self.guardian.record_trade_result(won=won, pnl=pnl)

        self._logger.info(
            "trade_recorded",
            pnl=round(pnl, 2),
            win_rate=f"{self.pnl.win_rate:.2%}",
            total_trades=self.pnl.total_trades,
        )

    def update_pnl_from_broker(self, account_info: dict[str, Any]) -> None:
        """Update P&L from broker account info (for live trading).

        Args:
            account_info: Broker account info dict (balance, equity, etc.).
        """
        equity = float(account_info.get("equity", 0))
        if equity > 0:
            self.pnl.update_drawdown(equity)

    # ── Correlation Integration ────────────────────────────────────

    def set_correlation_matrix(self, corr: CorrelationMatrix) -> None:
        """Set the shared correlation matrix (called by FleetManager)."""
        self._correlation = corr

    def get_correlation_warning(
        self, direction: str, open_positions: dict[str, str]
    ) -> tuple[bool, str]:
        """Check if this symbol + direction creates correlation risk.

        Args:
            direction: "BUY" or "SELL" for this symbol.
            open_positions: Dict of {pair: direction} for all open trades.

        Returns:
            (has_warning, message)
        """
        if not self._correlation or not self._correlation.is_ready:
            return False, "No correlation data"

        # Check for anti-correlated opposing bets
        for other_pair, other_dir in open_positions.items():
            if other_pair == self.symbol:
                continue

            is_risky, reason = self._correlation.are_opposing_bets_risky(
                (self.symbol, direction),
                (other_pair, other_dir),
            )
            if is_risky:
                return True, reason

        return False, "Pass"

    # ── Multi-Timeframe Access ─────────────────────────────────────

    @property
    def htf_trend(self) -> TrendDirection:
        """Get the higher timeframes trend direction."""
        if self._last_tf_result:
            return self._last_tf_result.htf_trend
        return TrendDirection.UNKNOWN

    @property
    def ltf_trend(self) -> TrendDirection:
        """Get the lower timeframes trend direction."""
        if self._last_tf_result:
            return self._last_tf_result.ltf_trend
        return TrendDirection.UNKNOWN

    @property
    def is_trend_aligned(self) -> bool:
        """True if all timeframes agree on direction."""
        if self._last_tf_result:
            return self._last_tf_result.alignment == TimeframeAlignment.ALIGNED
        return False

    def get_suggested_sl_tp(self) -> tuple[float, float]:
        """Get suggested SL/TP pips from multi-timeframe analysis."""
        if self._last_tf_result:
            return self._last_tf_result.stop_loss_pips, self._last_tf_result.take_profit_pips
        return 0.0, 0.0

    # ── State Management ───────────────────────────────────────────

    def pause(self, reason: str) -> None:
        """Temporarily pause trading for this symbol.

        Used for correlation conflicts, high volatility, news events.
        """
        if self.state == SymbolState.ACTIVE:
            self.state = SymbolState.PAUSED
            self.health.state = self.state
            self._logger.info("symbol_paused", reason=reason)

    def resume(self) -> None:
        """Resume trading after a pause."""
        if self.state == SymbolState.PAUSED:
            self.state = SymbolState.ACTIVE
            self.health.state = self.state
            self._logger.info("symbol_resumed")

    def halt(self, reason: str) -> None:
        """Permanently halt trading for this symbol (until manual review)."""
        self.state = SymbolState.HALTED
        self.health.state = self.state
        self.health.is_operational = False
        self._logger.error("symbol_halted", reason=reason)

    def _set_error(self, message: str) -> None:
        """Set error state."""
        self.state = SymbolState.ERROR
        self.health.last_error = message
        self.health.is_operational = False

    # ── Internal Helpers ───────────────────────────────────────────

    async def _fetch_bars_for_all_timeframes(self) -> bool:
        """Fetch bar data for all timeframes. Returns True if data is available."""
        import asyncio

        tfs = ["D1", "H4", "H1", "M15"]
        results = await asyncio.gather(
            *[self._fetch_bars(tf, 200) for tf in tfs],
            return_exceptions=True,
        )

        any_data = False
        for tf, result in zip(tfs, results):
            if isinstance(result, Exception):
                self._logger.warning("bar_fetch_failed", timeframe=tf, error=str(result))
            elif result and len(result) > 0:
                any_data = True

        return any_data

    async def _fetch_bars(self, timeframe: str, count: int) -> list[dict]:
        """Fetch bars — mirrors TimeframeManager pattern."""
        if hasattr(self.broker, 'bars') and callable(self.broker.bars):
            try:
                result = await self.broker.bars(self.symbol, timeframe, count)
                if result:
                    return list(result)
            except Exception:
                pass

        if hasattr(self.broker, 'get_candles') and callable(self.broker.get_candles):
            try:
                result = await asyncio.to_thread(
                    self.broker.get_candles, self.symbol, timeframe, count
                )
                if result:
                    return list(result)
            except Exception:
                pass

        if hasattr(self.broker, 'get_rates') and callable(self.broker.get_rates):
            try:
                result = await asyncio.to_thread(
                    self.broker.get_rates, self.symbol, timeframe, count
                )
                if result is not None:
                    if hasattr(result, 'to_dict'):
                        return result.to_dict('records')
                    if isinstance(result, list):
                        return result
            except Exception:
                pass

        return []

    async def _check_tradeable(self) -> bool:
        """Check if symbol is tradeable (spread, min lot, contract size)."""
        # Default: assume tradeable if we have a broker
        if self.broker is None:
            return False

        try:
            # Try to get symbol info
            if hasattr(self.broker, 'get_symbol_info'):
                info = self.broker.get_symbol_info(self.symbol)
                if info:
                    return True
            # If broker has no symbol info method, trust it
            return True
        except Exception:
            # Be permissive — assume tradeable
            return True

    def get_status(self) -> dict[str, Any]:
        """Get comprehensive status for this symbol."""
        return {
            "symbol": self.symbol,
            "state": self.state.value,
            "is_operational": self.health.is_operational,
            "cycles_completed": self.health.cycles_completed,
            "cycles_failed": self.health.cycles_failed,
            "last_decision": self.health.last_decision,
            "last_error": self.health.last_error,
            "avg_cycle_latency_ms": round(self.health.avg_cycle_latency_ms, 1),
            "htf_trend": self.htf_trend.value,
            "ltf_trend": self.ltf_trend.value,
            "trend_aligned": self.is_trend_aligned,
            "pnl": self.pnl.to_dict(),
        }
