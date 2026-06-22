"""Noema Main — Modern Agentic Trading System.

Uses the wave-based parallel orchestrator:
- Layer 1: Data agents (parallel, deterministic)
- Layer 2: Analysis agents (parallel, deterministic + LLM)
- Layer 3: Decision agents (sequential LLM debate)
- Layer 4: Execution (deterministic)
- Layer 5: Learning (background LLM reflection)
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Any

import structlog

from noema.core.settings import Settings, load_settings
from noema.core.nim_client import NIMClient, ModelTier
from noema.core.orchestrator_modern import ModernOrchestrator
from noema.core.metrics import MetricsCollector
from noema.core.storage import TradeStore, RedisCache

# ── Agent Imports ────────────────────────────────────────────────────
# Layer 1: Data agents (deterministic)
from noema.agents.macro import MacroEconomicAgent
from noema.agents.currency import CurrencyStrengthAgent
from noema.agents.session import SessionIntelligenceAgent

# Layer 2: Analysis agents (deterministic)
from noema.agents.structure import MarketStructureAgent
from noema.agents.institutional import InstitutionalFootprintAgent
from noema.agents.sr import SupportResistanceAgent
from noema.agents.momentum import MomentumAgent
from noema.agents.price_action import PriceActionAgent

# Layer 3: Decision agents (LLM-powered)
from noema.agents.thesis import TradeThesisAgent
from noema.agents.devil import DevilsAdvocateAgent
from noema.agents.cio import CIOAgent

# Layer 4: Execution agents (deterministic)
from noema.agents.risk import RiskManagerAgent
from noema.agents.execution import ExecutionAgent

# Layer 5: Learning agents (LLM-powered)
from noema.agents.learning import LearningAgent

# Self-learning + journaling + Telegram
from noema.agents.reflector import ReflectorAgent
from noema.database.journal import TradeJournal
from noema.agents.telegram_bot import TelegramBot

# Broker
from noema.broker.paper import PaperBroker
from noema.broker.mt5 import MT5Broker

logger = structlog.get_logger(__name__)


# ── Companion Services ───────────────────────────────────────────────


class CompanionServices:
    """ReflectorAgent + TradeJournal + Telegram — companion services
    that sit alongside the ModernOrchestrator and provide self-learning,
    trade journaling, and Telegram control surface."""

    def __init__(self) -> None:
        self.reflector = ReflectorAgent()
        self.journal = TradeJournal()
        self.telegram = TelegramBot()

    def record_trade(
        self,
        pair: str,
        decision: str,
        context: dict[str, Any],
        agent_reports: dict[str, dict],
    ) -> None:
        """Record an executed trade for self-learning and journaling."""
        try:
            trade_record = {
                "symbol": pair,
                "direction": "buy" if decision == "BUY" else "sell",
                "pnl": 0.0,
                "session": context.get("session", "unknown"),
                "market_regime": "unknown",
                "trend": context.get("trend", "unknown"),
                "confidence": agent_reports.get("thesis", {}).get("confidence", 0),
                "confluence_score": sum(
                    r.get("confidence", 0) for r in agent_reports.values()
                ) / max(len(agent_reports), 1),
                "exit_reason": "open",
                "agent_reports": agent_reports,
            }
            self.reflector.record_trade(trade_record)

            self.journal.record_trade(
                ticket=0,
                symbol=pair,
                direction="buy" if decision == "BUY" else "sell",
                entry_price=context.get("current_price", 0),
                exit_price=0,
                volume=context.get("lot_size", 0.01),
                sl=context.get("stop_loss", 0),
                tp=context.get("take_profit", 0),
                pnl=0,
                pnl_pips=0,
                entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc),
                exit_reason="open",
                session="unknown",
                settings_hash=self.journal.compute_config_hash({}),
                git_sha="",
                agent_reports=agent_reports,
            )
        except Exception as exc:
            logger.error("trade_recording_failed", error=str(exc))

    def get_learned_params(self) -> dict[str, Any]:
        """Get ReflectorAgent's adapted parameters."""
        return self.reflector.get_adapted_params()

    async def start(self) -> None:
        """Start Telegram bot."""
        adapted = self.reflector.get_adapted_params()
        if adapted.get("lessons"):
            logger.info(f"Loaded {len(adapted['lessons'])} lessons from ReflectorAgent")
        await self.telegram.start()

    async def stop(self) -> None:
        """Stop Telegram bot and close journal."""
        await self.telegram.stop()
        self.journal.close()


