"""Unit tests for all 17 VMPM agents.

Analysis Agents:  MacroEconomic, CurrencyStrength, MarketStructure,
                  InstitutionalFootprint, SupportResistance, SessionIntelligence
Signal Agents:    OpportunitySurveillance, Momentum, PriceAction
Decision Agents:  TradeThesis, DevilsAdvocate, CIO
Execution Agents: RiskManager, Execution, TradeManagement
Learning Agents:  PerformanceAnalyst, Learning
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

from vmpm.core.agent import AgentReport


# ===========================================================================
# Analysis Agents (1-6)
# ===========================================================================


class TestMacroEconomicAgent:
    """Tests for MacroEconomicAgent (#2)."""

    async def test_analyze_returns_report(self, agent_context, default_config):
        from vmpm.agents.macro import MacroEconomicAgent
        agent = MacroEconomicAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL", "STRONG_BULLISH", "STRONG_BEARISH")
        assert "currency_scores" in report.data
        assert "bias" in report.data

    async def test_analyze_with_empty_events(self, agent_context, default_config):
        from vmpm.agents.macro import MacroEconomicAgent
        agent = MacroEconomicAgent(config=default_config, message_bus=MagicMock())
        agent_context["economic_events"] = []
        report = await agent.process(agent_context)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL", "STRONG_BULLISH", "STRONG_BEARISH")

    async def test_agent_identity(self, default_config):
        from vmpm.agents.macro import MacroEconomicAgent
        agent = MacroEconomicAgent(config=default_config)
        assert agent.name == "macro-economic"
        assert agent.role == "Macro Economic Intelligence"
        assert agent.priority == 10


class TestCurrencyStrengthAgent:
    """Tests for CurrencyStrengthAgent (#3)."""

    async def test_analyze_returns_report(self, agent_context, default_config):
        from vmpm.agents.currency import CurrencyStrengthAgent
        agent = CurrencyStrengthAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "currency_scores" in report.data
        assert "ranking" in report.data
        assert "strongest" in report.data
        assert "weakest" in report.data

    async def test_ranking_order(self, agent_context, default_config):
        from vmpm.agents.currency import CurrencyStrengthAgent
        agent = CurrencyStrengthAgent(config=default_config)
        report = await agent.process(agent_context)
        ranking = report.data["ranking"]
        if ranking:
            scores = [s for _, s in ranking]
            assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))

    async def test_identity(self, default_config):
        from vmpm.agents.currency import CurrencyStrengthAgent
        agent = CurrencyStrengthAgent(config=default_config)
        assert agent.name == "currency-strength"
        assert agent.priority == 9


class TestMarketStructureAgent:
    """Tests for MarketStructureAgent (#4)."""

    async def test_analyze_returns_report(self, agent_context, default_config):
        from vmpm.agents.structure import MarketStructureAgent
        agent = MarketStructureAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "structure" in report.data
        assert "bos_detected" in report.data
        assert "choch_detected" in report.data

    async def test_insufficient_data(self, default_config):
        from vmpm.agents.structure import MarketStructureAgent
        agent = MarketStructureAgent(config=default_config)
        context = {"price_data": pd.DataFrame({"close": [1.0] * 5})}
        report = await agent.process(context)
        assert report.signal == "NEUTRAL"
        assert "Insufficient data" in report.reasoning

    async def test_identity(self, default_config):
        from vmpm.agents.structure import MarketStructureAgent
        agent = MarketStructureAgent(config=default_config)
        assert agent.name == "market-structure"
        assert agent.priority == 8


class TestInstitutionalFootprintAgent:
    """Tests for InstitutionalFootprintAgent (#5)."""

    async def test_analyze_returns_report(self, agent_context, default_config):
        from vmpm.agents.institutional import InstitutionalFootprintAgent
        agent = InstitutionalFootprintAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "order_blocks" in report.data
        assert "fair_value_gaps" in report.data
        assert "liquidity_sweeps" in report.data

    async def test_insufficient_data(self, default_config):
        from vmpm.agents.institutional import InstitutionalFootprintAgent
        agent = InstitutionalFootprintAgent(config=default_config)
        context = {"price_data": pd.DataFrame({"close": [1.0] * 5})}
        report = await agent.process(context)
        assert report.signal == "NEUTRAL"

    async def test_identity(self, default_config):
        from vmpm.agents.institutional import InstitutionalFootprintAgent
        agent = InstitutionalFootprintAgent(config=default_config)
        assert agent.name == "institutional-footprint"
        assert agent.priority == 7


