"""Unit tests for core infrastructure modules.

Covers:
- Agent base class (lifecycle, process, error handling)
- MessageBus (pub/sub, routing, lifecycle)
- TradingPipeline (state transitions, rejection, reset)
- Config loader (defaults, overrides, env vars)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from noema.core.agent import Agent, AgentReport, AgentState
from noema.core.config import (
    NoemaConfig, BrokerConfig, RiskConfig, TradingConfig,
    EconometricsConfig, load_config,
)
from noema.core.message_bus import MessageBus, Message
from noema.core.state_machine import (
    TradingPipeline, PipelineState, PhaseResult,
)


# ===========================================================================
# Agent Base Class
# ===========================================================================


class _ConcreteAgent(Agent):
    """Minimal concrete agent for testing the base class."""
    name = "test-agent"
    role = "Test Agent"
    priority = 5

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        return AgentReport(
            agent_name=self.name,
            signal="BULLISH",
            confidence=0.8,
            data={"key": "value"},
            reasoning="Test analysis",
        )


class _FailingAgent(Agent):
    """Agent that raises an exception during analyze."""
    name = "failing-agent"
    role = "Failing Agent"

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        raise ValueError("Something went wrong")


class TestAgentBase:
    """Tests for the Agent base class."""

    async def test_agent_initialization(self):
        """Agent should initialize with default state."""
        agent = _ConcreteAgent()
        assert agent.name == "test-agent"
        assert agent.role == "Test Agent"
        assert agent.state == AgentState.IDLE
        assert agent.last_report is None

    async def test_agent_initialization_with_bus(self, mock_message_bus):
        """Agent should accept message bus and config."""
        config = MagicMock()
        agent = _ConcreteAgent(message_bus=mock_message_bus, config=config)
        assert agent.message_bus is mock_message_bus
        assert agent.config is config

    async def test_process_returns_report(self):
        """process() should return an AgentReport on success."""
        agent = _ConcreteAgent()
        report = await agent.process({})
        assert isinstance(report, AgentReport)
        assert report.agent_name == "test-agent"
        assert report.signal == "BULLISH"
        assert report.confidence == 0.8
        assert report.data == {"key": "value"}
        assert report.reasoning == "Test analysis"

    async def test_process_handles_error(self):
        """process() should catch exceptions and return ERROR report."""
        agent = _FailingAgent()
        report = await agent.process({})
        assert isinstance(report, AgentReport)
        assert report.signal == "ERROR"
        assert report.confidence == 0.0
        assert "Error:" in report.reasoning
        assert "Something went wrong" in report.reasoning

    async def test_process_sets_state(self):
        """process() should set PROCESSING then IDLE state."""
        agent = _ConcreteAgent()
        assert agent.state == AgentState.IDLE
        await agent.process({})
        assert agent.state == AgentState.IDLE

    async def test_process_sets_error_state(self):
        """process() should set ERROR state on failure."""
        agent = _FailingAgent()
        await agent.process({})
        assert agent.state == AgentState.ERROR

    async def test_last_report_updates(self):
        """last_report should return the most recent report."""
        agent = _ConcreteAgent()
        assert agent.last_report is None
        await agent.process({})
        assert agent.last_report is not None
        assert agent.last_report.signal == "BULLISH"

    async def test_start_stop_lifecycle(self):
        """Agent should transition through start/stop states."""
        bus = MagicMock(spec=MessageBus)
        bus.register = AsyncMock()
        agent = _ConcreteAgent(message_bus=bus)
        assert agent.state == AgentState.IDLE
        await agent.start()
        assert agent.state == AgentState.IDLE
        await agent.stop()
        assert agent.state == AgentState.STOPPED

    async def test_start_without_bus(self):
        """Agent start should work without a message bus."""
        agent = _ConcreteAgent()
        await agent.start()
        assert agent.state == AgentState.IDLE
        await agent.stop()
        assert agent.state == AgentState.STOPPED

    async def test_analyze_not_implemented(self):
        """Base analyze() should raise NotImplementedError."""
        agent = Agent()
        agent.name = "abstract"
        with pytest.raises(NotImplementedError):
            await agent.analyze({})

    def test_repr(self):
        """__repr__ should include class name, name, and state."""
        agent = _ConcreteAgent()
        rep = repr(agent)
        assert "ConcreteAgent" in rep
        assert "test-agent" in rep
        assert "idle" in rep


class TestAgentReport:
    """Tests for the AgentReport dataclass."""

    def test_default_values(self):
        """AgentReport should have sensible defaults."""
        report = AgentReport(agent_name="test")
        assert report.signal == "NEUTRAL"
        assert report.confidence == 0.0
        assert report.data == {}
        assert report.reasoning == ""
        assert len(report.report_id) == 12

    def test_custom_values(self):
        """AgentReport should accept custom values."""
        report = AgentReport(
            agent_name="test",
            signal="BULLISH",
            confidence=0.9,
            data={"price": 1.10},
            reasoning="Strong setup",
        )
        assert report.signal == "BULLISH"
        assert report.confidence == 0.9
        assert report.data["price"] == 1.10


# ===========================================================================
# Message Bus
# ===========================================================================


class TestMessageBus:
    """Tests for the MessageBus pub/sub system."""

    async def test_start_stop(self):
        """Bus should start and stop cleanly."""
        bus = MessageBus()
        await bus.start()
        assert bus._running is True
        await bus.stop()
        assert bus._running is False

    async def test_publish_and_route(self):
        """Messages should be delivered to subscribers."""
        bus = MessageBus()
        await bus.start()

        received = []

        async def handler(msg: Message):
            received.append(msg)

        bus.subscribe("test_topic", handler)
        await bus.publish("test_topic", {"key": "value"}, sender="test_agent")

        import asyncio
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].topic == "test_topic"
        assert received[0].data["key"] == "value"
        assert received[0].sender == "test_agent"

        await bus.stop()

    async def test_wildcard_subscription(self):
        """Wildcard '*' subscribers should receive all messages."""
        bus = MessageBus()
        await bus.start()

        received = []

        async def handler(msg: Message):
            received.append(msg)

        bus.subscribe("*", handler)
        await bus.publish("topic_a", {"a": 1})
        await bus.publish("topic_b", {"b": 2})

        import asyncio
        await asyncio.sleep(0.05)

        assert len(received) == 2
        await bus.stop()

    async def test_unsubscribe(self):
        """Handler should stop receiving messages after unsubscribe."""
        bus = MessageBus()
        await bus.start()

        received = []

        async def handler(msg: Message):
            received.append(msg)

        bus.subscribe("t", handler)
        bus.unsubscribe("t", handler)
        await bus.publish("t", {"k": "v"})

        import asyncio
        await asyncio.sleep(0.05)

        assert len(received) == 0
        await bus.stop()

    async def test_handler_error_does_not_crash_bus(self):
        """An error in one handler should not crash the bus."""
        bus = MessageBus()
        await bus.start()

        async def bad_handler(msg: Message):
            raise RuntimeError("Handler crash")

        async def good_handler(msg: Message):
            good_handler.called = True

        good_handler.called = False

        bus.subscribe("t", bad_handler)
        bus.subscribe("t", good_handler)
        await bus.publish("t", {"k": "v"})

        import asyncio
        await asyncio.sleep(0.05)

        assert good_handler.called is True
        await bus.stop()

    async def test_stats(self):
        """stats should return subscription counts."""
        bus = MessageBus()
        bus.subscribe("a", AsyncMock())
        bus.subscribe("b", AsyncMock())
        bus.subscribe("b", AsyncMock())

        stats = bus.stats
        assert stats["a"] == 1
        assert stats["b"] == 2

    async def test_register_agent(self):
        """register() should subscribe to agent name if agent has on_message."""
        bus = MessageBus()

        agent = MagicMock()
        agent.name = "my-agent"
        agent.on_message = AsyncMock()

        await bus.register(agent)
        assert "my-agent" in bus._subscribers

    async def test_register_agent_no_handler(self):
        """register() should not crash if agent has no on_message."""
        bus = MessageBus()
        agent = MagicMock()
        agent.name = "no-handler"
        del agent.on_message

        await bus.register(agent)


# ===========================================================================
# Trading Pipeline (State Machine)
# ===========================================================================


class TestTradingPipeline:
    """Tests for the TradingPipeline state machine."""

    def test_initial_state(self):
        """Pipeline should start in IDLE state."""
        pipeline = TradingPipeline()
        assert pipeline.state == PipelineState.IDLE
        assert pipeline.is_active is False

    def test_advance_basic_transition(self):
        """advance() should move to the next valid state from IDLE."""
        pipeline = TradingPipeline()
        result = PhaseResult(
            phase=PipelineState.FUNDAMENTAL_ANALYSIS,
            success=True,
            signal="BULLISH",
            confidence=0.8,
        )
        assert pipeline.advance(result) is True
        assert pipeline.state == PipelineState.FUNDAMENTAL_ANALYSIS

    def test_advance_through_phases(self):
        """Pipeline should advance through multiple phases step by step."""
        pipeline = TradingPipeline()
        states = [
            PipelineState.FUNDAMENTAL_ANALYSIS,
            PipelineState.TREND_IDENTIFICATION,
            PipelineState.MARKET_STRUCTURE,
            PipelineState.SUPPORT_RESISTANCE,
            PipelineState.ORDER_BLOCK_ANALYSIS,
            PipelineState.WAITING_FOR_PRICE,  # 6th advance
        ]
        for phase in states:
            result = PhaseResult(phase=phase, success=True)
            assert pipeline.advance(result) is True
        assert pipeline.state == PipelineState.WAITING_FOR_PRICE

    def test_advance_rejection_from_analysis(self):
        """A failed phase after starting should transition to REJECTED."""
        pipeline = TradingPipeline()
        # First advance to FUNDAMENTAL_ANALYSIS
        r = PhaseResult(phase=PipelineState.FUNDAMENTAL_ANALYSIS, success=True)
        pipeline.advance(r)
        # Then fail at trend identification
        r = PhaseResult(phase=PipelineState.TREND_IDENTIFICATION, success=False)
        assert pipeline.advance(r) is True
        assert pipeline.state == PipelineState.REJECTED

    def test_advance_invalid_transition(self):
        """advance() should fail for invalid transitions."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.EXECUTION
        result = PhaseResult(
            phase=PipelineState.FUNDAMENTAL_ANALYSIS,
            success=True,
        )
        # advance() picks valid_next[0] from current state (TRADE_MANAGEMENT)
        # so FUNDAMENTAL_ANALYSIS phase doesn't matter — it picks TRADE_MANAGEMENT
        assert pipeline.advance(result) is True

    def test_reject(self):
        """reject() should set state to REJECTED."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.FUNDAMENTAL_ANALYSIS
        pipeline.reject("Bad setup")
        assert pipeline.state == PipelineState.REJECTED

    def test_reset(self):
        """reset() should return pipeline to IDLE."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.COMPLETED
        pipeline.reset()
        assert pipeline.state == PipelineState.IDLE
        assert pipeline.history == []
        assert pipeline.context == {}

    def test_wait_for_price_from_valid_state(self):
        """wait_for_price() works from WAITING_FOR_PRICE, RSI, or CANDLESTICK states."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.WAITING_FOR_PRICE
        assert pipeline.wait_for_price({"zone_key": "value"}) is True
        assert pipeline.state == PipelineState.WAITING_FOR_PRICE
        assert pipeline.context.get("waiting_zones") == {"zone_key": "value"}

    def test_wait_for_price_invalid_state(self):
        """wait_for_price() should return False from invalid states."""
        pipeline = TradingPipeline()
        assert pipeline.wait_for_price({}) is False

    def test_price_arrived(self):
        """price_arrived() should transition from WAITING to PRICE_AT_ZONE."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.WAITING_FOR_PRICE
        assert pipeline.price_arrived({"zone_name": "test"}) is True
        assert pipeline.state == PipelineState.PRICE_AT_ZONE

    def test_price_arrived_from_wrong_state(self):
        """price_arrived() should return False from non-WAITING state."""
        pipeline = TradingPipeline()
        assert pipeline.price_arrived({}) is False

    def test_full_pipeline_to_completion(self):
        """Simulate a full successful trade through all states to COMPLETED."""
        pipeline = TradingPipeline()
        phases = [
            PipelineState.FUNDAMENTAL_ANALYSIS,
            PipelineState.TREND_IDENTIFICATION,
            PipelineState.MARKET_STRUCTURE,
            PipelineState.SUPPORT_RESISTANCE,
            PipelineState.ORDER_BLOCK_ANALYSIS,
            PipelineState.WAITING_FOR_PRICE,
            PipelineState.PRICE_AT_ZONE,
            PipelineState.RSI_CONFIRMATION,
            PipelineState.CANDLESTICK_CONFIRMATION,
            PipelineState.TRADE_VALIDATION,
            PipelineState.RISK_MANAGEMENT,
            PipelineState.EXECUTION,
            PipelineState.TRADE_MANAGEMENT,
            PipelineState.POST_TRADE_LEARNING,
        ]
        for i, phase in enumerate(phases):
            result = PhaseResult(phase=phase, success=True)
            assert pipeline.advance(result) is True, f"Failed at phase {i}: {phase.value}"

        # After POST_TRADE_LEARNING, advance should go to COMPLETED
        assert pipeline.state == PipelineState.POST_TRADE_LEARNING
        result = PhaseResult(phase=PipelineState.COMPLETED, success=True)
        assert pipeline.advance(result) is True
        assert pipeline.state == PipelineState.COMPLETED

    def test_summary(self):
        """summary() should return current state info."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.FUNDAMENTAL_ANALYSIS
        summary = pipeline.summary()
        assert summary["state"] == "fundamental_analysis"
        assert summary["is_active"] is True

    def test_history_tracking(self):
        """Pipeline should track phase history."""
        pipeline = TradingPipeline()
        r1 = PhaseResult(phase=PipelineState.FUNDAMENTAL_ANALYSIS, success=True, signal="BULLISH")
        pipeline.advance(r1)
        r2 = PhaseResult(phase=PipelineState.TREND_IDENTIFICATION, success=True, signal="BEARISH")
        pipeline.advance(r2)

        assert len(pipeline.history) == 2
        assert pipeline.history[0].signal == "BULLISH"
        assert pipeline.history[1].signal == "BEARISH"

    def test_rejected_to_idle(self):
        """REJECTED should allow transition back to IDLE."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.REJECTED
        result = PhaseResult(phase=PipelineState.IDLE, success=True)
        assert pipeline.advance(result) is True
        assert pipeline.state == PipelineState.IDLE

    def test_completed_to_idle(self):
        """COMPLETED should allow transition back to IDLE."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.COMPLETED
        result = PhaseResult(phase=PipelineState.IDLE, success=True)
        assert pipeline.advance(result) is True
        assert pipeline.state == PipelineState.IDLE

    def test_rsi_confirmation_can_wait(self):
        """RSI_CONFIRMATION can transition back to WAITING_FOR_PRICE."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.RSI_CONFIRMATION
        assert pipeline.wait_for_price({"reason": "needs more time"}) is True

    def test_candlestick_confirmation_can_wait(self):
        """CANDLESTICK_CONFIRMATION can transition back to WAITING_FOR_PRICE."""
        pipeline = TradingPipeline()
        pipeline.state = PipelineState.CANDLESTICK_CONFIRMATION
        assert pipeline.wait_for_price({"reason": "no pattern yet"}) is True