# ── Telegram Command Handlers (wired to CompanionServices) ──────────


def _build_telegram_handlers(services: CompanionServices, broker: Any) -> dict[str, Any]:
    """Build Telegram command handlers bound to companion services."""

    async def handle_status() -> str:
        account = broker.get_account_info() if hasattr(broker, "get_account_info") else {}
        positions = broker.get_open_positions() if hasattr(broker, "get_open_positions") else []
        adapted = services.reflector.get_adapted_params()
        lessons = adapted.get("lessons", [])
        return (
            "📊 Noema STATUS\n"
            f"  Balance: ${account.get('balance', 0):,.2f}\n"
            f"  Equity: ${account.get('equity', 0):,.2f}\n"
            f"  Open Positions: {len(positions)}\n"
            f"  Risk Multiplier: {adapted.get('risk_multiplier', 1.0):.2f}\n"
            f"  Min Confidence: {adapted.get('min_confidence', 0.5):.0%}\n"
            f"  Lessons Loaded: {len(lessons)}"
        )

    async def handle_positions() -> str:
        positions = broker.get_open_positions() if hasattr(broker, "get_open_positions") else []
        if not positions:
            return "No open positions"
        lines = ["📋 OPEN POSITIONS"]
        for p in positions:
            lines.append(
                f"  {p.type.upper()} {p.volume} {p.symbol} @ {p.open_price:.5f}"
                f" | P&L: ${p.pnl:.2f}"
            )
        return "\n".join(lines)

    async def handle_flatten() -> str:
        positions = broker.get_open_positions() if hasattr(broker, "get_open_positions") else []
        if not positions:
            return "No positions to flatten"
        count = 0
        for p in positions:
            if hasattr(broker, "close_position") and broker.close_position(p.ticket):
                count += 1
        await services.telegram.send_alert(
            f"🚨 FLATTENED {count}/{len(positions)} positions."
        )
        return f"Flattened {count} positions."

    async def handle_halt() -> str:
        await services.telegram.send_alert("⏸️ Noema TRADING HALTED")
        return "Trading halted."

    async def handle_resume() -> str:
        await services.telegram.send_alert("▶️ Noema TRADING RESUMED")
        return "Trading resumed."

    async def handle_balance() -> str:
        account = broker.get_account_info() if hasattr(broker, "get_account_info") else {}
        return (
            f"💰 Balance: ${account.get('balance', 0):,.2f}\n"
            f"   Equity: ${account.get('equity', 0):,.2f}\n"
            f"   Free Margin: ${account.get('free_margin', 0):,.2f}"
        )

    async def handle_lessons() -> str:
        manual = services.reflector.get_operating_manual()
        return manual[:3000]

    async def handle_learn() -> str:
        insights = services.reflector.learn()
        n_lessons = len(insights.get("lessons", []))
        bayesian = insights.get("bayesian_edge", {})
        wr = bayesian.get("posterior_mean", 0)
        return (
            f"🧠 Learning cycle complete\n"
            f"  Active lessons: {n_lessons}\n"
            f"  Bayesian win rate: {wr:.1%}\n"
            f"  Trades analyzed: {bayesian.get('total_trades', 0)}"
        )

    return {
        "status": handle_status,
        "positions": handle_positions,
        "flatten": handle_flatten,
        "halt": handle_halt,
        "resume": handle_resume,
        "balance": handle_balance,
        "lessons": handle_lessons,
        "learn": handle_learn,
    }


# ── Orchestrator Factory ────────────────────────────────────────────


