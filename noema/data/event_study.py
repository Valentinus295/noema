"""
Event Study — Statistical analysis of economic event impact on forex pairs.

Phase 1.5: Applies event study methodology (Fama, Fisher, Jensen, Roll 1969; 
MacKinlay 1997) to forex. Maps to ECO 424 (Econometrics) and STA 244 (Time Series).

Capabilities:
    - Abnormal return calculation around events (CAR)
    - Pre/post volatility comparison (uses GARCH residuals from Phase 1)
    - Paired t-test / Wilcoxon for significance
    - Event impact database (learned over time, backtestable)
    - Impact calibration: which events actually move which pairs?

All computations are deterministic (no LLM involvement).
LLM role: narrative generation only (not in this module).

Usage:
    >>> study = EventStudy()
    >>> impact = study.analyze_event_impact(
    ...     pair="EURUSD",
    ...     event_name="NFP",
    ...     pre_prices=bars_before,
    ...     post_prices=bars_after,
    ... )
    >>> print(f"CAR: {impact.cumulative_abnormal_return:.4%}")
    >>> print(f"Significant: {impact.is_significant} (p={impact.p_value:.4f})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy import stats as scipy_stats

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════════════════════════

@dataclass
class EventImpactResult:
    """Result of an event impact analysis for a single pair-event combination.

    Attributes:
        event_name: Name of the economic event (e.g. "NFP", "FOMC")
        pair: Trading pair analyzed (e.g. "EURUSD")
        event_time: UTC time of the event
        cumulative_abnormal_return: CAR over the event window
        pre_volatility: Average volatility before event (e.g., GARCH sigma)
        post_volatility: Average volatility after event
        volatility_ratio: post_vol / pre_vol (> 1 = elevated vol)
        max_abs_return: Maximum absolute return in the event window
        is_significant: Whether the event had a statistically significant impact
        p_value: P-value from the significance test
        test_method: Which test was used ("ttest", "wilcoxon", "bootstrap")
        sample_size: Number of bars in event window
        mean_return: Mean return over event window bars
        std_return: Std deviation of returns over event window bars
        normality_normalized: Whether volatility returned to 1.5x pre-event within window
    """
    event_name: str
    pair: str
    event_time: datetime | None = None
    cumulative_abnormal_return: float = 0.0
    pre_volatility: float = 0.0
    post_volatility: float = 0.0
    volatility_ratio: float = 1.0
    max_abs_return: float = 0.0
    is_significant: bool = False
    p_value: float = 1.0
    test_method: str = "ttest"
    sample_size: int = 0
    mean_return: float = 0.0
    std_return: float = 0.0
    normality_normalized: bool = True


@dataclass
class EventStudyRecord:
    """Persistent record of a single event's impact — stored for backtesting."""
    event_name: str
    event_time: datetime
    currency: str
    pairs_affected: list[str] = field(default_factory=list)
    impacts: dict[str, EventImpactResult] = field(default_factory=dict)  # pair → ImpactResult
    narrative_llm: str = ""  # LLM-generated narrative (post-hoc, no trading role)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ══════════════════════════════════════════════════════════════════════
# Event Study Engine
# ══════════════════════════════════════════════════════════════════════

