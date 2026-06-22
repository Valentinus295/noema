"""Tests for ReflectorAgent — self-learning system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vmpm.agents.reflector import ReflectorAgent


class TestReflectorAgent:
    """Tests for the ReflectorAgent self-learning system."""

    def test_initialization(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))
        assert agent.knowledge["trades"] == []
        assert agent.knowledge["lessons"] == []

    def test_record_trade(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))
        agent.record_trade({
            "ticket": 1, "symbol": "EURUSD", "direction": "buy",
            "pnl": 50.0, "session": "london", "market_regime": "trending",
            "confidence": 0.8, "rsi_at_entry": 35,
            "candlestick_pattern": "bullish_engulfing",
        })
        assert len(agent.knowledge["trades"]) == 1
        assert agent.knowledge["trades"][0]["pnl"] == 50.0

    def test_learn_with_insufficient_trades(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))
        agent.record_trade({"pnl": 10, "session": "london"})
        insights = agent.learn()
        assert "message" in insights

    def test_learn_with_sufficient_trades(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))

        # Record 20 trades
        for i in range(20):
            agent.record_trade({
                "ticket": i, "symbol": "EURUSD", "direction": "buy",
                "pnl": 50 if i % 3 != 0 else -20,
                "session": "london" if i % 2 == 0 else "new_york",
                "market_regime": "trending" if i % 4 == 0 else "ranging",
                "confidence": 0.8 if i % 3 != 0 else 0.4,
                "rsi_at_entry": 35 + i, "candlestick_pattern": "bullish_engulfing",
                "exit_reason": "tp" if i % 3 != 0 else "sl",
                "risk_reward": 3.0, "confluence_score": 0.7,
            })

        insights = agent.learn()
        assert "failure_patterns" in insights
        assert "setup_analysis" in insights
        assert "session_analysis" in insights
        assert "bayesian_edge" in insights
        assert "lessons" in insights

    def test_failure_mining(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))

        # Record losing trades with patterns
        for i in range(10):
            agent.record_trade({
                "ticket": i, "pnl": -20, "session": "off_hours",
                "confidence": 0.3, "rsi_at_entry": 80, "direction": "buy",
                "exit_reason": "sl", "confluence_score": 0.4,
            })

        failures = agent._mine_losing_trades()
        assert len(failures) > 0
        assert any(f["pattern"] == "bad_session" for f in failures)

    def test_bayesian_win_rate(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))

        for i in range(20):
            agent.record_trade({
                "pnl": 30 if i < 12 else -20,
                "session": "london", "confidence": 0.7,
            })

        bayesian = agent._bayesian_win_rate()
        assert 0 < bayesian["posterior_mean"] < 1
        assert bayesian["total_trades"] == 20
        assert bayesian["wins"] == 12

    def test_get_adapted_params(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))
        params = agent.get_adapted_params("trending")
        assert "risk_multiplier" in params
        assert "min_confidence" in params
        assert "preferred_sessions" in params

    def test_operating_manual(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))
        manual = agent.get_operating_manual()
        assert isinstance(manual, str)

    def test_persistence(self, tmp_path):
        path = tmp_path / "knowledge.json"
        agent = ReflectorAgent(knowledge_path=str(path))
        agent.record_trade({"pnl": 50, "session": "london"})
        agent._save_knowledge()

        agent2 = ReflectorAgent(knowledge_path=str(path))
        assert len(agent2.knowledge["trades"]) == 1

    def test_session_analysis(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))
        for i in range(10):
            agent.record_trade({
                "pnl": 30 if i % 2 == 0 else -10,
                "session": "london" if i % 2 == 0 else "asian",
                "confidence": 0.7,
            })
        sessions = agent._analyze_sessions()
        assert "london" in sessions
        assert "asian" in sessions

    def test_auto_learn_after_10_trades(self, tmp_path):
        agent = ReflectorAgent(knowledge_path=str(tmp_path / "test.json"))
        for i in range(12):
            agent.record_trade({"pnl": 10, "session": "london", "confidence": 0.7})
        # Buffer auto-clears at 10, then 2 more trades added
        assert len(agent._trade_buffer) == 2
        assert len(agent.knowledge["trades"]) == 12