class TestSupportResistanceAgent:
    """Tests for SupportResistanceAgent (#6)."""

    async def test_analyze_returns_report(self, agent_context, default_config):
        from vmpm.agents.sr import SupportResistanceAgent
        agent = SupportResistanceAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "buy_zones" in report.data
        assert "sell_zones" in report.data
        assert "current_price" in report.data
        assert "nearest_support" in report.data
        assert "nearest_resistance" in report.data

    async def test_buy_and_sell_zones(self, agent_context, default_config):
        from vmpm.agents.sr import SupportResistanceAgent
        agent = SupportResistanceAgent(config=default_config)
        report = await agent.process(agent_context)
        assert len(report.data["buy_zones"]) > 0
        assert len(report.data["sell_zones"]) > 0
        for zone in report.data["buy_zones"]:
            assert "name" in zone
            assert "level" in zone
        for zone in report.data["sell_zones"]:
            assert "name" in zone
            assert "level" in zone

    async def test_identity(self, default_config):
        from vmpm.agents.sr import SupportResistanceAgent
        agent = SupportResistanceAgent(config=default_config)
        assert agent.name == "support-resistance"
        assert agent.priority == 6


class TestSessionIntelligenceAgent:
    """Tests for SessionIntelligenceAgent (#7)."""

    async def test_analyze_returns_report(self, default_config):
        from vmpm.agents.session import SessionIntelligenceAgent
        agent = SessionIntelligenceAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process({})
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "NEUTRAL")
        assert "active_sessions" in report.data
        assert "active_overlaps" in report.data
        assert "is_high_probability" in report.data
        assert "is_low_probability" in report.data
        assert "current_hour_eat" in report.data

    async def test_session_format(self, default_config):
        from vmpm.agents.session import SessionIntelligenceAgent
        agent = SessionIntelligenceAgent(config=default_config)
        report = await agent.process({})
        sessions = report.data["active_sessions"]
        for s in sessions:
            assert s in ("sydney", "tokyo", "london", "new_york")

    async def test_identity(self, default_config):
        from vmpm.agents.session import SessionIntelligenceAgent
        agent = SessionIntelligenceAgent(config=default_config)
        assert agent.name == "session-intelligence"
        assert agent.priority == 5


# ===========================================================================
# Signal Agents (7-9)
# ===========================================================================


class TestOpportunitySurveillanceAgent:
    """Tests for OpportunitySurveillanceAgent (#8)."""

    async def test_analyze_with_zones(self, agent_context, default_config, buy_zones, sell_zones, order_blocks):
        from vmpm.agents.opportunity import OpportunitySurveillanceAgent
        agent = OpportunitySurveillanceAgent(config=default_config, message_bus=MagicMock())
        agent_context["buy_zones"] = buy_zones
        agent_context["sell_zones"] = sell_zones
        agent_context["order_blocks"] = order_blocks
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert "opportunities" in report.data
        assert "count" in report.data
        assert "current_price" in report.data

    async def test_no_zones(self, agent_context, default_config):
        from vmpm.agents.opportunity import OpportunitySurveillanceAgent
        agent = OpportunitySurveillanceAgent(config=default_config)
        agent_context["buy_zones"] = []
        agent_context["sell_zones"] = []
        agent_context["order_blocks"] = []
        report = await agent.process(agent_context)
        assert report.data["count"] == 0

    async def test_identity(self, default_config):
        from vmpm.agents.opportunity import OpportunitySurveillanceAgent
        agent = OpportunitySurveillanceAgent(config=default_config)
        assert agent.name == "opportunity-surveillance"
        assert agent.priority == 4


