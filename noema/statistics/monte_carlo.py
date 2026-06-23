"""Monte Carlo simulation methods for risk assessment.

Simulation-based statistical inference:
- Monte Carlo simulation with configurable distributions
- Probability of ruin (gambler's ruin model)
- Value at Risk (VaR) and Conditional VaR (CVaR/Expected Shortfall)
- Bootstrap confidence intervals
- Block bootstrap (stationary, moving block) for time series
- Expected maximum drawdown simulation

Every function returns typed MCSimulationResult with statistics.
Uses: numpy, scipy — no LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
from scipy import stats as scipy_stats


@dataclass
class MCSimulationResult:
    """Monte Carlo simulation result.

    Attributes:
        statistic: Target statistic or metric name.
        mean: Mean of simulation distribution.
        median: Median.
        std: Standard deviation.
        ci_lower: Lower bound of confidence interval.
        ci_upper: Upper bound.
        ci_level: Confidence level (e.g., 0.95).
        values: Simulated values (for visualization/diagnostics).
        n_simulations: Number of simulation runs.
        p_ruin: Probability of ruin (when applicable).
        additional: Additional metrics.
    """
    statistic: str
    mean: float
    median: float = 0.0
    std: float = 0.0
    ci_lower: float = 0.0
    ci_upper: float = 0.0
    ci_level: float = 0.95
    values: np.ndarray = field(default_factory=lambda: np.array([]))
    n_simulations: int = 0
    p_ruin: Optional[float] = None
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def skewness(self) -> float:
        """Skewness of simulated values."""
        if len(self.values) < 3:
            return 0.0
        return float(scipy_stats.skew(self.values))

    @property
    def kurtosis(self) -> float:
        """Excess kurtosis of simulated values."""
        if len(self.values) < 4:
            return 0.0
        return float(scipy_stats.kurtosis(self.values))

    @property
    def sharpe_ratio(self) -> Optional[float]:
        """Simulated Sharpe ratio (mean / std)."""
        if self.std > 1e-10:
            return self.mean / self.std
        return None

    def percentile(self, q: float) -> float:
        """Get the q-th percentile of simulated values (0-100)."""
        return float(np.percentile(self.values, q))

    def to_dict(self) -> dict[str, Any]:
        return {
            "statistic": self.statistic,
            "mean": self.mean,
            "median": self.median,
            "std": self.std,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "ci_level": self.ci_level,
            "n_simulations": self.n_simulations,
            "p_ruin": self.p_ruin,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
        }


def monte_carlo_simulation(
    generator: Callable[[], float],
    n_simulations: int = 10000,
    ci_level: float = 0.95,
    statistic_name: str = "simulation",
) -> MCSimulationResult:
    """Run a Monte Carlo simulation using a generator function.

    Args:
        generator: Callable that returns a single simulation result.
        n_simulations: Number of simulation runs.
        ci_level: Confidence interval level (e.g., 0.95).
        statistic_name: Name of the statistic being estimated.

    Returns:
        MCSimulationResult with mean, CI, and full distribution.
    """
    values = np.zeros(n_simulations)
    for i in range(n_simulations):
        values[i] = generator()

    mean = float(np.mean(values))
    median = float(np.median(values))
    std = float(np.std(values, ddof=1))

    # Confidence interval (percentile bootstrap)
    alpha = (1 - ci_level) / 2
    ci_lower = float(np.percentile(values, 100 * alpha))
    ci_upper = float(np.percentile(values, 100 * (1 - alpha)))

    return MCSimulationResult(
        statistic=statistic_name,
        mean=mean,
        median=median,
        std=std,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_level=ci_level,
        values=values,
        n_simulations=n_simulations,
    )


def probability_of_ruin(
    initial_capital: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    max_risk_per_trade_pct: float = 0.02,
    n_simulations: int = 10000,
    max_trades: int = 1000,
    ruin_threshold: float = 0.3,
    random_seed: Optional[int] = None,
) -> MCSimulationResult:
    """Estimate probability of ruin via Monte Carlo simulation.

    Models equity curve evolution as a biased random walk with variable
    position sizes. Critical for risk management — answers:
    "What is the probability we go broke given our edge and sizing?"

    Args:
        initial_capital: Starting account balance.
        win_rate: Probability of a winning trade (0-1).
        avg_win: Average profit on winning trades (in account currency).
        avg_loss: Average loss on losing trades (positive number).
        max_risk_per_trade_pct: Maximum fraction of capital risked per trade.
        n_simulations: Number of equity curve simulations.
        max_trades: Maximum number of trades per simulation.
        ruin_threshold: Fraction of initial capital below which = ruin.
        random_seed: Optional random seed.

    Returns:
        MCSimulationResult with p_ruin and equity distribution.
    """
    rng = np.random.RandomState(random_seed)
    ruin_count = 0
    final_equities = np.zeros(n_simulations)
    max_drawdowns = np.zeros(n_simulations)
    ruin_at = np.full(n_simulations, max_trades + 1, dtype=int)

    ruin_capital = initial_capital * ruin_threshold

    for sim in range(n_simulations):
        equity = initial_capital
        peak = equity
        max_dd = 0.0

        for t in range(max_trades):
            # Determine if this trade wins
            is_win = rng.random() < win_rate

            # Position size based on risk per trade
            risk_amount = equity * max_risk_per_trade_pct
            # Loss-based sizing: risk_amount = position * avg_loss → position = risk/avg_loss
            if avg_loss > 0:
                position_value = risk_amount / (avg_loss / avg_win if avg_win > 0 else 1.0)
            else:
                position_value = risk_amount

            if is_win:
                equity += position_value * (avg_win / (avg_loss if avg_loss > 0 else 1.0))
            else:
                equity -= risk_amount

            # Track peak and drawdown
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

            # Check ruin
            if equity <= ruin_capital:
                ruin_count += 1
                ruin_at[sim] = t + 1
                equity = ruin_capital  # Floor at ruin
                break

        final_equities[sim] = equity
        max_drawdowns[sim] = max_dd

    p_ruin = ruin_count / n_simulations

    return MCSimulationResult(
        statistic="P(ruin)",
        mean=float(np.mean(final_equities)),
        median=float(np.median(final_equities)),
        std=float(np.std(final_equities)),
        ci_lower=float(np.percentile(final_equities, 2.5)),
        ci_upper=float(np.percentile(final_equities, 97.5)),
        values=final_equities,
        n_simulations=n_simulations,
        p_ruin=p_ruin,
        additional={
            "initial_capital": initial_capital,
            "ruin_threshold_pct": ruin_threshold,
            "ruin_threshold_value": ruin_capital,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_trades": max_trades,
            "mean_max_drawdown": float(np.mean(max_drawdowns)),
            "median_max_drawdown": float(np.median(max_drawdowns)),
            "max_drawdown_95pct": float(np.percentile(max_drawdowns, 95)),
            "mean_trades_to_ruin": float(np.mean(ruin_at[ruin_at <= max_trades])) if ruin_count > 0 else float('inf'),
        },
    )


def value_at_risk(
    returns: np.ndarray,
    confidence: float = 0.95,
    method: str = "historical",
) -> dict[str, Any]:
    """Compute Value at Risk (VaR).

    VaR estimates the maximum loss at a given confidence level over
    a holding period. Returns absolute VaR (loss as positive number).

    Args:
        returns: Array of returns (e.g., daily log returns).
        confidence: Confidence level (0.95 = 95% VaR).
        method: "historical" (empirical quantile), "parametric" (normal), 
                or "cornish_fisher" (accounts for skew/kurtosis).

    Returns:
        Dictionary with VaR value and methodology.
    """
    returns = np.asarray(returns, dtype=float).ravel()

    if method == "parametric":
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))
        z = scipy_stats.norm.ppf(1 - confidence)
        var = float(-(mu + z * sigma))

    elif method == "cornish_fisher":
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))
        z = scipy_stats.norm.ppf(1 - confidence)
        s = float(scipy_stats.skew(returns))
        k = float(scipy_stats.kurtosis(returns))
        # Cornish-Fisher expansion
        z_cf = z + (s / 6) * (z ** 2 - 1) + (k / 24) * (z ** 3 - 3 * z) - (s ** 2 / 36) * (2 * z ** 3 - 5 * z)
        var = float(-(mu + z_cf * sigma))

    else:  # historical
        var = float(-np.percentile(returns, 100 * (1 - confidence)))

    return {
        "var": var,
        "confidence": confidence,
        "method": method,
        "n_samples": len(returns),
        "var_as_pct": var if var < 1 else var,  # Handle both return and price scales
    }


def conditional_value_at_risk(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Compute Conditional Value at Risk (CVaR / Expected Shortfall).

    CVaR is the expected loss conditional on exceeding VaR.
    Always >= VaR, captures tail risk that VaR misses.

    Args:
        returns: Array of returns.
        confidence: Confidence level.

    Returns:
        Dictionary with CVaR, VaR, and methodology.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    var_result = value_at_risk(returns, confidence, method="historical")
    var_val = var_result["var"]

    # CVaR = mean of returns worse than VaR
    var_threshold = np.percentile(returns, 100 * (1 - confidence))
    tail = returns[returns <= var_threshold]
    cvar = float(-np.mean(tail)) if len(tail) > 0 else var_val

    return {
        "cvar": cvar,
        "var": var_val,
        "confidence": confidence,
        "n_tail_samples": len(tail),
        "n_samples": len(returns),
        "tail_fraction": len(tail) / len(returns) if len(returns) > 0 else 0.0,
    }


def bootstrap_ci(
    data: np.ndarray,
    statistic_fn: Callable[[np.ndarray], float] = np.mean,
    n_bootstrap: int = 10000,
    ci_level: float = 0.95,
    method: str = "percentile",
    random_seed: Optional[int] = None,
) -> MCSimulationResult:
    """Compute bootstrap confidence interval for a statistic.

    Non-parametric bootstrap: resamples data with replacement to
    estimate the sampling distribution of any statistic.

    Args:
        data: Original sample.
        statistic_fn: Function to compute the statistic.
        n_bootstrap: Number of bootstrap resamples.
        ci_level: Confidence level (0.95 = 95% CI).
        method: "percentile" (simple) or "bca" (bias-corrected accelerated).
        random_seed: Random seed.

    Returns:
        MCSimulationResult with bootstrap distribution and CI.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    rng = np.random.RandomState(random_seed)

    bootstrap_stats = np.zeros(n_bootstrap)
    for i in range(n_bootstrap):
        resample = data[rng.randint(0, n, n)]
        bootstrap_stats[i] = statistic_fn(resample)

    mean = float(np.mean(bootstrap_stats))
    std = float(np.std(bootstrap_stats, ddof=1))

    if method == "bca":
        # Bias-corrected and accelerated interval
        obs_stat = statistic_fn(data)
        # Bias correction
        z0 = scipy_stats.norm.ppf(np.mean(bootstrap_stats < obs_stat))
        # Acceleration (jackknife)
        jack_stats = np.zeros(n)
        for i in range(n):
            jack_data = np.delete(data, i)
            jack_stats[i] = statistic_fn(jack_data)
        jack_mean = np.mean(jack_stats)
        num = np.sum((jack_mean - jack_stats) ** 3)
        den = 6 * (np.sum((jack_mean - jack_stats) ** 2)) ** 1.5
        a = num / den if den > 0 else 0.0

        alpha = 1 - ci_level
        z_alpha = scipy_stats.norm.ppf(alpha / 2)
        z_1_alpha = scipy_stats.norm.ppf(1 - alpha / 2)

        p_lower = scipy_stats.norm.cdf(z0 + (z0 + z_alpha) / (1 - a * (z0 + z_alpha)))
        p_upper = scipy_stats.norm.cdf(z0 + (z0 + z_1_alpha) / (1 - a * (z0 + z_1_alpha)))

        ci_lower = float(np.percentile(bootstrap_stats, 100 * p_lower))
        ci_upper = float(np.percentile(bootstrap_stats, 100 * p_upper))
    else:
        alpha = (1 - ci_level) / 2
        ci_lower = float(np.percentile(bootstrap_stats, 100 * alpha))
        ci_upper = float(np.percentile(bootstrap_stats, 100 * (1 - alpha)))

    return MCSimulationResult(
        statistic="bootstrap_ci",
        mean=mean,
        median=float(np.median(bootstrap_stats)),
        std=std,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_level=ci_level,
        values=bootstrap_stats,
        n_simulations=n_bootstrap,
        additional={
            "method": method,
            "n_original": n,
            "statistic_name": statistic_fn.__name__ if hasattr(statistic_fn, "__name__") else "unknown",
        },
    )


