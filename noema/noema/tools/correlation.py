"""
Correlation Tool — check forex pair correlations.

Provides correlation analysis between currency pairs:
- Rolling Pearson correlation coefficients
- Correlation matrix for configured pairs
- Risk warnings for highly correlated positions

Inspired by TradingAgents' approach of giving agents real data tools
rather than relying on training-data knowledge of correlations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

from noema.tools import ToolDef

logger = logging.getLogger(__name__)


def get_currency_correlation(
    base_pair: str,
    lookback_bars: int = 100,
    timeframe: str = "H1",
) -> dict[str, Any]:
    """Calculate correlation between a base pair and other major pairs.

    Args:
        base_pair: Primary pair to correlate against (e.g., "EURUSD")
        lookback_bars: Number of bars to use for correlation calculation
        timeframe: Bar timeframe for correlation

    Returns:
        dict with correlation coefficients and risk assessment

    Example:
        >>> get_currency_correlation("EURUSD")
        {
            "base_pair": "EURUSD",
            "correlations": {
                "GBPUSD": 0.82,
                "USDCHF": -0.91,
                ...
            },
            "highly_correlated": ["GBPUSD"],
            "inversely_correlated": ["USDCHF"],
            "risk_warning": "EURUSD positions correlate with GBPUSD (0.82) — avoid doubling exposure"
        }
    """
    correlations: dict[str, float] = {}
    source = "none"

    # Default pairs to check (major FX pairs)
    check_pairs = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
        "USDCAD", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
    ]

    # Remove base pair from check list
    if base_pair in check_pairs:
        check_pairs.remove(base_pair)

    # --- Try MT5 ---
    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5()
        if mt5.initialize():
            # Timeframe mapping
            tf_map = {
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
                "M15": mt5.TIMEFRAME_M15,
            }
            mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_H1)

            # Fetch base pair data
            base_rates = mt5.copy_rates_from_pos(base_pair, mt5_tf, 0, lookback_bars)
            if base_rates is None or len(base_rates) < 20:
                mt5.shutdown()
                return {
                    "base_pair": base_pair,
                    "error": f"Insufficient data for {base_pair}",
                    "correlations": {},
                }

            # Extract closes
            base_closes = np.array([float(r.close) for r in base_rates])
            # Use returns for correlation
            base_returns = np.diff(np.log(base_closes))

            for pair in check_pairs:
                try:
                    pair_rates = mt5.copy_rates_from_pos(pair, mt5_tf, 0, lookback_bars)
                    if pair_rates is None or len(pair_rates) < 20:
                        continue

                    pair_closes = np.array([float(r.close) for r in pair_rates])
                    pair_returns = np.diff(np.log(pair_closes))

                    # Calculate Pearson correlation of returns
                    min_len = min(len(base_returns), len(pair_returns))
                    if min_len < 10:
                        continue

                    corr = float(np.corrcoef(base_returns[:min_len], pair_returns[:min_len])[0, 1])
                    if not np.isnan(corr):
                        correlations[pair] = round(corr, 3)
                except Exception:
                    continue

            mt5.shutdown()
            source = "mt5"
    except ImportError:
        logger.debug("MT5 not available for correlation")
    except Exception as e:
        logger.warning(f"Correlation calculation failed: {e}")

    # --- Compute risk assessment ---
    highly_correlated = [
        p for p, c in correlations.items() if abs(c) > 0.7 and p != base_pair
    ]
    inversely_correlated = [
        p for p, c in correlations.items() if c < -0.7
    ]

    risk_warning = ""
    if highly_correlated:
        risk_warning = (
            f"{base_pair} positions correlate strongly with {', '.join(highly_correlated[:3])} "
            f"— avoid doubling directional exposure"
        )
    if inversely_correlated:
        risk_warning += (
            f" | Inverse correlation with {', '.join(inversely_correlated[:3])}"
        )

    return {
        "base_pair": base_pair,
        "correlations": correlations,
        "highly_correlated": highly_correlated,
        "inversely_correlated": inversely_correlated,
        "risk_warning": risk_warning.strip(),
        "timeframe": timeframe,
        "bars_used": lookback_bars,
        "source": source,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def get_correlation_matrix(
    pairs: list[str] | None = None,
    lookback_bars: int = 100,
    timeframe: str = "H1",
) -> dict[str, Any]:
    """Calculate a full correlation matrix for a set of pairs.

    Args:
        pairs: List of pairs (default: major FX pairs)
        lookback_bars: Number of bars for calculation
        timeframe: Bar timeframe

    Returns:
        dict with matrix and clustering
    """
    if pairs is None:
        pairs = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]

    matrix: dict[str, dict[str, float]] = {}
    pair_data: dict[str, np.ndarray] = {}

    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5()
        if mt5.initialize():
            tf_map = {"H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
            mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_H1)

            # Fetch all pair data
            for pair in pairs:
                rates = mt5.copy_rates_from_pos(pair, mt5_tf, 0, lookback_bars)
                if rates is not None and len(rates) >= 20:
                    closes = np.array([float(r.close) for r in rates])
                    pair_data[pair] = np.diff(np.log(closes))

            mt5.shutdown()

        # Build correlation matrix from returns
        available = list(pair_data.keys())
        for p1 in available:
            matrix[p1] = {}
            for p2 in available:
                if p1 == p2:
                    matrix[p1][p2] = 1.0
                else:
                    r1 = pair_data[p1]
                    r2 = pair_data[p2]
                    min_len = min(len(r1), len(r2))
                    if min_len >= 10:
                        matrix[p1][p2] = round(float(np.corrcoef(r1[:min_len], r2[:min_len])[0, 1]), 3)
                    else:
                        matrix[p1][p2] = 0.0

    except Exception as e:
        logger.warning(f"Correlation matrix failed: {e}")

    return {
        "pairs": available if 'available' in dir() else pairs,
        "matrix": matrix,
        "timeframe": timeframe,
        "bars_used": lookback_bars,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── ToolDefs for registration ──────────────────────────────────────────

correlation_tool = ToolDef(
    name="get_currency_correlation",
    description=(
        "Calculate correlation between a currency pair and other major pairs. "
        "Returns Pearson correlation coefficients, identifies highly correlated "
        "and inversely correlated pairs, and provides a risk warning. "
        "Use this to check if opening a position would double your directional "
        "exposure or if you should consider pair diversification."
    ),
    func=get_currency_correlation,
    parameters={
        "base_pair": {
            "type": "string",
            "description": "Primary currency pair to check (e.g., EURUSD, GBPJPY)",
        },
        "lookback_bars": {
            "type": "integer",
            "description": "Number of bars for correlation calculation (default: 100)",
        },
        "timeframe": {
            "type": "string",
            "enum": ["H1", "H4", "D1", "M15"],
            "description": "Timeframe for correlation (default: H1)",
        },
    },
    tags=["correlation", "risk", "portfolio", "diversification"],
    category="risk",
    requires_broker=True,
)

correlation_matrix_tool = ToolDef(
    name="get_correlation_matrix",
    description=(
        "Calculate the full correlation matrix for a set of currency pairs. "
        "Returns a dictionary of pair-to-pair correlation coefficients. "
        "Use this for portfolio-level risk assessment and position sizing decisions."
    ),
    func=get_correlation_matrix,
    parameters={
        "pairs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of pairs (default: major FX pairs)",
        },
        "lookback_bars": {
            "type": "integer",
            "description": "Number of bars for calculation (default: 100)",
        },
        "timeframe": {
            "type": "string",
            "enum": ["H1", "H4", "D1"],
            "description": "Timeframe (default: H1)",
        },
    },
    tags=["correlation", "matrix", "portfolio", "risk"],
    category="risk",
    requires_broker=True,
)
