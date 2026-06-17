"""VMPM Main — Modern Agentic Trading System.

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
from typing import Any

import structlog

from vmpm.core.settings import Settings, load_settings
from vmpm.core.nim_client import NIMClient, ModelTier
from vmpm.core.orchestrator_modern import ModernOrchestrator
from vmpm.core.metrics import MetricsCollector
from vmpm.core.storage import TradeStore, RedisCache

# ── Agent Imports ────────────────────────────────────────────────────
# Layer 1: Data agents (deterministic)
from vmpm.agents.macro import MacroEconomicAgent
from vmpm.agents.currency import CurrencyStrengthAgent
from vmpm.agents.session import SessionIntelligenceAgent

# Layer 2: Analysis agents (deterministic)
from vmpm.agents.structure import MarketStructureAgent
from vmpm.agents.institutional import InstitutionalFootprintAgent
from vmpm.agents.sr import SupportResistanceAgent
from vmpm.agents.momentum import MomentumAgent
from vmpm.agents.price_action import PriceActionAgent

# Layer 3: Decision agents (LLM-powered)
from vmpm.agents.thesis import TradeThesisAgent
from vmpm.agents.devil import DevilsAdvocateAgent
from vmpm.agents.cio import CIOAgent

# Layer 4: Execution agents (deterministic)
from vmpm.agents.risk import RiskManagerAgent
from vmpm.agents.execution import ExecutionAgent

# Layer 5: Learning agents (LLM-powered)
from vmpm.agents.learning import LearningAgent

# Broker
from vmpm.broker.paper import PaperBroker
from vmpm.broker.mt5 import MT5Broker

logger = structlog.get_logger(__name__)


async def create_orchestrator(settings: Settings) -> ModernOrchestrator:
    """Build and configure the modern orchestrator."""

    # ── NIM Client ───────────────────────────────────────────────────
    api_key = settings.nim.api_key or os.getenv("NIM_API_KEY", "")
    if not api_key:
        logger.warning("NIM_API_KEY not set — LLM agents will use fallback logic")

    tier_map = {"fast": ModelTier.FAST, "standard": ModelTier.STANDARD, "heavy": ModelTier.HEAVY}
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

    return orch


async def main() -> None:
    """VMPM entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Valentine Money Printing Machine")
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

    logger.info("vmpm_starting", version="2.0.0", pairs=settings.trading.pairs)

    # Create orchestrator
    orch = await create_orchestrator(settings)

    # Handle shutdown signals
    shutdown_event = asyncio.Event()

    def _signal_handler(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Start orchestrator
    await orch.start(interval=args.interval)

    # Wait for shutdown
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("vmpm_shutting_down")
    await orch.stop()
    logger.info("vmpm_stopped")


if __name__ == "__main__":
    asyncio.run(main())