async def create_orchestrator(
    settings: Settings,
) -> tuple[ModernOrchestrator, CompanionServices]:
    """Build and configure the modern orchestrator with companion services.

    Returns (orchestrator, services) — the orchestrator runs the wave-based
    pipeline, while services provides self-learning, journaling, and Telegram.
    """

    # ── NIM Client ───────────────────────────────────────────────────
    api_key = settings.nim.api_key or os.getenv("NIM_API_KEY", "")
    if not api_key:
        logger.warning("NIM_API_KEY not set — LLM agents will use fallback logic")

    tier_map = {
        "fast": ModelTier.FAST,
        "standard": ModelTier.STANDARD,
        "heavy": ModelTier.HEAVY,
    }
    nim = NIMClient(
        api_key=api_key,
        base_url=settings.nim.base_url,
        default_tier=tier_map.get(settings.nim.default_tier, ModelTier.STANDARD),
        cache_ttl=settings.nim.cache_ttl,
        cache_enabled=settings.nim.cache_enabled,
        max_retries=settings.nim.max_retries,
        rpm_limit=settings.nim.rpm_limit,
    )

    # ── Broker ───────────────────────────────────────────────────────
    if settings.broker.type == "mt5":
        broker = MT5Broker(settings)
    else:
        broker = PaperBroker(settings)

    # ── Storage ──────────────────────────────────────────────────────
    trade_store = None
    redis_cache = None

    if settings.database_url.startswith("postgresql"):
        trade_store = TradeStore(settings.database_url)
        await trade_store.initialize()

    redis_url = settings.redis_url or os.getenv("REDIS_URL", "")
    if redis_url:
        redis_cache = RedisCache(redis_url)
        await redis_cache.initialize()

    # ── Metrics ──────────────────────────────────────────────────────
    metrics = MetricsCollector(enabled=True)
    metrics.set_system_info(
        version="2.0.0",
        pairs=settings.trading.pairs,
    )

    # ── Companion Services ───────────────────────────────────────────
    services = CompanionServices()

    # ── Orchestrator ─────────────────────────────────────────────────
    orch = ModernOrchestrator(nim_client=nim, broker=broker, config=settings)

    # Layer 1: Data agents (deterministic, parallel)
    orch.register_data_agents([
        MacroEconomicAgent(config=settings),
        CurrencyStrengthAgent(config=settings),
        SessionIntelligenceAgent(config=settings),
    ])

    # Layer 2: Analysis agents (deterministic, parallel)
    orch.register_analysis_agents([
        MarketStructureAgent(config=settings),
        InstitutionalFootprintAgent(config=settings),
        SupportResistanceAgent(config=settings),
        MomentumAgent(config=settings),
        PriceActionAgent(config=settings),
    ])

    # Layer 3: Decision agents (LLM, sequential debate)
    orch.register_decision_agents(
        thesis=TradeThesisAgent(config=settings, nim_client=nim),
        devil=DevilsAdvocateAgent(config=settings, nim_client=nim),
        cio=CIOAgent(config=settings, nim_client=nim),
    )

    # Layer 4: Execution agents (deterministic, sequential)
    orch.register_execution_agents(
        risk=RiskManagerAgent(config=settings),
        execution=ExecutionAgent(config=settings, broker=broker),
    )

    # Layer 5: Learning agent (LLM, background)
    orch.register_learning_agent(
        LearningAgent(config=settings, nim_client=nim)
    )

    # Wire Telegram handlers
    handlers = _build_telegram_handlers(services, broker)
    services.telegram.register_handlers(handlers)

    return orch, services


# ── CLI Entry Point ──────────────────────────────────────────────────


async def main() -> None:
    """Noema entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Noema")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--interval", type=float, default=60.0, help="Cycle interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Use paper broker")
    args = parser.parse_args()

    # Load config
    settings = load_settings()
    if args.dry_run:
        settings.broker.type = "paper"

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.stdlib._NAME_TO_LEVEL.get(settings.log_level.lower(), 20)
        ),
    )

    logger.info("noema_starting", version="2.0.0", pairs=settings.trading.pairs)

    # Create orchestrator + services
    orch, services = await create_orchestrator(settings)

    # Start companion services (Telegram, journal, reflector)
    await services.start()

    # Handle shutdown signals
    shutdown_event = asyncio.Event()

    def _signal_handler(sig, _frame):
        logger.info("shutdown_signal_received", signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Start orchestrator
    await orch.start(interval=args.interval)

    # Wait for shutdown
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("noema_shutting_down")
    await orch.stop()
    await services.stop()
    logger.info("noema_stopped")


if __name__ == "__main__":
    asyncio.run(main())