class EventStudy:
    """Statistical event impact analysis for forex economic events.

    Methodology:
    1. Pre-event window: Estimate normal volatility regime
       - Uses GARCH(1,1) residuals when available (Phase 1)
       - Falls back to rolling stddev
    2. Event window (configurable, default ±5 bars):
       - Compute abnormal returns (actual - expected)
       - Cumulative abnormal return (CAR)
       - Cross-sectional comparison across affected pairs
    3. Post-event window:
       - Test for volatility normalization
       - Significance testing (t-test, Wilcoxon signed-rank)
       - Impact calibration (which events move which pairs?)
    """

    def __init__(
        self,
        event_window_bars: int = 5,        # Bars around event (default: ±5)
        pre_window_bars: int = 50,         # Bars before event for baseline
        post_window_bars: int = 20,        # Bars after event for normalization check
        significance_level: float = 0.05,  # Alpha level for significance tests
        vol_normalization_mult: float = 1.5,  # Post-vol / pre-vol < this = normalized
    ):
        self.event_window_bars = event_window_bars
        self.pre_window_bars = pre_window_bars
        self.post_window_bars = post_window_bars
        self.significance_level = significance_level
        self.vol_normalization_mult = vol_normalization_mult

        # Historical impact database (learned over time)
        self._impact_db: dict[str, dict[str, list[EventImpactResult]]] = {}  # event → pair → list

    # ── Core Analysis ───────────────────────────────────────────────

    def analyze_event_impact(
        self,
        event_name: str,
        pair: str,
        pre_prices: list[float],
        post_prices: list[float],
        event_time: datetime | None = None,
        use_garch_residuals: list[float] | None = None,
    ) -> EventImpactResult:
        """Analyze the impact of an economic event on a forex pair.

        Args:
            event_name: Name of the event (e.g. "NFP", "FOMC Interest Rate Decision")
            pair: Trading pair (e.g. "EURUSD")
            pre_prices: Price series before the event (length ≥ pre_window_bars)
            post_prices: Price series after the event (length ≥ post_window_bars)
            event_time: UTC timestamp of the event
            use_garch_residuals: GARCH standardized residuals for better volatility estimate

        Returns:
            EventImpactResult with statistical measures of impact.
        """
        # ── 1. Compute returns ────────
        pre_returns = _compute_log_returns(pre_prices)
        post_returns = _compute_log_returns(post_prices)

        if len(pre_returns) < 2 or len(post_returns) < 2:
            return EventImpactResult(event_name=event_name, pair=pair, event_time=event_time)

        # ── 2. Pre-event volatility (baseline) ────────
        if use_garch_residuals and len(use_garch_residuals) >= 10:
            # Use GARCH residual std as volatility estimate
            pre_vol = float(np.std(use_garch_residuals[-self.pre_window_bars:]))
        else:
            # Fall back to rolling std of log returns
            pre_window = pre_returns[-self.pre_window_bars:] if len(pre_returns) > self.pre_window_bars else pre_returns
            pre_vol = float(np.std(pre_window))

        if pre_vol == 0:
            pre_vol = 0.0001  # Avoid division by zero (0.01% baseline vol)

        # ── 3. Expected return (mean of pre-window returns) ────────
        if len(pre_returns) > self.pre_window_bars:
            expected_return = float(np.mean(pre_returns[-self.pre_window_bars:]))
        else:
            expected_return = float(np.mean(pre_returns))

        # ── 4. Event window returns (abnormal) ────────
        event_returns = post_returns[:self.event_window_bars]
        if len(event_returns) < 2:
            event_returns = post_returns[:min(len(post_returns), self.event_window_bars)]

        abnormal_returns = [r - expected_return for r in event_returns]
        car = float(np.sum(abnormal_returns))
        mean_ab_return = float(np.mean(abnormal_returns)) if abnormal_returns else 0.0
        std_ab_return = float(np.std(abnormal_returns)) if len(abnormal_returns) > 1 else 0.0

        # ── 5. Post-event volatility ────────
        post_window = post_returns[:self.post_window_bars] if len(post_returns) >= self.post_window_bars else post_returns
        post_vol = float(np.std(post_window))
        vol_ratio = post_vol / pre_vol if pre_vol > 0 else 1.0

        # ── 6. Max absolute return in event window ────────
        max_abs_ret = float(max(abs(r) for r in abnormal_returns)) if abnormal_returns else 0.0

        # ── 7. Significance testing ────────
        is_sig, p_val, test_method = self._test_significance(
            pre_returns=pre_returns[-self.pre_window_bars:] if len(pre_returns) > self.pre_window_bars else pre_returns,
            event_returns=abnormal_returns,
        )

        # ── 8. Volatility normalization check ────────
        normality_normalized = vol_ratio < self.vol_normalization_mult

        result = EventImpactResult(
            event_name=event_name,
            pair=pair,
            event_time=event_time,
            cumulative_abnormal_return=car,
            pre_volatility=pre_vol,
            post_volatility=post_vol,
            volatility_ratio=vol_ratio,
            max_abs_return=max_abs_ret,
            is_significant=is_sig,
            p_value=p_val,
            test_method=test_method,
            sample_size=len(abnormal_returns),
            mean_return=mean_ab_return,
            std_return=std_ab_return,
            normality_normalized=normality_normalized,
        )

        # Store in impact database
        self._record_impact(result)

        return result

    def analyze_cross_sectional(
        self,
        event_name: str,
        pair_results: dict[str, EventImpactResult],
        event_time: datetime | None = None,
    ) -> list[EventImpactResult]:
        """Cross-sectional analysis: compare impact across affected pairs.

        For NFP → all USD pairs: EURUSD, GBPUSD, USDJPY, AUDUSD, etc.
        Identifies which pairs are most/least affected.
        """
        significant_pairs = [r for r in pair_results.values() if r.is_significant]
        return sorted(significant_pairs, key=lambda r: abs(r.cumulative_abnormal_return), reverse=True)

    # ── Significance Testing ────────────────────────────────────────

    def _test_significance(
        self,
        pre_returns: list[float],
        event_returns: list[float],
    ) -> tuple[bool, float, str]:
        """Test whether event-window returns are significantly different from pre-event.

        Tests in order: t-test (parametric), Wilcoxon (non-parametric), Bootstrap (last resort).

        Returns: (is_significant, p_value, method_name)
        """
        pre = np.array(pre_returns, dtype=float)
        evt = np.array(event_returns, dtype=float)

        if len(evt) < 3:
            return False, 1.0, "insufficient_data"

        # ── Test 1: One-sample t-test (is mean abnormal return ≠ 0?) ──
        try:
            t_stat, p_val = scipy_stats.ttest_1samp(evt, popmean=0.0)
            if not np.isnan(p_val):
                return float(p_val) < self.significance_level, float(p_val), "ttest"
        except Exception:
            pass

        # ── Test 2: Wilcoxon signed-rank (non-parametric) ──
        try:
            if len(evt) >= 5:
                w_stat, p_val = scipy_stats.wilcoxon(evt)
                if not np.isnan(p_val):
                    return float(p_val) < self.significance_level, float(p_val), "wilcoxon"
        except Exception:
            pass

        # ── Test 3: Bootstrap (resample pre-returns to build null distribution) ──
        try:
            if len(pre) >= 10:
                p_val = _bootstrap_test(pre, np.mean(evt), n_bootstrap=1000)
                return float(p_val) < self.significance_level, float(p_val), "bootstrap"
        except Exception:
            pass

        return False, 1.0, "failed"

    # ── Volatility Normalization ────────────────────────────────────

    def is_volatility_normalized(
        self,
        current_returns: list[float],
        pre_event_volatility: float,
        lookback_bars: int = 20,
    ) -> bool:
        """Check if volatility has returned to within normalization_mult of pre-event levels.

        Used by EventAnalyst to decide when to lift the blackout.
        """
        if len(current_returns) < 5:
            return False

        recent_returns = current_returns[-lookback_bars:]
        recent_vol = float(np.std(recent_returns))

        if pre_event_volatility <= 0:
            return True  # No baseline → assume normalized

        vol_ratio = recent_vol / pre_event_volatility
        return vol_ratio < self.vol_normalization_mult

    # ── Event Impact Database ───────────────────────────────────────

    def _record_impact(self, result: EventImpactResult) -> None:
        """Record an impact result in the internal database."""
        key = result.event_name.lower()
        if key not in self._impact_db:
            self._impact_db[key] = {}
        if result.pair not in self._impact_db[key]:
            self._impact_db[key][result.pair] = []
        self._impact_db[key][result.pair].append(result)

    def get_historical_impact(
        self,
        event_name: str,
        pair: str | None = None,
        max_records: int = 20,
    ) -> list[EventImpactResult]:
        """Get historical impact records for an event type.

        Args:
            event_name: e.g. "NFP", "FOMC"
            pair: Optional, filter to specific pair
            max_records: Maximum number of records to return

        Returns:
            List of EventImpactResult sorted by event_time (newest first).
        """
        key = event_name.lower()
        if key not in self._impact_db:
            return []

        records = []
        if pair:
            records = self._impact_db[key].get(pair, [])
        else:
            for pair_records in self._impact_db[key].values():
                records.extend(pair_records)

        # Sort by event_time (newest first), filter None times
        records = [r for r in records if r.event_time is not None]
        records.sort(key=lambda r: r.event_time, reverse=True)  # type: ignore[arg-type]

        return records[-max_records:]

    def get_event_pair_sensitivity(self) -> dict[str, dict[str, float]]:
        """Get event → pair sensitivity mapping for the orchestrator.

        Returns:
            dict where:
                key = event name
                value = {pair: average_abs_CAR}

        Example:
            {"nfp": {"EURUSD": 0.0042, "GBPUSD": 0.0051, "USDJPY": 0.0048}}
        """
        sensitivity: dict[str, dict[str, float]] = {}
        for event_name, pair_dict in self._impact_db.items():
            sensitivity[event_name] = {}
            for pair, records in pair_dict.items():
                if records:
                    avg_car = float(np.mean([abs(r.cumulative_abnormal_return) for r in records]))
                    sensitivity[event_name][pair] = avg_car
        return sensitivity

    def get_pair_sensitive_events(
        self,
        pair: str,
        min_avg_car: float = 0.001,
    ) -> list[tuple[str, float]]:
        """Get events that significantly affect a given pair, ranked by impact.

        Args:
            pair: Trading pair (e.g. "EURUSD")
            min_avg_car: Minimum average CAR to consider meaningful (default 0.1%)

        Returns:
            List of (event_name, avg_abs_CAR) sorted by impact.
        """
        results = []
        for event_name, pair_dict in self._impact_db.items():
            records = pair_dict.get(pair, [])
            if records:
                avg_car = float(np.mean([abs(r.cumulative_abnormal_return) for r in records]))
                if avg_car >= min_avg_car:
                    results.append((event_name, avg_car))

        results.sort(key=lambda x: x[1], reverse=True)
        return results