class TestMomentumAgent:
    """Tests for MomentumAgent (#9)."""

    async def test_analyze_returns_report(self, agent_context, default_config):
        from vmpm.agents.momentum import MomentumAgent
        agent = MomentumAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "rsi" in report.data
        assert "rsi_signal" in report.data
        assert "macd" in report.data
        assert "macd_histogram" in report.data
        assert "adx" in report.data
        assert "divergence" in report.data

    async def test_insufficient_data(self, default_config):
        from vmpm.agents.momentum import MomentumAgent
        agent = MomentumAgent(config=default_config)
        context = {"price_data": pd.DataFrame({"close": [1.0] * 5})}
        report = await agent.process(context)
        assert report.signal == "NEUTRAL"

    async def test_identity(self, default_config):
        from vmpm.agents.momentum import MomentumAgent
        agent = MomentumAgent(config=default_config)
        assert agent.name == "momentum"
        assert agent.priority == 4


class TestPriceActionAgent:
    """Tests for PriceActionAgent (#10)."""

    async def test_analyze_returns_report(self, agent_context, default_config):
        from vmpm.agents.price_action import PriceActionAgent
        agent = PriceActionAgent(config=default_config, message_bus=MagicMock())
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "patterns" in report.data
        assert "confirmation" in report.data

    async def test_insufficient_data(self, default_config):
        from vmpm.agents.price_action import PriceActionAgent
        agent = PriceActionAgent(config=default_config)
        context = {"price_data": pd.DataFrame({"close": [1.0] * 3})}
        report = await agent.process(context)
        assert report.signal == "NEUTRAL"

    async def test_identity(self, default_config):
        from vmpm.agents.price_action import PriceActionAgent
        agent = PriceActionAgent(config=default_config)
        assert agent.name == "price-action"
        assert agent.priority == 3


# ===========================================================================
# Decision Agents (10-12)
# ===========================================================================


class TestTradeThesisAgent:
    """Tests for TradeThesisAgent (#11)."""

    async def test_analyze_returns_report(self, agent_context, default_config, agent_reports):
        from vmpm.agents.thesis import TradeThesisAgent
        agent = TradeThesisAgent(config=default_config, message_bus=MagicMock())
        agent_context["agent_reports"] = agent_reports
        agent_context["direction"] = "long"
        report = await agent.process(agent_context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "evidence_for" in report.data
        assert "evidence_against" in report.data
        assert "direction" in report.data

    async def test_bullish_evidence(self, default_config):
        from vmpm.agents.thesis import TradeThesisAgent
        agent = TradeThesisAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "agent_reports": {
                "macro-economic": {"signal": "BULLISH"},
                "market-structure": {"signal": "BULLISH"},
                "support-resistance": {"signal": "BULLISH"},
                "momentum": {"signal": "NEUTRAL"},
                "institutional-footprint": {"signal": "NEUTRAL"},
                "price-action": {"signal": "NEUTRAL"},
            },
        }
        report = await agent.process(context)
        assert len(report.data["evidence_for"]) >= 2

    async def test_mixed_signals(self, default_config):
        from vmpm.agents.thesis import TradeThesisAgent
        agent = TradeThesisAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "agent_reports": {
                "macro-economic": {"signal": "BEARISH"},
                "market-structure": {"signal": "BEARISH"},
                "momentum": {"signal": "NEUTRAL"},
            },
        }
        report = await agent.process(context)
        assert len(report.data["evidence_against"]) >= 1

    async def test_identity(self, default_config):
        from vmpm.agents.thesis import TradeThesisAgent
        agent = TradeThesisAgent(config=default_config)
        assert agent.name == "trade-thesis"
        assert agent.priority == 2


class TestDevilsAdvocateAgent:
    """Tests for DevilsAdvocateAgent (#12)."""

    async def test_approve_good_setup(self, agent_context, default_config, agent_reports):
        from vmpm.agents.devil import DevilsAdvocateAgent
        agent = DevilsAdvocateAgent(config=default_config, message_bus=MagicMock())
        agent_context["agent_reports"] = agent_reports
        agent_context["direction"] = "long"
        report = await agent.process(agent_context)
        assert report.signal in ("APPROVE", "REJECT")
        assert "weaknesses" in report.data
        assert "verdict" in report.data

    async def test_reject_conflicting(self, default_config):
        from vmpm.agents.devil import DevilsAdvocateAgent
        agent = DevilsAdvocateAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "agent_reports": {
                "macro-economic": {"signal": "BEARISH"},
                "market-structure": {"signal": "BEARISH"},
                "support-resistance": {"signal": "BEARISH"},
                "session-intelligence": {"signal": "NEUTRAL", "data": {"is_low_probability": True}},
                "opportunity-surveillance": {"signal": "NEUTRAL", "data": {"count": 0}},
            },
        }
        report = await agent.process(context)
        assert len(report.data["weaknesses"]) >= 2

    async def test_identity(self, default_config):
        from vmpm.agents.devil import DevilsAdvocateAgent
        agent = DevilsAdvocateAgent(config=default_config)
        assert agent.name == "devils-advocate"
        assert agent.priority == 1


