"""VMPM Main Orchestrator — the brain that coordinates all 17 agents.

Runs the complete 12-phase trading pipeline:
1. Fundamental Analysis → 2. Trend → 3. Market Structure → 4. S/R Mapping
→ 5. Order Blocks → 6. WAIT FOR PRICE → 7. RSI → 8. Candlestick
→ 9. Validation → 10. Risk Management → 11. Execution → 12. Learning
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

import structlog

from vmpm.core.config import load_config, VMPMConfig
from vmpm.core.message_bus import MessageBus
from vmpm.core.state_machine import TradingPipeline, PipelineState

# Agents
from vmpm.agents.macro import MacroEconomicAgent
from vmpm.agents.currency import CurrencyStrengthAgent
from vmpm.agents.structure import MarketStructureAgent
from vmpm.agents.institutional import InstitutionalFootprintAgent
from vmpm.agents.sr import SupportResistanceAgent
from vmpm.agents.session import SessionIntelligenceAgent
from vmpm.agents.opportunity import OpportunitySurveillanceAgent
from vmpm.agents.momentum import MomentumAgent
from vmpm.agents.price_action import PriceActionAgent
from vmpm.agents.thesis import TradeThesisAgent
from vmpm.agents.devil import DevilsAdvocateAgent
from vmpm.agents.cio import CIOAgent
from vmpm.agents.risk import RiskManagerAgent
from vmpm.agents.execution import ExecutionAgent
from vmpm.agents.management import TradeManagementAgent
from vmpm.agents.performance import PerformanceAnalystAgent
from vmpm.agents.learning import LearningAgent

# Infrastructure
from vmpm.data.feed import MarketDataFeed
from vmpm.data.calendar import EconomicCalendar
from vmpm.broker.paper import PaperBroker
from vmpm.broker.mt5 import MT5Broker
from vmpm.models.knowledge import KnowledgeBase

logger = structlog.get_logger(__name__)


class VMPMOrchestrator:
    """The Valentine Money Printing Machine orchestrator.

    Coordinates all 17 agents through the 12-phase trading pipeline.
    """

    def __init__(self, config: VMPMConfig | None = None) -> None:
        self.config = config or load_config()
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Core infrastructure
        self.bus = MessageBus()
        self.pipeline = TradingPipeline()
        self.knowledge = KnowledgeBase()

        # Initialize broker
        if self.config.broker.type == "mt5":
            self.broker = MT5Broker(self.config)
        else:
            self.broker = PaperBroker(self.config)

        # Data
        self.data_feed = MarketDataFeed(self.broker)
        self.calendar = EconomicCalendar(self.config)

        # Initialize all 17 agents
        kwargs = {"config": self.config, "message_bus": self.bus}
        self.agents = {
            "macro": MacroEconomicAgent(**kwargs),
            "currency": CurrencyStrengthAgent(**kwargs),
            "structure": MarketStructureAgent(**kwargs),
            "institutional": InstitutionalFootprintAgent(**kwargs),
            "sr": SupportResistanceAgent(**kwargs),
            "session": SessionIntelligenceAgent(**kwargs),
            "opportunity": OpportunitySurveillanceAgent(**kwargs),
            "momentum": MomentumAgent(**kwargs),
            "price_action": PriceActionAgent(**kwargs),
            "thesis": TradeThesisAgent(**kwargs),
            "devil": DevilsAdvocateAgent(**kwargs),
            "cio": CIOAgent(**kwargs),
            "risk": RiskManagerAgent(**kwargs),
            "execution": ExecutionAgent(**kwargs),
            "management": TradeManagementAgent(**kwargs),
            "performance": PerformanceAnalystAgent(**kwargs),
            "learning": LearningAgent(**kwargs),
        }

        # Configure logging
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the VMPM system."""
        logger.info("=" * 60)
        logger.info("  VALENTINE MONEY PRINTING MACHINE (VMPM)")
        logger.info("  Multi-Agent Trading System v1.0.0")
        logger.info("=" * 60)

        # Start infrastructure
        await self.bus.start()
        self.broker.initialize()

        # Start all agents
        for name, agent in self.agents.items():
            await agent.start()
            logger.info(f"  ✓ Agent started: {agent.role} ({agent.name})")

        self._running = True
        logger.info("=" * 60)
        logger.info("  All 17 agents online. System ready.")
        logger.info(f"  Broker: {self.config.broker.type.upper()}")
        logger.info(f"  Pairs: {', '.join(self.config.trading.pairs)}")
        logger.info("=" * 60)

    async def stop(self) -> None:
        """Gracefully stop the VMPM system."""
        logger.info("Shutting down VMPM...")
        self._running = False
        self._shutdown_event.set()

        for agent in self.agents.values():
            await agent.stop()

        self.broker.shutdown()
        await self.bus.stop()
        logger.info("VMPM stopped.")

    # ------------------------------------------------------------------
    # Main Trading Loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main entry point — starts system and runs the trading loop."""
        await self.start()

        try:
            while self._running:
                await self._trading_cycle()
                await asyncio.sleep(60)  # Check every minute
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def _trading_cycle(self) -> None:
        """Execute one complete trading cycle across all pairs."""
        for pair in self.config.trading.pairs:
            try:
                await self._analyze_pair(pair)
            except Exception as exc:
                logger.error(f"Error analyzing {pair}: {exc}")

    async def _analyze_pair(self, pair: str) -> None:
        """Run the full 12-phase pipeline for a single pair."""
        logger.info(f"\n{'─' * 40}")
        logger.info(f"  Analyzing: {pair}")
        logger.info(f"{'─' * 40}")

        # Fetch data
        prices = await self.data_feed.get_multi_tf(
            pair, ["M15", "H1", "H4", "D1", "W1", "MN1"]
        )
        events = await self.calendar.get_events()
        account = self.broker.get_account_info()

        context: dict[str, Any] = {
            "pair": pair,
            "prices": prices,
            "price_data": prices.get("H1"),
            "economic_events": events,
            "account_balance": account.get("balance", 10000),
            "daily_pnl": self.broker.get_daily_pnl(),
            "weekly_pnl": self.broker.get_weekly_pnl(),
            "open_trades": len(self.broker.get_open_positions()),
            "open_positions": [
                p.to_dict() for p in self.broker.get_open_positions()
            ],
        }

        # Phase 1-6: Analysis Pipeline
        agent_reports: dict[str, dict] = {}

        # Phase 1: Fundamental Analysis
        report = await self.agents["macro"].process(context)
        agent_reports["macro-economic"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}
        context["fundamental_scores"] = report.data.get("currency_scores", {})
        context["fundamental_bias"] = report.signal

        if not self.pipeline.advance(report=None):
            return

        # Phase 2: Trend Identification (via structure agent)
        report = await self.agents["structure"].process(context)
        agent_reports["market-structure"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}
        context["trend"] = report.signal
        if not self.pipeline.advance(report=None):
            return

        # Phase 3: Support & Resistance
        report = await self.agents["sr"].process(context)
        agent_reports["support-resistance"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}
        context["buy_zones"] = report.data.get("buy_zones", [])
        context["sell_zones"] = report.data.get("sell_zones", [])

        # Also run institutional footprint
        report = await self.agents["institutional"].process(context)
        agent_reports["institutional-footprint"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}
        context["order_blocks"] = report.data.get("order_blocks", [])

        # Session analysis
        report = await self.agents["session"].process(context)
        agent_reports["session-intelligence"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        # Currency strength
        report = await self.agents["currency"].process(context)
        agent_reports["currency-strength"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        # Phase 4: Opportunity Surveillance
        report = await self.agents["opportunity"].process(context)
        agent_reports["opportunity-surveillance"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        # Phase 5: WAITING FOR PRICE — skip in analysis mode, continue to check conditions
        logger.info("  Waiting for price to reach zone...")

        # Phase 6: RSI Confirmation
        report = await self.agents["momentum"].process(context)
        agent_reports["momentum"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        # Phase 7: Candlestick Confirmation
        report = await self.agents["price_action"].process(context)
        agent_reports["price-action"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        # Phase 8: Trade Thesis
        direction = "long" if context.get("trend") == "BULLISH" else "short"
        context["direction"] = direction
        context["agent_reports"] = agent_reports
        report = await self.agents["thesis"].process(context)
        agent_reports["trade-thesis"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        # Devil's Advocate
        report = await self.agents["devil"].process(context)
        agent_reports["devils-advocate"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        # CIO Decision
        context["pipeline_state"] = self.pipeline.state.value
        report = await self.agents["cio"].process(context)
        agent_reports["cio"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

        decision = report.data.get("decision", "WAIT")
        logger.info(f"  CIO Decision: {decision}")

        # Phase 9-10: If approved, run risk management
        if decision in ("BUY", "SELL"):
            # Calculate SL/TP
            current_price = float(prices.get("H1", prices.get("H4")).close.iloc[-1]) if prices.get("H1") is not None or prices.get("H4") is not None else 0
            atr = 0.0010  # Default ATR

            if direction == "long":
                sl = current_price - 100 * atr
                tp = current_price + 300 * atr
            else:
                sl = current_price + 100 * atr
                tp = current_price - 300 * atr

            context["current_price"] = current_price
            context["stop_loss"] = sl
            context["take_profit"] = tp

            # Risk Manager
            report = await self.agents["risk"].process(context)
            agent_reports["risk-manager"] = {"signal": report.signal, "data": report.data, "confidence": report.confidence}

            if report.data.get("approved"):
                context["lot_size"] = report.data.get("lot_size", 0.01)

                # Phase 10: Execution
                context["broker"] = self.broker
                context["magic_number"] = self.config.broker.magic_number
                report = await self.agents["execution"].process(context)
                logger.info(f"  Execution: {report.signal} — {report.reasoning}")
            else:
                logger.info(f"  Risk Manager rejected: {report.reasoning}")

        logger.info(f"  Pipeline complete for {pair}")

    # ------------------------------------------------------------------
    # Single Analysis (for testing)
    # ------------------------------------------------------------------

    async def analyze_once(self, pair: str) -> dict[str, Any]:
        """Run analysis once for a single pair and return results."""
        prices = await self.data_feed.get_multi_tf(
            pair, ["M15", "H1", "H4", "D1", "W1", "MN1"]
        )
        events = await self.calendar.get_events()
        account = self.broker.get_account_info()

        context: dict[str, Any] = {
            "pair": pair,
            "prices": prices,
            "price_data": prices.get("H1"),
            "economic_events": events,
            "account_balance": account.get("balance", 10000),
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "open_trades": 0,
        }

        results: dict[str, Any] = {}

        # Run all analysis agents
        agents_to_run = [
            "macro", "currency", "structure", "institutional",
            "sr", "session", "opportunity", "momentum", "price_action",
        ]

        agent_reports: dict[str, dict] = {}
        for name in agents_to_run:
            report = await self.agents[name].process(context)
            agent_reports[name] = {
                "signal": report.signal,
                "confidence": report.confidence,
                "reasoning": report.reasoning,
            }
            results[name] = {
                "signal": report.signal,
                "confidence": report.confidence,
                "reasoning": report.reasoning,
            }

        # Thesis
        direction = "long" if agent_reports.get("structure", {}).get("signal") == "BULLISH" else "short"
        context["direction"] = direction
        context["agent_reports"] = agent_reports

        report = await self.agents["thesis"].process(context)
        agent_reports["thesis"] = {"signal": report.signal, "confidence": report.confidence}
        results["thesis"] = {"signal": report.signal, "confidence": report.confidence, "reasoning": report.reasoning}

        # Devil's Advocate
        report = await self.agents["devil"].process(context)
        results["devils_advocate"] = {"signal": report.signal, "confidence": report.confidence, "reasoning": report.reasoning}

        # CIO
        report = await self.agents["cio"].process(context)
        results["cio_decision"] = {"signal": report.signal, "confidence": report.confidence, "reasoning": report.reasoning}

        return results


# ------------------------------------------------------------------
# CLI Entry Point
# ------------------------------------------------------------------

async def main() -> None:
    """CLI entry point for VMPM."""
    import argparse

    parser = argparse.ArgumentParser(description="VMPM — Valentine Money Printing Machine")
    parser.add_argument("--config", type=str, help="Path to config YAML")
    parser.add_argument("--mode", choices=["run", "analyze", "paper"], default="paper",
                        help="run=continuous, analyze=single analysis, paper=paper trading")
    parser.add_argument("--pair", type=str, default="EURUSD", help="Pair to analyze")
    args = parser.parse_args()

    config = load_config(args.config)

    # Override to paper mode for safety
    if args.mode == "paper":
        config.broker.type = "paper"

    orchestrator = VMPMOrchestrator(config)

    if args.mode == "analyze":
        results = await orchestrator.analyze_once(args.pair)
        print("\n" + "=" * 60)
        print(f"  VMPM Analysis: {args.pair}")
        print("=" * 60)
        for agent, data in results.items():
            print(f"\n  {agent.upper()}")
            print(f"    Signal: {data['signal']}")
            print(f"    Confidence: {data.get('confidence', 0):.0%}")
            if "reasoning" in data:
                for line in data["reasoning"].split("\n")[:3]:
                    print(f"    {line}")
        print("\n" + "=" * 60)
    else:
        # Run continuously
        loop = asyncio.get_event_loop()
        for sig_name in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig_name, lambda: asyncio.create_task(orchestrator.stop()))
        await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