# ══════════════════════════════════════════════════════════════════════
# Utility Functions
# ══════════════════════════════════════════════════════════════════════

def _compute_log_returns(prices: list[float]) -> list[float]:
    """Compute log returns from a price series."""
    if len(prices) < 2:
        return []
    prices_arr = np.array(prices, dtype=float)
    # Avoid log(0) or log(negative)
    mask = prices_arr > 0
    if not mask.all():
        prices_arr = np.where(mask, prices_arr, np.nan)
    return list(np.diff(np.log(prices_arr[mask])))


def _bootstrap_test(
    pre_returns: np.ndarray,
    event_mean: float,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> float:
    """Bootstrap test: what's the probability of observing |event_mean|
    from a null distribution built from pre-returns?

    Returns p-value.
    """
    rng = np.random.default_rng(seed)
    n = len(pre_returns)

    # Bootstrap null distribution: draw n samples from pre_returns, compute mean
    null_means = np.array([
        float(np.mean(rng.choice(pre_returns, size=min(n, 10), replace=True)))
        for _ in range(n_bootstrap)
    ])

    # Two-tailed p-value: proportion of null means more extreme than observed
    p_val = float(np.mean(np.abs(null_means) >= abs(event_mean)))
    return max(p_val, 1.0 / n_bootstrap)  # Floor at 1/n_bootstrap


def estimate_event_volatility(
    prices: list[float],
    use_garch: bool = False,
) -> dict[str, float]:
    """Estimate pre-event volatility baseline.

    Args:
        prices: Price series before the event
        use_garch: Attempt to use GARCH(1,1) for volatility estimate

    Returns:
        dict with {"volatility", "model_used"}
    """
    returns = _compute_log_returns(prices)
    if len(returns) < 10:
        return {"volatility": 0.0, "model_used": "none"}

    if use_garch:
        try:
            from noema.econometrics.volatility import fit_garch

            result = fit_garch(returns)
            if result and result.omega is not None:
                vol = float(np.sqrt(result.omega / (1 - result.alpha - result.beta)))
                return {"volatility": vol, "model_used": "garch"}
        except Exception:
            pass

    # Fallback: rolling std dev (annualized from log returns)
    vol = float(np.std(returns))
    return {"volatility": vol, "model_used": "rolling_std"}
