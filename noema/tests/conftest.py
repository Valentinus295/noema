"""Shared fixtures and helpers for Noema test suite.

Provides mock objects, synthetic data, and configuration fixtures
for all test modules. All external dependencies (MT5, Redis, NIM, DB)
are mocked — tests should never require live infrastructure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from noema.core.settings import Settings, BrokerConfig, RiskConfig, TradingConfig


# ===========================================================================
# pytest markers registration (declarative — see pyproject.toml for config)
# ===========================================================================


# ===========================================================================
# Fixtures: Configuration
# ===========================================================================


@pytest.fixture
def default_config() -> Settings:
    """Return a default Settings object for testing.

    Uses RiskConfig field names that match the actual model:
      risk_per_trade, max_daily_loss, max_weekly_loss, min_risk_reward, max_open_trades.
    """
    return Settings(
        broker=BrokerConfig(type="paper"),
        risk=RiskConfig(
            risk_per_trade=0.01,
            risk_pct_per_trade=0.01,
            max_daily_loss=0.03,
            max_weekly_loss=0.08,
            min_risk_reward=2.0,
            max_open_trades=5,
            max_concurrent_positions=5,
        ),
        trading=TradingConfig(
            pairs=["EURUSD", "GBPUSD"],
            timeframes={
                "primary": "D1", "secondary": "H4", "entry": "H1", "confirmation": "M15",
            },
        ),
    )


# ===========================================================================
# Fixtures: Mock External Dependencies
# ===========================================================================


@pytest.fixture
def mock_message_bus():
    """A mock message bus that doesn't start background tasks."""
    from noema.core.message_bus import MessageBus

    class MockMessageBus(MessageBus):
        """Mock bus with in-memory delivery — no asyncio tasks."""

        async def start(self):
            self._running = True

        async def stop(self):
            self._running = False

        async def _run_loop(self) -> None:
            """No-op — don't spin up a background task."""
            pass

    bus = MockMessageBus()
    return bus


@pytest.fixture
def mock_broker():
    """Mock PaperBroker for agent tests that need a broker."""
    broker = MagicMock()
    broker.place_order = MagicMock(return_value=MagicMock(success=True, ticket=100001, volume=0.1))
    broker.close_position = MagicMock(return_value=True)
    broker.modify_position = MagicMock(return_value=True)
    broker.get_tick = MagicMock(return_value={"bid": 1.1000, "ask": 1.1002})
    broker.get_open_positions = MagicMock(return_value=[])
    return broker


@pytest.fixture
def mock_nim_client():
    """Mock NIMClient — avoids real LLM API calls."""
    client = AsyncMock()
    client.chat_completion = AsyncMock(return_value=MagicMock(
        signal="BULLISH", confidence=0.7, data={}, reasoning="Mock NIM response",
    ))
    return client


@pytest.fixture
def mock_redis():
    """Mock Redis client for message bus integration tests."""
    redis = MagicMock()
    redis.publish = AsyncMock()
    redis.subscribe = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    return redis


# ===========================================================================
# Fixtures: Synthetic OHLCV Data
# ===========================================================================


@pytest.fixture(scope="session")
def synthetic_ohlcv() -> pd.DataFrame:
    """Generate deterministic synthetic OHLCV data (100 candles, hourly).

    Scope=session: reused across all tests that don't mutate it.
    """
    rng = np.random.RandomState(42)
    close = 1.1000 + np.cumsum(rng.randn(100) * 0.0005)
    open_ = close + rng.randn(100) * 0.0001
    high = close + abs(rng.randn(100) * 0.0003)
    low = close - abs(rng.randn(100) * 0.0003)

    # Enforce OHLC consistency
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    return pd.DataFrame({
        "time": pd.date_range(end=pd.Timestamp.now(), periods=100, freq="1h"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.randint(50, 500, 100).astype(float),
    })


@pytest.fixture
def synthetic_multi_tf(synthetic_ohlcv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return a multi-timeframe price dictionary for testing."""
    return {
        "EURUSD": synthetic_ohlcv,
        "M15": synthetic_ohlcv,
        "H1": synthetic_ohlcv,
        "H4": synthetic_ohlcv,
        "D1": synthetic_ohlcv,
        "W1": synthetic_ohlcv,
        "MN1": synthetic_ohlcv,
    }


# ===========================================================================
# Fixtures: Context Dictionaries for Agent Tests
# ===========================================================================


@pytest.fixture
def agent_context(synthetic_multi_tf: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Standard context dict for agent tests."""
    return {
        "pair": "EURUSD",
        "prices": synthetic_multi_tf,
        "price_data": synthetic_multi_tf["H1"],
        "economic_events": [
            {"name": "CPI", "currency": "USD", "impact": "high",
             "forecast": 2.5, "actual": 2.8, "previous": 2.4},
            {"name": "GDP", "currency": "EUR", "impact": "high",
             "forecast": 0.3, "actual": 0.2, "previous": 0.4},
        ],
        "account_balance": 10000.0,
        "daily_pnl": 0.0,
        "weekly_pnl": 0.0,
        "open_trades": 0,
        "open_positions": [],
        "trade_history": [],
    }


@pytest.fixture
def buy_zones() -> list[dict[str, Any]]:
    """Sample buy zones for SR/opportunity tests."""
    return [
        {"name": "Daily Low", "level": 1.0950, "tf": "D1"},
        {"name": "Weekly Low", "level": 1.0900, "tf": "W1"},
    ]


@pytest.fixture
def sell_zones() -> list[dict[str, Any]]:
    """Sample sell zones for SR/opportunity tests."""
    return [
        {"name": "Daily High", "level": 1.1050, "tf": "D1"},
        {"name": "Weekly High", "level": 1.1100, "tf": "W1"},
    ]


@pytest.fixture
def order_blocks() -> list[dict[str, Any]]:
    """Sample order blocks for institutional/opportunity tests."""
    return [
        {"type": "bullish", "midpoint": 1.0970, "strength": 0.7},
        {"type": "bearish", "midpoint": 1.1080, "strength": 0.6},
    ]


@pytest.fixture
def agent_reports() -> dict[str, dict[str, Any]]:
    """Sample agent reports for decision agent tests."""
    return {
        "macro-economic": {"signal": "BULLISH", "confidence": 0.7, "data": {}},
        "market-structure": {"signal": "BULLISH", "confidence": 0.6, "data": {}},
        "support-resistance": {"signal": "BULLISH", "confidence": 0.5, "data": {}},
        "institutional-footprint": {"signal": "BULLISH", "confidence": 0.8, "data": {}},
        "momentum": {"signal": "NEUTRAL", "confidence": 0.4, "data": {}},
        "price-action": {"signal": "BULLISH", "confidence": 0.7, "data": {}},
        "session-intelligence": {
            "signal": "BULLISH", "confidence": 0.6,
            "data": {"is_low_probability": False},
        },
        "opportunity-surveillance": {
            "signal": "BULLISH", "confidence": 0.7,
            "data": {"count": 3},
        },
        "trade-thesis": {"signal": "BULLISH", "confidence": 0.65},
        "risk-manager": {"signal": "APPROVE", "confidence": 0.9},
    }