def block_bootstrap(
    data: np.ndarray,
    block_size: int,
    statistic_fn: Callable[[np.ndarray], float] = np.mean,
    n_bootstrap: int = 10000,
    ci_level: float = 0.95,
    random_seed: Optional[int] = None,
) -> MCSimulationResult:
    """Moving block bootstrap for dependent (time series) data.

    Standard i.i.d. bootstrap fails for autocorrelated data (like financial
    returns). Block bootstrap preserves serial dependence by resampling
    contiguous blocks of observations.

    Args:
        data: Time series data.
        block_size: Size of each block (determines serial dependence length).
        statistic_fn: Function to compute the statistic.
        n_bootstrap: Number of bootstrap resamples.
        ci_level: Confidence level.
        random_seed: Random seed.

    Returns:
        MCSimulationResult with block-bootstrap distribution and CI.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    rng = np.random.RandomState(random_seed)

    bootstrap_stats = np.zeros(n_bootstrap)
    n_blocks = int(np.ceil(n / block_size))

    for i in range(n_bootstrap):
        resample = []
        for _ in range(n_blocks):
            start = rng.randint(0, n - block_size + 1)
            resample.extend(data[start:start + block_size].tolist())
        resample = np.array(resample[:n])
        bootstrap_stats[i] = statistic_fn(resample)

    mean = float(np.mean(bootstrap_stats))
    std = float(np.std(bootstrap_stats, ddof=1))
    alpha = (1 - ci_level) / 2
    ci_lower = float(np.percentile(bootstrap_stats, 100 * alpha))
    ci_upper = float(np.percentile(bootstrap_stats, 100 * (1 - alpha)))

    return MCSimulationResult(
        statistic="block_bootstrap",
        mean=mean,
        median=float(np.median(bootstrap_stats)),
        std=std,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_level=ci_level,
        values=bootstrap_stats,
        n_simulations=n_bootstrap,
        additional={
            "method": "moving_block_bootstrap",
            "block_size": block_size,
            "n_original": n,
            "autocorrelation_preserved_up_to_lag": block_size - 1,
        },
    )


def stationary_bootstrap(
    data: np.ndarray,
    expected_block_size: float,
    statistic_fn: Callable[[np.ndarray], float] = np.mean,
    n_bootstrap: int = 10000,
    ci_level: float = 0.95,
    random_seed: Optional[int] = None,
) -> MCSimulationResult:
    """Stationary bootstrap for time series data.

    Extends block bootstrap with random block lengths (geometric distribution).
    Produces stationary resamples — useful for financial time series.

    Args:
        data: Time series data.
        expected_block_size: Mean block length (1/p where p = geometric parameter).
        statistic_fn: Function to compute the statistic.
        n_bootstrap: Number of resamples.
        ci_level: Confidence level.
        random_seed: Random seed.

    Returns:
        MCSimulationResult with stationary bootstrap distribution and CI.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    rng = np.random.RandomState(random_seed)

    # Geometric probability: p = 1 / expected_block_size
    p = 1.0 / expected_block_size

    bootstrap_stats = np.zeros(n_bootstrap)

    for b in range(n_bootstrap):
        resample = []
        idx = rng.randint(0, n)
        while len(resample) < n:
            resample.append(data[idx])
            idx = (idx + 1) % n
            # Stop block with probability p
            if rng.random() < p and len(resample) < n:
                idx = rng.randint(0, n)

        resample_arr = np.array(resample[:n])
        bootstrap_stats[b] = statistic_fn(resample_arr)

    mean = float(np.mean(bootstrap_stats))
    std = float(np.std(bootstrap_stats, ddof=1))
    alpha = (1 - ci_level) / 2
    ci_lower = float(np.percentile(bootstrap_stats, 100 * alpha))
    ci_upper = float(np.percentile(bootstrap_stats, 100 * (1 - alpha)))

    return MCSimulationResult(
        statistic="stationary_bootstrap",
        mean=mean,
        median=float(np.median(bootstrap_stats)),
        std=std,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_level=ci_level,
        values=bootstrap_stats,
        n_simulations=n_bootstrap,
        additional={
            "method": "stationary_bootstrap",
            "expected_block_size": expected_block_size,
            "n_original": n,
        },
    )


