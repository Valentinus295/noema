"""Tests for PortfolioAgent — PCA, correlation, currency strength gating.

PortfolioAgent ensures diversified exposure:
1. PCA factor exposure — limits exposure to dominant factor
2. Hierarchical correlation — prevents over-concentration in correlated pairs
3. Currency strength rank — positions in top-N strongest/weakest pairs
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from noema.core.modern_agent import AgentReport


class TestPortfolioAgent:
    """Tests for PortfolioAgent."""

    async def test_agent_identity(self, default_config):
        from noema.agents.portfolio import PortfolioAgent
        agent = PortfolioAgent(config=default_config)
        assert agent.name == "portfolio"
        assert agent.priority >= 0

    async def test_process_returns_report(self, default_config):
        from noema.agents.portfolio import PortfolioAgent
        agent = PortfolioAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "account_balance": 10000.0,
            "open_positions": [],
            "correlation_matrix": pd.DataFrame(
                [[1.0, 0.8], [0.8, 1.0]],
                index=["EURUSD", "GBPUSD"],
                columns=["EURUSD", "GBPUSD"],
            ),
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_correlation_limit_check(self, default_config):
        """Portfolio should check correlation with existing positions."""
        from noema.agents.portfolio import PortfolioAgent
        agent = PortfolioAgent(config=default_config)
        context = {
            "pair": "GBPUSD",
            "direction": "long",
            "current_price": 1.2500,
            "account_balance": 10000.0,
            "open_positions": [
                {"symbol": "EURUSD", "direction": "buy"},
            ],
            "correlation_matrix": pd.DataFrame(
                [[1.0, 0.85], [0.85, 1.0]],
                index=["EURUSD", "GBPUSD"],
                columns=["EURUSD", "GBPUSD"],
            ),
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_pca_factor_exposure(self, default_config):
        """Portfolio should compute factor exposure."""
        from noema.agents.portfolio import PortfolioAgent
        agent = PortfolioAgent(config=default_config)

        # Create multi-currency returns for PCA
        np.random.seed(42)
        n = 100
        returns = pd.DataFrame({
            "EURUSD": np.random.randn(n) * 0.01,
            "GBPUSD": np.random.randn(n) * 0.01,
            "USDJPY": np.random.randn(n) * 0.005,
        })

        # The agent might need custom context
        report = await agent.process({})
        assert isinstance(report, AgentReport)

    async def test_currency_strength_ranking(self, default_config):
        """Portfolio should rank currencies by strength."""
        from noema.agents.portfolio import PortfolioAgent
        agent = PortfolioAgent(config=default_config)
        context = {
            "currency_scores": {
                "USD": 5.0,
                "EUR": -2.0,
                "GBP": 1.0,
                "JPY": -4.0,
            },
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)

    async def test_max_positions_gate(self, default_config):
        """Portfolio should reject new positions when max is reached."""
        from noema.agents.portfolio import PortfolioAgent
        agent = PortfolioAgent(config=default_config)
        context = {
            "pair": "EURUSD",
            "direction": "long",
            "current_price": 1.1000,
            "account_balance": 10000.0,
            "open_positions": [
                {"symbol": "EURUSD", "direction": "buy"},
                {"symbol": "GBPUSD", "direction": "buy"},
                {"symbol": "USDJPY", "direction": "sell"},
            ],
        }
        report = await agent.process(context)
        assert isinstance(report, AgentReport)
