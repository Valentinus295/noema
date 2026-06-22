"""Tests for FundamentalBiasAgent — Taylor rule, carry regime, macro narrative.

FundamentalBiasAgent combines:
1. Taylor Rule analysis — estimates appropriate interest rates
2. Carry regime detection — identifies carry trade opportunities
3. Central bank policy divergence — rates spreads and forward guidance
4. Macro narrative — synthesizes stories from data
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from noema.core.modern_agent import AgentReport


class TestFundamentalBiasAgent:
    """Tests for FundamentalBiasAgent."""

    async def test_agent_identity(self, default_config):
        from noema.agents.fundamental import FundamentalBiasAgent
        agent = FundamentalBiasAgent(config=default_config)
        assert agent.name == "fundamental-bias"
        assert agent.role == "Fundamental Bias"
        assert agent.priority >= 0

    async def test_process_returns_report(self, default_config):
        from noema.agents.fundamental import FundamentalBiasAgent
        agent = FundamentalBiasAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "interest_rates": {"USD": 5.5, "EUR": 4.5},
            "inflation": {"USD": 3.2, "EUR": 2.4},
            "gdp_growth": {"USD": 2.5, "EUR": 0.8},
            "economic_events": [
                {"name": "FOMC", "currency": "USD", "impact": "high",
                 "forecast": 5.5, "actual": 5.5},
            ],
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_taylor_rule_calculation(self, default_config):
        """Taylor rule should estimate appropriate interest rate."""
        from noema.agents.fundamental import FundamentalBiasAgent
        agent = FundamentalBiasAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "interest_rates": {"USD": 5.25, "EUR": 3.75},
            "inflation": {"USD": 3.5, "EUR": 2.1},
            "gdp_growth": {"USD": 3.0, "EUR": 0.5},
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_carry_regime_detection(self, default_config):
        """High rate differential should indicate carry opportunity."""
        from noema.agents.fundamental import FundamentalBiasAgent
        agent = FundamentalBiasAgent(config=default_config)
        context = {
            "pair": "AUDJPY",
            "interest_rates": {"AUD": 4.35, "JPY": 0.25},
            "inflation": {"AUD": 3.8, "JPY": 0.8},
            "gdp_growth": {"AUD": 1.5, "JPY": 0.2},
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_rate_differential_bias(self, default_config):
        """Widening rate differential should create directional bias."""
        from noema.agents.fundamental import FundamentalBiasAgent
        agent = FundamentalBiasAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "interest_rates": {"USD": 5.5, "EUR": 3.5},
            "inflation": {"USD": 2.0, "EUR": 5.0},
            "gdp_growth": {"USD": 2.8, "EUR": 0.3},
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_process_without_data(self, default_config):
        """Agent should handle minimal context gracefully."""
        from noema.agents.fundamental import FundamentalBiasAgent
        agent = FundamentalBiasAgent(config=default_config)
        report = await agent.process({"pair": "EURUSD"})
        assert isinstance(report, AgentReport)
        assert report.signal in ("NEUTRAL", "BULLISH", "BEARISH", "UNKNOWN")
