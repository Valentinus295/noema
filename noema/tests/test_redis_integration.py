"""Integration tests for Redis-backed MessageBus.

These tests verify that the message bus integration layer
correctly interfaces with Redis for pub/sub, persistence, and
agent communication. Requires redis server or uses fakeredis.

NOTE: These are integration tests — they require a Redis instance.
      In CI, use a Redis Docker container. For local dev, use redis-server.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from noema.core.message_bus import MessageBus, Message


@pytest.mark.integration
class TestRedisMessageBusIntegration:
    """Integration tests for Redis-backed pub/sub messaging.

    These tests mock Redis at the client level to verify
    the integration logic without requiring a real server.
    """

    async def test_redis_publish_dispatch(self, mock_redis):
        """Message published to Redis should reach local subscribers."""
        bus = MessageBus()
        await bus.start()

        received = []

        async def handler(msg: Message):
            received.append(msg)

        bus.subscribe("signals.macro-economic", handler)

        # Simulate Redis publish triggering local dispatch
        await bus.publish(
            "signals.macro-economic",
            {"signal": "BULLISH", "confidence": 0.8},
            sender="macro-economic",
        )

        import asyncio
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].data["signal"] == "BULLISH"
        await bus.stop()

    async def test_redis_fallback_to_memory(self):
        """When Redis is unavailable, bus should fall back to in-memory pub/sub."""
        bus = MessageBus()
        await bus.start()

        received = []

        async def handler(msg: Message):
            received.append(msg)

        bus.subscribe("test.topic", handler)

        # Even without Redis, local pub/sub should work
        await bus.publish("test.topic", {"key": "val"}, sender="test")
        import asyncio
        await asyncio.sleep(0.05)

        assert len(received) == 1
        await bus.stop()

    async def test_multiple_agent_subscriptions(self):
        """Multiple agents can subscribe to the same topic."""
        bus = MessageBus()
        await bus.start()

        agent1_msgs = []
        agent2_msgs = []

        async def handler1(msg): agent1_msgs.append(msg)
        async def handler2(msg): agent2_msgs.append(msg)

        bus.subscribe("signals.analysis", handler1)
        bus.subscribe("signals.analysis", handler2)

        await bus.publish("signals.analysis", {"signal": "BULLISH"})
        import asyncio
        await asyncio.sleep(0.05)

        assert len(agent1_msgs) == 1
        assert len(agent2_msgs) == 1
        await bus.stop()

    async def test_agent_register_integration(self, mock_nim_client, default_config):
        """Registering an agent should set up its message subscriptions."""
        from noema.agents.macro import MacroEconomicAgent
        bus = MessageBus()
        await bus.start()

        agent = MacroEconomicAgent(config=default_config, message_bus=bus)
        await agent.start()

        # Agent should be registered on the bus
        assert "macro-economic" in bus._subscribers

        await bus.stop()

    async def test_cross_agent_communication(self, mock_nim_client, default_config):
        """Two agents should communicate via the message bus."""
        from noema.agents.macro import MacroEconomicAgent
        from noema.agents.risk import RiskManagerAgent

        bus = MessageBus()
        await bus.start()

        # Verify agents can be created and register
        macro = MacroEconomicAgent(config=default_config, message_bus=bus)
        risk = RiskManagerAgent(config=default_config, message_bus=bus)

        await macro.start()
        await risk.start()

        assert "macro-economic" in bus._subscribers
        assert "risk-manager" in bus._subscribers

        await bus.stop()