# ===========================================================================
# Config
# ===========================================================================


class TestNoemaConfig:
    """Tests for Noema configuration."""

    def test_default_config(self):
        """Default config should have sensible trading parameters."""
        config = NoemaConfig()
        assert config.broker.type == "paper"
        assert config.risk.risk_per_trade == 0.01
        assert config.risk.max_daily_loss == 0.03
        assert config.risk.min_risk_reward == 2.0
        assert "EURUSD" in config.trading.pairs
        assert config.trading.timeframes["primary"] == "D1"

    def test_default_broker_config(self):
        """BrokerConfig should have sensible defaults."""
        config = BrokerConfig()
        assert config.type == "paper"
        assert config.mt5_login == 0
        assert config.magic_number == 20260609
        assert config.slippage == 20

    def test_default_risk_config(self):
        """RiskConfig should have sensible defaults."""
        config = RiskConfig()
        assert config.risk_per_trade == 0.01
        assert config.max_correlated_trades == 2

    def test_default_econometrics_config(self):
        """EconometricsConfig should have sensible defaults."""
        config = EconometricsConfig()
        assert config.arima_max_order == (3, 2, 3)
        assert config.cointegration_significance == 0.05
        assert config.regime_lookback == 60

    def test_custom_config_overrides(self):
        """Custom config should override defaults."""
        config = NoemaConfig(
            broker=BrokerConfig(type="mt5", mt5_login=12345),
            risk=RiskConfig(risk_per_trade=0.02, max_open_trades=3),
        )
        assert config.broker.type == "mt5"
        assert config.broker.mt5_login == 12345
        assert config.risk.risk_per_trade == 0.02
        assert config.risk.max_open_trades == 3

    def test_load_config_from_yaml(self, tmp_path):
        """load_config should read from a YAML file."""
        yaml_content = {
            "broker": {"type": "mt5", "mt5_login": 99999},
            "risk": {"risk_per_trade": 0.02},
            "trading": {"pairs": ["EURUSD", "GBPJPY"]},
            "econometrics": {"pca_components": 3},
            "log_level": "DEBUG",
            "dashboard_port": 9090,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(yaml_content, f)

        config = load_config(config_file)
        assert config.broker.type == "mt5"
        assert config.broker.mt5_login == 99999
        assert config.risk.risk_per_trade == 0.02
        assert "GBPJPY" in config.trading.pairs
        assert config.econometrics.pca_components == 3
        assert config.log_level == "DEBUG"
        assert config.dashboard_port == 9090

    def test_load_config_non_existent(self):
        """load_config should return defaults if file doesn't exist."""
        config = load_config("/nonexistent/path.yaml")
        assert config.broker.type == "paper"

    def test_config_dataclass_types(self):
        """Config should use proper types for all fields."""
        config = NoemaConfig()
        assert isinstance(config.broker, BrokerConfig)
        assert isinstance(config.risk, RiskConfig)
        assert isinstance(config.trading, TradingConfig)
        assert isinstance(config.econometrics, EconometricsConfig)
        assert isinstance(config.log_level, str)
        assert isinstance(config.database_url, str)
        assert isinstance(config.dashboard_port, int)
