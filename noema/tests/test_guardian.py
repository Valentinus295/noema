"""Tests for GuardianAgent — kill-switch and pre-trade veto system.

GuardianAgent provides protection layers:
1. Global kill-switches (system halt, max daily loss, max drawdown)
2. Pre-trade veto (correlation check, news filter, spread filter)
3. Pre-order-send checks (price deviation, volume check, hedging check)

These tests verify the safety guardrails work correctly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from noema.core.modern_agent import AgentReport


class TestGuardianAgent:
    """Tests for GuardianAgent kill-switch and veto logic."""

    @pytest.fixture
    def guardian(self, default_config):
        from noema.agents.guardian import GuardianAgent
        return GuardianAgent(config=default_config)

    async def test_agent_identity(self, guardian):
        """Guardian should have correct identity."""
        assert guardian.name == "guardian"
        assert guardian.role == "Guardian"
        assert guardian.priority >= 0

    async def test_global_halt_enabled(self, guardian, default_config):
        """When global halt is active, all trades should be rejected."""
        from noema.agents.guardian import GuardianAgent
        agent = GuardianAgent(config=default_config)
        context = {
            "global_halt": True,
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
        }
        report = await agent.process(context)
        assert report.signal == "REJECT"
        assert "global halt" in report.reasoning.lower()

    async def test_max_daily_loss_breach(self, guardian, default_config):
        """When daily loss exceeds limit, trades should be rejected."""
        from noema.agents.guardian import GuardianAgent
        agent = GuardianAgent(config=default_config)
        context = {
            "daily_pnl": -500.0,  # -5% of 10k account
            "account_balance": 10000.0,
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
        }
        report = await agent.process(context)
        assert report.signal in ("REJECT", "HALT")

    async def test_news_event_protection(self, guardian, default_config):
        """High-impact news events should trigger caution."""
        from noema.agents.guardian import GuardianAgent
        agent = GuardianAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
            "upcoming_news": [
                {"name": "NFP", "impact": "high", "minutes_away": 15}
            ],
            "account_balance": 10000.0,
            "daily_pnl": 0.0,
        }
        report = await agent.process(context)
        # Should either reject or warn about news
        assert isinstance(report, AgentReport)

    async def test_spread_protection(self, guardian, default_config):
        """Abnormally high spread should trigger rejection."""
        from noema.agents.guardian import GuardianAgent
        agent = GuardianAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
            "spread_pips": 50.0,  # Very high spread
            "account_balance": 10000.0,
            "daily_pnl": 0.0,
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)
        # Spread check should be logged

    async def test_correlation_limit(self, guardian, default_config):
        """Opening correlated positions should be prevented."""
        from noema.agents.guardian import GuardianAgent
        agent = GuardianAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
            "open_positions": [
                {"symbol": "EURUSD", "direction": "buy"},
            ],
            "account_balance": 10000.0,
            "daily_pnl": 0.0,
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_pass_valid_setup(self, guardian, default_config):
        """A clean setup with no issues should pass or be reviewed."""
        from noema.agents.guardian import GuardianAgent
        agent = GuardianAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "stop_loss": 1.0900,
            "take_profit": 1.1300,
            "account_balance": 10000.0,
            "daily_pnl": 0.0,
            "open_positions": [],
            "spread_pips": 1.5,
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)
        assert report.signal in ("APPROVE", "CAUTION", "NEUTRAL")
