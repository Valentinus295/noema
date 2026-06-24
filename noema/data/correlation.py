"""Real-time correlation matrix for multi-symbol forex trading.

Phase 3 component. Builds on the Phase 1 multivariate module (PCA) and
the existing correlation tool (noema/tools/correlation.py) to provide:
- Real-time rolling correlation matrix across all traded pairs
- Anti-correlation detection → avoid opposing bets on highly inverse pairs
- Basket trading awareness: correlated pairs move together → size accordingly
- Currency-level exposure analysis (don't double-bet USD)
- PCA-based factor decomposition from Phase 1 statistics layer

Usage:
    matrix = CorrelationMatrix(pairs=["EURUSD", "GBPUSD", "USDJPY", ...])
    report = matrix.analyze()
    # report.exposure_by_currency → {"USD": 0.75, "EUR": 0.25, ...}
    # report.anti_correlated_pairs → [("EURUSD", "USDCHF"), ...]
    # report.basket_recommendations → "Reduce USD exposure..."

PURE MATH: All calculations are deterministic. No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog
from scipy import stats as scipy_stats

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# Pair-to-Currency Mapping
# ═══════════════════════════════════════════════════

# Standard FX pair → constituent currencies
PAIR_CURRENCIES: dict[str, tuple[str, str]] = {
    "EURUSD": ("EUR", "USD"), "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"), "USDCHF": ("USD", "CHF"),
    "AUDUSD": ("AUD", "USD"), "NZDUSD": ("NZD", "USD"),
    "USDCAD": ("USD", "CAD"), "EURJPY": ("EUR", "JPY"),
    "EURGBP": ("EUR", "GBP"), "EURCHF": ("EUR", "CHF"),
    "GBPJPY": ("GBP", "JPY"), "GBPCHF": ("GBP", "CHF"),
    "AUDJPY": ("AUD", "JPY"), "NZDJPY": ("NZD", "JPY"),
    "CADJPY": ("CAD", "JPY"), "EURAUD": ("EUR", "AUD"),
    "EURNZD": ("EUR", "NZD"), "EURCAD": ("EUR", "CAD"),
    "GBPAUD": ("GBP", "AUD"), "GBPNZD": ("GBP", "NZD"),
    "GBPCAD": ("GBP", "CAD"), "AUDCHF": ("AUD", "CHF"),
    "AUDNZD": ("AUD", "NZD"), "NZDCAD": ("NZD", "CAD"),
    "XAUUSD": ("XAU", "USD"), "XAGUSD": ("XAG", "USD"),
}


# USD-correlated pairs that share directional exposure
USD_PAIRS_BUY_USD = {"USDJPY", "USDCHF", "USDCAD"}  # Buy = USD strengthens
USD_PAIRS_SELL_USD = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "XAUUSD", "XAGUSD"}  # Buy = USD weakens


@dataclass
class CorrelationAnalysis:
    """Complete correlation analysis for a set of trading pairs.

    Attributes:
        matrix: Pair-to-pair correlation coefficients (labeled).
        pair_names: Ordered list of pair names matching matrix indices.
        anti_correlated_pairs: Pairs with correlation < -0.7 (avoid opposing bets).
        highly_correlated_pairs: Pairs with correlation > 0.7 (risk aggregation).
        exposure_by_currency: Net directional exposure per currency (0.0-1.0).
        usd_exposure: Aggregate USD exposure (warning > 0.5).
        basket_recommendations: Human-readable risk advisory.
        pca_explained_variance: PCA first component variance ratio.
        computed_at: ISO-8601 timestamp.
        data_quality: "high" | "medium" | "low" based on data available.
    """
    matrix: np.ndarray = field(default_factory=lambda: np.array([]))
    pair_names: list[str] = field(default_factory=list)
    anti_correlated_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    highly_correlated_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    exposure_by_currency: dict[str, float] = field(default_factory=dict)
    usd_exposure: float = 0.0
    basket_recommendations: list[str] = field(default_factory=list)
    pca_explained_variance: float = 0.0
    computed_at: str = ""
    data_quality: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_names": self.pair_names,
            "matrix": self.matrix.tolist() if self.matrix.size > 0 else [],
            "anti_correlated_pairs": [
                {"pair_a": a, "pair_b": b, "correlation": c}
                for a, b, c in self.anti_correlated_pairs
            ],
            "highly_correlated_pairs": [
                {"pair_a": a, "pair_b": b, "correlation": c}
                for a, b, c in self.highly_correlated_pairs
            ],
            "exposure_by_currency": self.exposure_by_currency,
            "usd_exposure": self.usd_exposure,
            "basket_recommendations": self.basket_recommendations,
            "pca_explained_variance": self.pca_explained_variance,
            "computed_at": self.computed_at,
            "data_quality": self.data_quality,
        }


class CorrelationMatrix:
    """Real-time correlation matrix for multi-symbol forex trading.

    Computes pair-level and currency-level correlations to prevent:
    1. Doubling directional exposure on highly correlated pairs
    2. Opening opposing bets on inversely correlated pairs
    3. Excessive exposure to a single currency (e.g., USD)

    Data source agnostic: accepts numpy arrays (from any broker/feed).
    Uses the Phase 1 multivariate module for PCA decomposition.
    """

    # Thresholds
    HIGH_CORR_THRESHOLD = 0.70       # Above this = highly correlated
    ANTI_CORR_THRESHOLD = -0.70      # Below this = inversely correlated
    USD_EXPOSURE_WARN = 0.60          # USD exposure warning
    USD_EXPOSURE_CRITICAL = 0.80      # USD exposure critical
    MIN_BARS_FOR_COMPUTE = 20         # Minimum bars for reliable correlation

    def __init__(
        self,
        pairs: list[str] | None = None,
        lookback_bars: int = 100,
        use_log_returns: bool = True,
    ):
        """Initialize the correlation matrix.

        Args:
            pairs: List of trading pairs. Default: major FX pairs.
            lookback_bars: Bars for rolling correlation window.
            use_log_returns: Use log returns instead of raw prices.
        """
        self.pairs = pairs or [
            "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
        ]
        self.lookback_bars = lookback_bars
        self.use_log_returns = use_log_returns
        self._price_cache: dict[str, np.ndarray] = {}
        self._logger = logger.bind(component="correlation_matrix")

    def feed_prices(self, pair: str, closes: np.ndarray | list[float]) -> None:
        """Feed price data for a pair into the correlation cache.

        Args:
            pair: Pair name (e.g., "EURUSD").
            closes: Array of closing prices (most recent last).
        """
        data = np.asarray(closes, dtype=float)
        if len(data) >= self.MIN_BARS_FOR_COMPUTE:
            self._price_cache[pair] = data[-self.lookback_bars:]
        else:
            self._logger.warning("insufficient_data", pair=pair, bars=len(data))

    def feed_bars(self, pair: str, bars: list[dict[str, Any]]) -> None:
        """Feed bar data (OHLCV dicts) into the correlation cache.

        Args:
            pair: Pair name.
            bars: List of OHLCV dicts, each with 'close' key.
        """
        if not bars:
            return
        closes = [float(b["close"]) for b in bars if "close" in b]
        if len(closes) >= self.MIN_BARS_FOR_COMPUTE:
            self._price_cache[pair] = np.array(closes[-self.lookback_bars:], dtype=float)
        elif closes:
            self._price_cache[pair] = np.array(closes, dtype=float)

    async def feed_from_broker(
        self,
        broker: Any,
        timeframe: str = "H1",
    ) -> int:
        """Feed all pairs from a broker connection.

        Args:
            broker: Broker instance with get_candles() or get_rates() method.
            timeframe: Bar timeframe (H1, H4, D1).

        Returns:
            Number of pairs successfully loaded.
        """
        import asyncio
        count = 0
        for pair in self.pairs:
            try:
                bars = await self._get_bars(broker, pair, timeframe, self.lookback_bars)
                if bars:
                    self.feed_bars(pair, bars)
                    count += 1
            except Exception as e:
                self._logger.warning("broker_feed_failed", pair=pair, error=str(e))
        return count

    async def _get_bars(
        self, broker: Any, symbol: str, timeframe: str, count: int
    ) -> list[dict] | None:
        """Fetch bars from a broker — mirrors ModernOrchestrator._get_bars pattern."""
        if hasattr(broker, 'bars') and callable(broker.bars):
            try:
                result = await broker.bars(symbol, timeframe, count)
                if result:
                    return list(result)
            except Exception:
                pass
        if hasattr(broker, 'get_candles') and callable(broker.get_candles):
            try:
                result = await __import__('asyncio').to_thread(
                    broker.get_candles, symbol, timeframe, count
                )
                if result:
                    return list(result)
            except Exception:
                pass
        if hasattr(broker, 'get_rates') and callable(broker.get_rates):
            try:
                result = await __import__('asyncio').to_thread(
                    broker.get_rates, symbol, timeframe, count
                )
                if result is not None:
                    if hasattr(result, 'to_dict'):
                        return result.to_dict('records')
                    if isinstance(result, list):
                        return result
            except Exception:
                pass
        return None

    def analyze(self) -> CorrelationAnalysis:
        """Run full correlation analysis on all cached pairs.

        Computes:
        - Pair correlation matrix (Pearson on log returns)
        - Anti-correlated pairs
        - Highly correlated pairs
        - Currency-level USD exposure
        - PCA explained variance
        - Basket risk recommendations

        Returns:
            CorrelationAnalysis with full results.
        """
        if len(self._price_cache) < 2:
            return CorrelationAnalysis(
                pair_names=list(self._price_cache.keys()),
                computed_at=datetime.now(timezone.utc).isoformat(),
                data_quality="low",
                basket_recommendations=["Insufficient data — need ≥2 pairs with ≥20 bars each."],
            )

        # ── Step 1: Build returns matrix ──
        available_pairs = []
        returns_matrix = []

        for pair in self.pairs:
            if pair in self._price_cache:
                closes = self._price_cache[pair]
                if len(closes) >= self.MIN_BARS_FOR_COMPUTE:
                    if self.use_log_returns:
                        returns = np.diff(np.log(closes))
                    else:
                        returns = np.diff(closes) / closes[:-1]
                    available_pairs.append(pair)
                    returns_matrix.append(returns)

        if len(available_pairs) < 2:
            return CorrelationAnalysis(
                pair_names=available_pairs,
                computed_at=datetime.now(timezone.utc).isoformat(),
                data_quality="low",
                basket_recommendations=["Insufficient data — need ≥2 valid pairs."],
            )

        # ── Step 2: Align lengths (trim to shortest) ──
        min_len = min(len(r) for r in returns_matrix)
        aligned = []
        for r in returns_matrix:
            aligned.append(r[-min_len:])
        returns_array = np.column_stack(aligned)  # (min_len, n_pairs)

        # ── Step 3: Compute correlation matrix ──
        n_pairs = len(available_pairs)
        corr_matrix = np.zeros((n_pairs, n_pairs))

        for i in range(n_pairs):
            corr_matrix[i, i] = 1.0
            for j in range(i + 1, n_pairs):
                r, _ = scipy_stats.pearsonr(returns_array[:, i], returns_array[:, j])
                corr_matrix[i, j] = corr_matrix[j, i] = round(float(r), 4)

        # ── Step 4: Detect highly correlated & anti-correlated pairs ──
        anti_corr: list[tuple[str, str, float]] = []
        high_corr: list[tuple[str, str, float]] = []

        for i in range(n_pairs):
            for j in range(i + 1, n_pairs):
                val = corr_matrix[i, j]
                if val > self.HIGH_CORR_THRESHOLD:
                    high_corr.append((available_pairs[i], available_pairs[j], val))
                elif val < self.ANTI_CORR_THRESHOLD:
                    anti_corr.append((available_pairs[i], available_pairs[j], val))

        # ── Step 5: USD exposure analysis ──
        exposure_by_currency: dict[str, float] = {}
        total_weight = n_pairs

        for pair in available_pairs:
            currencies = PAIR_CURRENCIES.get(pair)
            if currencies is None:
                continue
            base, quote = currencies
            # Each pair contributes 1/N to base and quote exposure
            exposure_by_currency[base] = exposure_by_currency.get(base, 0.0) + 1.0 / total_weight
            exposure_by_currency[quote] = exposure_by_currency.get(quote, 0.0) + 1.0 / total_weight

        usd_exposure = exposure_by_currency.get("USD", 0.0)

        # ── Step 6: PCA decomposition (first component) ──
        pca_var = 0.0
        if n_pairs >= 3:
            try:
                from noema.statistics.multivariate import perform_pca
                pca_result = perform_pca(
                    returns_array,
                    n_components=min(3, n_pairs),
                    feature_names=available_pairs,
                    standardize=True,
                )
                pca_var = float(pca_result.explained_variance_ratio[0]) if pca_result.explained_variance_ratio.size > 0 else 0.0
            except Exception as e:
                self._logger.debug("pca_failed", error=str(e))

        # ── Step 7: Basket recommendations ──
        recommendations: list[str] = []

        if usd_exposure > self.USD_EXPOSURE_CRITICAL:
            recommendations.append(
                f"⚠️ CRITICAL: USD exposure at {usd_exposure:.0%} — "
                f"severe concentration risk. Reduce USD pairs or use hedging."
            )
        elif usd_exposure > self.USD_EXPOSURE_WARN:
            recommendations.append(
                f"⚠️ WARNING: USD exposure at {usd_exposure:.0%} — "
                f"consider reducing USD-correlated positions."
            )

        for a, b, val in anti_corr:
            recommendations.append(
                f"🔄 Anti-correlated: {a} ↔ {b} ({val:.2f}) — "
                f"avoid opposing directional bets on these pairs."
            )

        for a, b, val in high_corr:
            recommendations.append(
                f"📊 Highly correlated: {a} ↔ {b} ({val:.2f}) — "
                f"treat as a basket, don't double directional exposure."
            )

        if pca_var > 0.7:
            recommendations.append(
                f"🔍 PCA: First component explains {pca_var:.0%} of variance — "
                f"pairs are strongly driven by a common factor (likely USD)."
            )

        # Determine data quality
        if len(available_pairs) >= 5 and min_len >= self.lookback_bars * 0.9:
            data_quality = "high"
        elif len(available_pairs) >= 3 and min_len >= self.MIN_BARS_FOR_COMPUTE * 2:
            data_quality = "medium"
        else:
            data_quality = "low"

        return CorrelationAnalysis(
            matrix=corr_matrix,
            pair_names=available_pairs,
            anti_correlated_pairs=anti_corr,
            highly_correlated_pairs=high_corr,
            exposure_by_currency=exposure_by_currency,
            usd_exposure=usd_exposure,
            basket_recommendations=recommendations,
            pca_explained_variance=pca_var,
            computed_at=datetime.now(timezone.utc).isoformat(),
            data_quality=data_quality,
        )

    def check_anti_correlation(
        self, pair_a: str, pair_b: str
    ) -> float | None:
        """Check if two specific pairs are anti-correlated.

        Args:
            pair_a: First pair.
            pair_b: Second pair.

        Returns:
            Correlation coefficient if data available, None otherwise.
        """
        if pair_a not in self._price_cache or pair_b not in self._price_cache:
            return None

        closes_a = self._price_cache[pair_a]
        closes_b = self._price_cache[pair_b]

        if len(closes_a) < self.MIN_BARS_FOR_COMPUTE or len(closes_b) < self.MIN_BARS_FOR_COMPUTE:
            return None

        if self.use_log_returns:
            ret_a = np.diff(np.log(closes_a))
            ret_b = np.diff(np.log(closes_b))
        else:
            ret_a = np.diff(closes_a) / closes_a[:-1]
            ret_b = np.diff(closes_b) / closes_b[:-1]

        min_len = min(len(ret_a), len(ret_b))
        r, _ = scipy_stats.pearsonr(ret_a[-min_len:], ret_b[-min_len:])
        return float(r)

    def are_opposing_bets_risky(
        self,
        position_a: tuple[str, str],  # (pair, direction) e.g., ("EURUSD", "BUY")
        position_b: tuple[str, str],
    ) -> tuple[bool, str]:
        """Check if two open/target positions create opposing-direction risk.

        An opposing bet occurs when:
        - Pair A is BUY and Pair B is SELL
        - AND the two pairs are highly anti-correlated (< -0.7)
        OR when both pairs are highly correlated (> 0.7) with opposite directions.

        Args:
            position_a: (pair, direction) for first position.
            position_b: (pair, direction) for second position.

        Returns:
            (is_risky: bool, reason: str)
        """
        pair_a, dir_a = position_a
        pair_b, dir_b = position_b

        corr = self.check_anti_correlation(pair_a, pair_b)
        if corr is None:
            return False, f"Insufficient data for {pair_a}/{pair_b} correlation."

        dir_same = (dir_a.upper() == dir_b.upper())

        # Case 1: Highly anti-correlated + SAME direction = contradictory
        if corr < self.ANTI_CORR_THRESHOLD and dir_same:
            return True, (
                f"OPPOSING RISK: {pair_a} and {pair_b} are anti-correlated ({corr:.2f}) "
                f"but both have {dir_a} direction. One will likely lose."
            )

        # Case 2: Highly correlated + OPPOSITE direction = cancelling out
        if corr > self.HIGH_CORR_THRESHOLD and not dir_same:
            return True, (
                f"OPPOSING RISK: {pair_a} and {pair_b} are highly correlated ({corr:.2f}) "
                f"but have opposite directions ({dir_a} vs {dir_b}). They cancel out."
            )

        # Case 3: Highly correlated + SAME direction = doubling exposure
        if corr > self.HIGH_CORR_THRESHOLD and dir_same:
            return True, (
                f"DOUBLING RISK: {pair_a} and {pair_b} are highly correlated ({corr:.2f}) "
                f"with same direction ({dir_a}). Effectively 2x exposure."
            )

        return False, "Pass"

    def get_usd_exposure_warning(
        self,
        open_positions: dict[str, str],  # {pair: direction}
    ) -> tuple[bool, str]:
        """Check if current open positions create excessive USD exposure.

        Args:
            open_positions: Dict mapping pair to direction (e.g., {"EURUSD": "BUY"}).

        Returns:
            (has_warning: bool, message: str)
        """
        usd_long_count = 0
        usd_short_count = 0
        total_usd_pairs = 0

        for pair, direction in open_positions.items():
            currencies = PAIR_CURRENCIES.get(pair)
            if currencies is None or "USD" not in currencies:
                continue

            total_usd_pairs += 1
            base, quote = currencies

            # Determine if this position is LONG or SHORT USD
            # BUY pair = long base, short quote
            # SELL pair = short base, long quote
            direction_upper = direction.upper()
            if base == "USD":
                # USDxxx: BUY = long USD, SELL = short USD
                if direction_upper in ("BUY", "LONG"):
                    usd_long_count += 1
                else:
                    usd_short_count += 1
            elif quote == "USD":
                # xxxUSD: BUY = short USD, SELL = long USD
                if direction_upper in ("BUY", "LONG"):
                    usd_short_count += 1
                else:
                    usd_long_count += 1

        if total_usd_pairs == 0:
            return False, "No USD pairs in open positions."

        # Net USD bias
        net_bias = abs(usd_long_count - usd_short_count) / max(total_usd_pairs, 1)

        if net_bias >= 0.8:
            bias_dir = "long" if usd_long_count > usd_short_count else "short"
            return True, (
                f"⚠️ USD exposure biased {net_bias:.0%} {bias_dir}: "
                f"{usd_long_count}L/{usd_short_count}S across {total_usd_pairs} USD pairs. "
                f"Consider diversification."
            )

        return False, "USD exposure balanced."

    def clear_cache(self) -> None:
        """Clear the price cache."""
        self._price_cache.clear()

    @property
    def cached_pairs(self) -> list[str]:
        """List of pairs currently in the price cache."""
        return list(self._price_cache.keys())

    @property
    def is_ready(self) -> bool:
        """True if enough pairs have been fed for analysis."""
        count_ready = sum(
            1 for closes in self._price_cache.values()
            if len(closes) >= self.MIN_BARS_FOR_COMPUTE
        )
        return count_ready >= 2