class TestCIOAgent:
    """Tests for CIOAgent (#1)."""

    async def test_buy_decision(self, agent_context, default_config, agent_reports):
        from vmpm.agents.cio import CIOAgent
        agent = CIOAgent(config=default_config, message_bus=MagicMock())
        agent_context["agent_reports"] = agent_reports
        agent_context["direction"] = "long"
        agent_context["pipeline_state"] = "risk_management"
        report = await agent.process(agent_context)
        assert report.signal in ("BUY", "SELL", "WAIT", "REJECT")
        assert "decision" in report.data
        assert "consensus" in report.data

    async def test_reject_when_devil_says_reject(self, default_config):
        from vmpm.agents.cio import CIOAgent
        agent = CIOAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "pipeline_state": "trade_validation",
            "agent_reports": {
                "devils-advocate": {"signal": "REJECT"},
                "macro-economic": {"signal": "BULLISH"},
            },
        }
        report = await agent.process(context)
        assert report.signal == "REJECT"

    async def test_wait_low_consensus(self, default_config):
        from vmpm.agents.cio import CIOAgent
        agent = CIOAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "pipeline_state": "trade_validation",
            "agent_reports": {
                "macro-economic": {"signal": "NEUTRAL"},
                "market-structure": {"signal": "NEUTRAL"},
                "trade-thesis": {"signal": "NEUTRAL", "confidence": 0.3},
            },
        }
        report = await agent.process(context)
        assert report.signal == "WAIT"

    async def test_identity(self, default_config):
        from vmpm.agents.cio import CIOAgent
        agent = CIOAgent(config=default_config)
        assert agent.name == "cio"
        assert agent.priority == 0


# ===========================================================================
# Execution Agents (13-15)
# ===========================================================================


class TestRiskManagerAgent:
    """Tests for RiskManagerAgent (#13)."""

    async def test_approve_valid_trade(self, default_config):
        from vmpm.agents.risk import RiskManagerAgent
        agent = RiskManagerAgent(config=default_config)
        context = {
            "account_balance": 10000.0,
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "open_trades": 0,
        }
        report = await agent.process(context)
        assert report.signal == "APPROVE"
        assert report.data["approved"] is True
        assert report.data["lot_size"] > 0
        assert report.data["rr_ratio"] >= 2.0

    async def test_reject_max_daily_loss(self, default_config):
        from vmpm.agents.risk import RiskManagerAgent
        agent = RiskManagerAgent(config=default_config)
        context = {
            "account_balance": 10000.0,
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1200,
            "daily_pnl": -500.0,
            "weekly_pnl": 0.0,
            "open_trades": 0,
        }
        report = await agent.process(context)
        assert report.signal == "REJECT"
        assert "Daily loss limit" in report.reasoning

    async def test_reject_max_open_trades(self, default_config):
        from vmpm.agents.risk import RiskManagerAgent
        agent = RiskManagerAgent(config=default_config)
        context = {
            "account_balance": 10000.0,
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "open_trades": 5,
        }
        report = await agent.process(context)
        assert report.signal == "REJECT"

    async def test_reject_poor_rr(self, default_config):
        from vmpm.agents.risk import RiskManagerAgent
        agent = RiskManagerAgent(config=default_config)
        context = {
            "account_balance": 10000.0,
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1050,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "open_trades": 0,
        }
        report = await agent.process(context)
        assert report.signal == "REJECT"

    async def test_identity(self, default_config):
        from vmpm.agents.risk import RiskManagerAgent
        agent = RiskManagerAgent(config=default_config)
        assert agent.name == "risk-manager"
        assert agent.priority == 1