def expected_max_drawdown(
    returns: np.ndarray,
    n_simulations: int = 10000,
    horizon: Optional[int] = None,
    method: str = "bootstrap",
    ci_level: float = 0.95,
    random_seed: Optional[int] = None,
) -> MCSimulationResult:
    """Estimate expected maximum drawdown via simulation.

    Critical for position sizing: answers "What's the worst pain
    we should expect given this strategy's return characteristics?"

    Args:
        returns: Historical return series.
        n_simulations: Number of equity curve simulations.
        horizon: Trading horizon (number of periods). Defaults to len(returns).
        method: "bootstrap" (resample returns) or "parametric" (normal).
        ci_level: Confidence level.
        random_seed: Random seed.

    Returns:
        MCSimulationResult with drawdown distribution.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    n = len(returns)
    horizon = horizon or n
    rng = np.random.RandomState(random_seed)

    max_dd_values = np.zeros(n_simulations)

    for sim in range(n_simulations):
        if method == "parametric":
            mu = float(np.mean(returns))
            sigma = float(np.std(returns, ddof=1))
            sim_returns = rng.normal(mu, sigma, horizon)
        else:
            # Bootstrap returns
            sim_returns = returns[rng.randint(0, n, horizon)]

        # Compute equity curve
        equity = np.cumprod(1 + sim_returns)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_dd_values[sim] = float(np.max(drawdown))

    mean = float(np.mean(max_dd_values))
    median = float(np.median(max_dd_values))
    std = float(np.std(max_dd_values, ddof=1))
    alpha = (1 - ci_level) / 2
    ci_lower = float(np.percentile(max_dd_values, 100 * alpha))
    ci_upper = float(np.percentile(max_dd_values, 100 * (1 - alpha)))

    return MCSimulationResult(
        statistic="expected_max_drawdown",
        mean=mean,
        median=median,
        std=std,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_level=ci_level,
        values=max_dd_values,
        n_simulations=n_simulations,
        additional={
            "method": method,
            "horizon": horizon,
            "expected_max_dd_95pct": float(np.percentile(max_dd_values, 95)),
            "expected_max_dd_99pct": float(np.percentile(max_dd_values, 99)),
            "n_original_returns": n,
        },
    )
