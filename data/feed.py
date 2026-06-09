"""Market data feed for VMPM.

Fetches OHLCV data from MT5 or generates synthetic data for paper trading.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


class MarketDataFeed:
    """Provides market data to all agents.

    Supports MT5 real data and synthetic data for paper trading.
    """

    def __init__(self, broker: Any = None) -> None:
        self.broker = broker
        self._cache: dict[str, pd.DataFrame] = {}
        self._logger = logger.bind(component="data_feed")

    async def get_ohlcv(
        self, symbol: str, timeframe: str, count: int = 200
    ) -> pd.DataFrame | None:
        """Get OHLCV data for a symbol and timeframe.

        Tries broker first, falls back to synthetic data.
        """
        cache_key = f"{symbol}_{timeframe}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        # Try broker
        if self.broker:
            try:
                df = self.broker.get_rates(symbol, timeframe, count)
                if df is not None and len(df) > 0:
                    self._cache[cache_key] = df
                    return df
            except Exception as exc:
                self._logger.warning("broker_fetch_failed", error=str(exc))

        # Fallback: synthetic data
        df = self._generate_synthetic(symbol, timeframe, count)
        self._cache[cache_key] = df
        return df

    async def get_multi_tf(
        self, symbol: str, timeframes: list[str], count: int = 200
    ) -> dict[str, pd.DataFrame]:
        """Get data for multiple timeframes."""
        result = {}
        for tf in timeframes:
            df = await self.get_ohlcv(symbol, tf, count)
            if df is not None:
                result[tf] = df
        return result

    def clear_cache(self) -> None:
        self._cache.clear()

    def _generate_synthetic(
        self, symbol: str, timeframe: str, count: int
    ) -> pd.DataFrame:
        """Generate realistic synthetic OHLCV data for testing."""
        # Seed based on symbol for consistency
        seed = sum(ord(c) for c in symbol)
        rng = np.random.RandomState(seed)

        # Base price varies by pair
        base_prices = {
            "EURUSD": 1.10, "GBPUSD": 1.27, "USDJPY": 149.0,
            "USDCHF": 0.88, "AUDUSD": 0.66, "NZDUSD": 0.61,
            "USDCAD": 1.36,
        }
        base = base_prices.get(symbol, 1.0)

        # Generate price path with mean reversion and trend
        returns = rng.randn(count) * 0.0005
        # Add slight trend
        trend = np.sin(np.linspace(0, 4 * np.pi, count)) * 0.0001
        returns += trend

        close = base + np.cumsum(returns)

        # OHLC from close
        spread = abs(rng.randn(count)) * 0.0002
        high = close + spread
        low = close - spread
        open_ = close + rng.randn(count) * 0.0001

        # Ensure OHLC consistency
        high = np.maximum(high, np.maximum(open_, close))
        low = np.minimum(low, np.minimum(open_, close))

        # Time index
        freq_map = {
            "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
            "H1": "1h", "H4": "4h", "D1": "1D", "W1": "1W", "MN1": "1ME",
        }
        freq = freq_map.get(timeframe, "1h")

        df = pd.DataFrame({
            "time": pd.date_range(end=pd.Timestamp.now(), periods=count, freq=freq),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.randint(50, 500, count).astype(float),
        })

        self._logger.debug("synthetic_data_generated", symbol=symbol, timeframe=timeframe, count=count)
        return df