class TestExecutionAgent:
    """Tests for ExecutionAgent (#14)."""

    async def test_simulated_trade(self, default_config):
        from vmpm.agents.execution import ExecutionAgent
        agent = ExecutionAgent(config=default_config)
        context = {
            "broker": MagicMock(),
            "pair": "EURUSD",
            "direction": "long",
            "lot_size": 0.1,
            "stop_loss": 1.0900,
            "take_profit": 1.1100,
            "magic_number": 20260609,
        }
        report = await agent.process(context)
        assert report.signal in ("SIMULATED", "ERROR")

    async def test_no_broker(self, default_config):
        from vmpm.agents.execution import ExecutionAgent
        agent = ExecutionAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "lot_size": 0.1,
            "stop_loss": 1.0900,
            "take_profit": 1.1100,
        }
        report = await agent.process(context)
        assert report.signal == "ERROR"

    async def test_identity(self, default_config):
        from vmpm.agents.execution import ExecutionAgent
        agent = ExecutionAgent(config=default_config)
        assert agent.name == "execution"
        assert agent.priority == 0


class TestTradeManagementAgent:
    """Tests for TradeManagementAgent (#15)."""

    async def test_hold_with_no_positions(self, default_config):
        from vmpm.agents.management import TradeManagementAgent
        agent = TradeManagementAgent(config=default_config)
        context = {"open_positions": [], "current_prices": {}}
        report = await agent.process(context)
        assert report.signal == "HOLD"
        assert report.data["positions_monitored"] == 0

    async def test_actions_with_positions(self, default_config):
        from vmpm.agents.management import TradeManagementAgent
        agent = TradeManagementAgent(config=default_config)
        context = {
            "open_positions": [
                {"ticket": 1001, "symbol": "EURUSD", "type": "buy",
                 "open_price": 1.1000, "sl": 1.0950, "tp": 1.1200, "volume": 0.1},
            ],
            "current_prices": {"EURUSD": 1.1080},
            "upcoming_news": [],
        }
        report = await agent.process(context)
        assert report.signal in ("ACTION", "HOLD")

    async def test_emergency_exit(self, default_config):
        from vmpm.agents.management import TradeManagementAgent
        agent = TradeManagementAgent(config=default_config)
        context = {
            "open_positions": [
                {"ticket": 1001, "symbol": "EURUSD", "type": "buy",
                 "open_price": 1.1000, "sl": 1.0950, "tp": 1.1200, "volume": 0.1},
            ],
            "current_prices": {"EURUSD": 1.1015},
            "upcoming_news": [{"impact": "high", "name": "NFP"}],
        }
        report = await agent.process(context)
        if report.signal == "ACTION":
            actions = report.data["actions"]
            assert any(a["type"] == "emergency_exit" for a in actions)

    async def test_identity(self, default_config):
        from vmpm.agents.management import TradeManagementAgent
        agent = TradeManagementAgent(config=default_config)
        assert agent.name == "trade-management"
        assert agent.priority == 0


# ===========================================================================
# Learning Agents (16-17)
# ===========================================================================


class TestPerformanceAnalystAgent:
    """Tests for PerformanceAnalystAgent (#16)."""

    async def test_analyze_no_trades(self, default_config):
        from vmpm.agents.performance import PerformanceAnalystAgent
        agent = PerformanceAnalystAgent(config=default_config)
        context = {"trade_history": []}
        report = await agent.process(context)
        assert report.signal == "NEUTRAL"
        assert report.data["total_trades"] == 0

    async def test_analyze_with_trades(self, default_config):
        from vmpm.agents.performance import PerformanceAnalystAgent
        agent = PerformanceAnalystAgent(config=default_config)
        context = {
            "trade_history": [
                {"pnl": 50, "pair": "EURUSD", "session": "london"},
                {"pnl": 30, "pair": "GBPUSD", "session": "london"},
                {"pnl": -20, "pair": "EURUSD", "session": "ny"},
            ]
        }
        report = await agent.process(context)
        assert report.data["total_trades"] == 3
        assert report.data["wins"] == 2
        assert report.data["losses"] == 1
        assert report.data["win_rate"] == 2 / 3
        assert report.data["profit_factor"] > 0
        assert "session_stats" in report.data

    async def test_high_win_rate(self, default_config):
        from vmpm.agents.performance import PerformanceAnalystAgent
        agent = PerformanceAnalystAgent(config=default_config)
        context = {
            "trade_history": [
                {"pnl": v, "pair": "EURUSD", "session": "london"}
                for v in [50, 30, 20, -10, 40, 60, -5, 25]
            ]
        }
        report = await agent.process(context)
        assert report.signal == "BULLISH"

    async def test_identity(self, default_config):
        from vmpm.agents.performance import PerformanceAnalystAgent
        agent = PerformanceAnalystAgent(config=default_config)
        assert agent.name == "performance-analyst"
        assert agent.priority == 0


