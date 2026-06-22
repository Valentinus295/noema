"""
Market Data Tool — fetch current and historical OHLCV data.

Provides verified market data from the broker (MT5) or configured data source.
Inspired by TradingAgents' get_verified_market_snapshot — a deterministic
ground truth that prevents LLM confabulation of exact price values.

Key pattern: Before making any exact price claim, agents should call
get_verified_broker_snapshot. The returned data is treated as the source
of truth for OHLCV, indicator values, and price levels.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from noema.tools import ToolDef

logger = logging.getLogger(__name__)


def get_market_data(
    symbol: str,
    timeframe: str = "H1",
    count: int = 200,
) -> dict[str, Any]:
    """Fetch OHLCV bars for a symbol from the configured broker.

    Args:
        symbol: Trading symbol in MT5 format (EURUSD, GBPJPY, etc.)
        timeframe: Bar timeframe (M1, M5, M15, M30, H1, H4, D1, W1, MN)
        count: Number of bars to retrieve (max 5000)

    Returns:
        dict with 'bars' array and metadata

    Example:
        >>> get_market_data("EURUSD", "H1", 100)
        {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "current_price": 1.0856,
            "bars": [
                {"time": "2026-06-23T01:00:00Z", "open": 1.0850, ...},
                ...
            ],
            "bar_count": 100,
            "source": "mt5"
        }
    """
    bars: list[dict[str, Any]] = []
    source = "none"
    current_price = 0.0

    # --- Try MT5 broker ---
    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5()
        if mt5.initialize():
            tf_map = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
                "W1": mt5.TIMEFRAME_W1,
                "MN": mt5.TIMEFRAME_MN,
            }
            mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_H1)
            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
            if rates is not None and len(rates) > 0:
                for rate in rates:
                    bars.append({
                        "time": str(rate.time),
                        "open": float(rate.open),
                        "high": float(rate.high),
                        "low": float(rate.low),
                        "close": float(rate.close),
                        "tick_volume": int(rate.tick_volume),
                    })
                current_price = bars[-1]["close"]
                source = "mt5"
            mt5.shutdown()
    except ImportError:
        logger.debug("MT5 not available for market data")
    except Exception as e:
        logger.warning(f"MT5 market data fetch failed: {e}")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": current_price,
        "bars": bars,
        "bar_count": len(bars),
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_verified_broker_snapshot(
    symbol: str,
    look_back_bars: int = 30,
) -> dict[str, Any]:
    """Get a deterministic snapshot of current market state for a symbol.

    This is THE source of truth for exact price, OHLCV, and indicator values.
    Inspired by TradingAgents' get_verified_market_snapshot — agents MUST
    call this before making exact price claims to prevent hallucination.

    Args:
        symbol: Trading symbol (EURUSD, GBPJPY, etc.)
        look_back_bars: Number of recent bars to include

    Returns:
        Verified OHLCV data with common indicators
    """
    data = get_market_data(symbol, "H1", look_back_bars)

    if not data["bars"]:
        return {
            "symbol": symbol,
            "error": "No data available from broker",
            "verified": False,
        }

    bars = data["bars"]
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    # ── Compute basic indicators deterministically ────────────────
    n = len(closes)

    # SMA
    sma20 = sum(closes[-20:]) / min(20, n) if n >= 20 else sum(closes) / n
    sma50 = sum(closes[-50:]) / min(50, n) if n >= 50 else None

    # Current vs SMA
    current = closes[-1]
    vs_sma20 = round((current - sma20) / sma20 * 100, 2) if sma20 else None

    # RSI (14-period)
    rsi = _compute_rsi(closes, 14) if n >= 15 else None

    # Recent volatility (ATR approximation — H1 range average)
    ranges = [highs[i] - lows[i] for i in range(max(0, n - 14), n)]
    avg_range = sum(ranges) / len(ranges) if ranges else 0

    # Price position (where current is within recent range)
    recent_high = max(highs[-look_back_bars:])
    recent_low = min(lows[-look_back_bars:])
    price_position_pct = (
        (current - recent_low) / (recent_high - recent_low) * 100
        if recent_high != recent_low
        else 50
    )

    return {
        "symbol": symbol,
        "verified": True,
        "current_price": current,
        "sma20": round(sma20, 5) if sma20 else None,
        "sma50": round(sma50, 5) if sma50 else None,
        "vs_sma20_pct": vs_sma20,
        "rsi_14": round(rsi, 1) if rsi else None,
        "avg_range_pips": round(avg_range * 10000, 1),  # Pips for FX
        "price_position_pct": round(price_position_pct, 1),
        "recent_high": recent_high,
        "recent_low": recent_low,
        "last_bar": {
            "time": bars[-1]["time"],
            "open": bars[-1]["open"],
            "high": bars[-1]["high"],
            "low": bars[-1]["low"],
            "close": bars[-1]["close"],
        },
        "source": data["source"],
        "fetched_at": data["fetched_at"],
    }


def _compute_rsi(closes: list[float], period: int = 14) -> float:
    """Deterministic RSI computation — no reliance on TA-Lib."""
    if len(closes) < period + 1:
        return 50.0  # Neutral fallback

    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ── ToolDefs for registration ──────────────────────────────────────────

market_data_tool = ToolDef(
    name="get_market_data",
    description=(
        "Fetch OHLCV bars for a trading symbol from the broker. "
        "Returns open, high, low, close, and tick volume for each bar. "
        "Use this to get current price data before making any trading decision."
    ),
    func=get_market_data,
    parameters={
        "symbol": {
            "type": "string",
            "description": "Trading symbol in MT5 format (EURUSD, GBPJPY, USDJPY, etc.)",
        },
        "timeframe": {
            "type": "string",
            "enum": ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"],
            "description": "Bar timeframe (default: H1)",
        },
        "count": {
            "type": "integer",
            "description": "Number of bars to retrieve (max 5000, default: 200)",
        },
    },
    tags=["market", "ohlcv", "price", "bars"],
    category="market_data",
    requires_broker=True,
)

verified_snapshot_tool = ToolDef(
    name="get_verified_broker_snapshot",
    description=(
        "Get a DETERMINISTIC verified snapshot of current market state. "
        "This is the SOURCE OF TRUTH for exact OHLCV values and price levels. "
        "ALWAYS call this before making exact price claims in your analysis. "
        "Returns current price, SMA values, RSI, average range, and price position. "
        "If you receive conflicting data from another source, this snapshot takes precedence."
    ),
    func=get_verified_broker_snapshot,
    parameters={
        "symbol": {
            "type": "string",
            "description": "Trading symbol (EURUSD, GBPJPY, etc.)",
        },
        "look_back_bars": {
            "type": "integer",
            "description": "Number of recent bars to include for calculations (default: 30)",
        },
    },
    tags=["market", "verified", "truth", "snapshot"],
    category="market_data",
    requires_broker=True,
)
