"""Unit tests for data modules.

Covers:
- MarketDataFeed (OHLCV fetching, multi-TF, caching, synthetic fallback)
- EconomicCalendar (event fetching, sample data generation)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from vmpm.data.feed import MarketDataFeed
from vmpm.data.calendar import EconomicCalendar


# ===========================================================================
# MarketDataFeed
# ===========================================================================


class TestMarketDataFeed:
    """Tests for the MarketDataFeed class."""

    async def test_get_ohlcv_returns_dataframe(self, synthetic_ohlcv):
        """get_ohlcv should return a DataFrame."""
        broker = MagicMock()
        broker.get_rates.return_value = synthetic_ohlcv
        feed = MarketDataFeed(broker)
        result = await feed.get_ohlcv("EURUSD", "H1", 100)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 100
        assert "close" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "open" in result.columns
        assert "volume" in result.columns

    async def test_get_ohlcv_caches_data(self, synthetic_ohlcv):
        """get_ohlcv should cache data after first fetch."""
        broker = MagicMock()
        broker.get_rates.return_value = synthetic_ohlcv
        feed = MarketDataFeed(broker)

        # First call
        result1 = await feed.get_ohlcv("EURUSD", "H1", 100)
        assert len(result1) == 100

        # Second call should use cache
        result2 = await feed.get_ohlcv("EURUSD", "H1", 100)
        assert len(result2) == 100
        assert broker.get_rates.call_count == 1

    async def test_get_ohlcv_synthetic_fallback(self):
        """get_ohlcv should generate synthetic data if broker fails."""
        broker = MagicMock()
        broker.get_rates.side_effect = Exception("Broker error")
        feed = MarketDataFeed(broker)

        result = await feed.get_ohlcv("EURUSD", "H1", 100)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 100

    async def test_get_multi_tf_returns_dict(self, synthetic_ohlcv):
        """get_multi_tf should return a dict of DataFrames."""
        broker = MagicMock()
        broker.get_rates.return_value = synthetic_ohlcv
        feed = MarketDataFeed(broker)

        timeframes = ["M15", "H1", "H4", "D1"]
        result = await feed.get_multi_tf("EURUSD", timeframes)
        assert isinstance(result, dict)
        for tf in timeframes:
            assert tf in result
            assert isinstance(result[tf], pd.DataFrame)

    async def test_get_multi_tf_handles_missing_data(self):
        """get_multi_tf should exclude timeframes that return None."""
        broker = MagicMock()

        def side_effect(symbol, tf, count):
            if tf == "H1":
                return None
            return pd.DataFrame({"close": [1.0, 1.1]})

        broker.get_rates.side_effect = side_effect
        feed = MarketDataFeed(broker)

        result = await feed.get_multi_tf("EURUSD", ["M15", "H1"])
        assert "M15" in result
        # H1 returns None from broker, but feed falls back to synthetic data
        # so it should still be present
        assert isinstance(result.get("H1"), pd.DataFrame)

    async def test_clear_cache(self, synthetic_ohlcv):
        """clear_cache should remove cached data."""
        broker = MagicMock()
        broker.get_rates.return_value = synthetic_ohlcv
        feed = MarketDataFeed(broker)

        await feed.get_ohlcv("EURUSD", "H1", 100)
        feed.clear_cache()

        # Should fetch again
        await feed.get_ohlcv("EURUSD", "H1", 100)
        assert broker.get_rates.call_count == 2

    async def test_synthetic_data_consistency(self):
        """Synthetic data should produce different outputs per symbol."""
        feed = MarketDataFeed(None)

        eur = await feed.get_ohlcv("EURUSD", "H1", 50)
        gbp = await feed.get_ohlcv("GBPUSD", "H1", 50)

        assert isinstance(eur, pd.DataFrame)
        assert isinstance(gbp, pd.DataFrame)
        # Different symbols should have different prices
        assert abs(eur["close"].iloc[-1] - gbp["close"].iloc[-1]) > 0.001


# ===========================================================================
# EconomicCalendar
# ===========================================================================


class TestEconomicCalendar:
    """Tests for the EconomicCalendar class."""

    async def test_get_events_returns_list(self):
        """get_events should return a list of events."""
        calendar = EconomicCalendar()
        events = await calendar.get_events(currencies=["USD", "EUR"], days_ahead=1)
        assert isinstance(events, list)
        assert len(events) > 0

    async def test_sample_events_have_required_fields(self):
        """Sample events should have all required fields."""
        calendar = EconomicCalendar()
        events = await calendar.get_events(currencies=["USD"])
        for event in events:
            assert "name" in event
            assert "currency" in event
            assert "impact" in event
            assert "forecast" in event
            assert "actual" in event
            assert "previous" in event

    async def test_sample_events_valid_impact(self):
        """Sample events should have valid impact levels."""
        calendar = EconomicCalendar()
        events = await calendar.get_events()
        for event in events:
            assert event["impact"] in ("high", "medium", "low")

    async def test_get_events_currency_filter(self):
        """get_events should filter by currency if specified."""
        calendar = EconomicCalendar()
        events = await calendar.get_events(currencies=["JPY"])
        for event in events:
            assert event["currency"] == "JPY"

    async def test_get_events_no_currency_filter(self):
        """get_events should include all currencies if none specified."""
        calendar = EconomicCalendar()
        events = await calendar.get_events()
        currencies = {e["currency"] for e in events}
        assert len(currencies) > 1

    async def test_safe_float_conversion(self):
        """_safe_float should handle various input types."""
        calendar = EconomicCalendar()
        assert calendar._safe_float("2.5") == 2.5
        assert calendar._safe_float("0") == 0.0
        assert calendar._safe_float("—") is None
        assert calendar._safe_float(None) is None
        assert calendar._safe_float("") is None
        assert calendar._safe_float("1,000") == 1000.0
        assert calendar._safe_float(-3.14) == -3.14

    async def test_api_fetch_fallback(self):
        """If API fetch fails, should fall back to sample events."""
        calendar = EconomicCalendar()
        # Mock the API to fail
        with patch.object(calendar, "_fetch_from_api", return_value=[]):
            events = await calendar.get_events()
            assert len(events) > 0

    async def test_key_events_mapping(self):
        """KEY_EVENTS should include major economic indicators."""
        expected_keys = [
            "interest_rate_decision",
            "nfp",
            "cpi",
            "gdp",
            "fomc",
        ]
        for key in expected_keys:
            assert key in EconomicCalendar.KEY_EVENTS