class TestLearningAgent:
    """Tests for LearningAgent (#17)."""

    async def test_no_trade_to_learn(self, default_config):
        from vmpm.agents.learning import LearningAgent
        agent = LearningAgent(config=default_config)
        context = {"completed_trade": {}}
        report = await agent.process(context)
        assert report.signal == "NEUTRAL"

    async def test_record_trade(self, default_config, tmp_path):
        from vmpm.agents.learning import LearningAgent
        agent = LearningAgent(config=default_config)
        agent.knowledge_file = tmp_path / "test_knowledge.json"
        agent.knowledge = {"trades": [], "insights": {}}

        context = {
            "completed_trade": {
                "pair": "EURUSD",
                "direction": "long",
                "pnl": 50.0,
                "session": "london",
                "market_regime": "trending_bull",
                "trend": "bullish",
                "rsi_at_entry": 35,
                "candlestick_pattern": "bullish_engulfing",
                "order_block_type": "bullish",
                "risk_reward": 3.0,
                "confidence": 0.8,
            }
        }
        report = await agent.process(context)
        assert report.signal == "LEARNED"
        assert report.data["recorded"] is True
        assert report.data["total_trades_learned"] == 1

        assert agent.knowledge_file.exists()
        saved = json.loads(agent.knowledge_file.read_text())
        assert len(saved["trades"]) == 1
        assert saved["trades"][0]["pair"] == "EURUSD"

    async def test_analyze_patterns_with_multiple_trades(self, default_config, tmp_path):
        from vmpm.agents.learning import LearningAgent
        agent = LearningAgent(config=default_config)
        agent.knowledge_file = tmp_path / "test_knowledge2.json"

        trades = [
            {"session": "london", "outcome": "win", "pnl": 50,
             "candlestick_pattern": "bullish_engulfing"},
            {"session": "london", "outcome": "win", "pnl": 30,
             "candlestick_pattern": "hammer"},
            {"session": "ny", "outcome": "loss", "pnl": -20,
             "candlestick_pattern": "bullish_engulfing"},
            {"session": "london", "outcome": "win", "pnl": 40,
             "candlestick_pattern": "morning_star"},
            {"session": "tokyo", "outcome": "loss", "pnl": -10,
             "candlestick_pattern": "hammer"},
        ]
        agent.knowledge = {"trades": trades, "insights": {}}
        insights = agent._analyze_patterns()

        assert "best_session" in insights
        assert insights["best_session"] != "N/A"
        assert "session_stats" in insights
        assert "pattern_stats" in insights

    async def test_knowledge_persistence(self, default_config, tmp_path):
        from vmpm.agents.learning import LearningAgent
        agent = LearningAgent(config=default_config)
        agent.knowledge_file = tmp_path / "persist.json"
        agent.knowledge = {"trades": [], "insights": {}}

        agent.knowledge["trades"].append({"pair": "EURUSD", "outcome": "win"})
        agent._save_knowledge()

        agent2 = LearningAgent(config=default_config)
        agent2.knowledge_file = tmp_path / "persist.json"
        agent2.knowledge = agent2._load_knowledge()
        assert len(agent2.knowledge["trades"]) == 1

    async def test_identity(self, default_config):
        from vmpm.agents.learning import LearningAgent
        agent = LearningAgent(config=default_config)
        assert agent.name == "learning"
        assert agent.priority == 0
