"""Statistical gates for strategy validation.

Implements:
- Bootstrap confidence interval on Sharpe (Politis-Romano stationary bootstrap)
- SPRT (Sequential Probability Ratio Test) for online edge monitoring
- Permutation test via stationary bootstrap
- Monte Carlo equity simulation → P(ruin)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np


@dataclass
class BootstrapResult:
    """Bootstrap confidence interval result."""
    mean: float
    ci_lower: float
    ci_upper: float
    n_resamples: int
    significant: bool  # True if CI doesn't contain 0


@dataclass
class SPRTResult:
    """Sequential Probability Ratio Test result."""
    log_likelihood_ratio: float
    decision: str  # "accept_h0", "accept_h1", "continue"
    trades_tested: int


@dataclass
class PermutationResult:
    """Permutation test result."""
    observed_statistic: float
    p_value: float
    significant: bool


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation result."""
    p_ruin: float
    median_final_equity: float
    worst_case_equity: float
    best_case_equity: float
    n_simulations: int


def bootstrap_sharpe_ci(
    pnls: list[float],
    n_resamples: int = 5000,
    confidence: float = 0.95,
    seed: int = 42,
) -> BootstrapResult:
    """Bootstrap CI on Sharpe ratio using stationary bootstrap (Politis-Romano)."""
    if len(pnls) < 10:
        return BootstrapResult(0.0, 0.0, 0.0, 0, False)

    rng = np.random.RandomState(seed)
    pnls_arr = np.array(pnls)
    observed_sharpe = _compute_sharpe(pnls_arr)

    # Block length for stationary bootstrap
    block_len = max(5, int(len(pnls) * 0.1))

    bootstrap_sharpes = []
    for _ in range(n_resamples):
        sample = _stationary_bootstrap(pnls_arr, block_len, rng)
        bootstrap_sharpes.append(_compute_sharpe(sample))

    alpha = (1 - confidence) / 2
    ci_lower = float(np.percentile(bootstrap_sharpes, alpha * 100))
    ci_upper = float(np.percentile(bootstrap_sharpes, (1 - alpha) * 100))

    return BootstrapResult(
        mean=observed_sharpe,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        n_resamples=n_resamples,
        significant=ci_lower > 0,
    )


def sprt_monitor(
    trades_pnl: list[float],
    h0_expectancy: float = 0.0,
    h1_expectancy: float = 0.15,
    alpha: float = 0.05,
    beta: float = 0.20,
) -> SPRTResult:
    """Sequential Probability Ratio Test for online edge monitoring.

    H0: E[R] = h0_expectancy (no edge)
    H1: E[R] = h1_expectancy (positive edge)
    """
    if not trades_pnl:
        return SPRTResult(0.0, "continue", 0)

    log_a = math.log((1 - beta) / alpha)
    log_b = math.log(beta / (1 - alpha))

    llr = 0.0
    for i, pnl in enumerate(trades_pnl):
        # Log-likelihood ratio under normal assumption
        if h1_expectancy != h0_expectancy:
            llr += (pnl - (h0_expectancy + h1_expectancy) / 2) / max(abs(h1_expectancy - h0_expectancy), 1e-10)
        
        if llr >= log_a:
            return SPRTResult(llr, "accept_h1", i + 1)
        elif llr <= log_b:
            return SPRTResult(llr, "accept_h0", i + 1)

    return SPRTResult(llr, "continue", len(trades_pnl))


def permutation_test(
    pnls: list[float],
    n_resamples: int = 5000,
    mean_block_length: int = 20,
    seed: int = 42,
) -> PermutationResult:
    """Permutation test using stationary bootstrap (Politis-Romano)."""
    if len(pnls) < 10:
        return PermutationResult(0.0, 1.0, False)

    rng = np.random.RandomState(seed)
    pnls_arr = np.array(pnls)
    observed_stat = np.mean(pnls_arr)

    count_extreme = 0
    for _ in range(n_resamples):
        resampled = _stationary_bootstrap(pnls_arr, mean_block_length, rng)
        if abs(np.mean(resampled)) >= abs(observed_stat):
            count_extreme += 1

    p_value = count_extreme / n_resamples
    return PermutationResult(
        observed_statistic=float(observed_stat),
        p_value=p_value,
        significant=p_value < 0.05,
    )


def monte_carlo_ruin(
    trades_pnl: list[float],
    initial_balance: float = 10000.0,
    risk_pct: float = 0.01,
    n_simulations: int = 10000,
    n_trades_per_sim: int = 252,
    seed: int = 42,
) -> MonteCarloResult:
    """Monte Carlo equity simulation to estimate P(ruin)."""
    if not trades_pnl:
        return MonteCarloResult(0.0, initial_balance, initial_balance, initial_balance, 0)

    rng = np.random.RandomState(seed)
    final_equities = []
    ruin_count = 0

    for _ in range(n_simulations):
        equity = initial_balance
        peak = equity
        ruined = False

        for _ in range(n_trades_per_sim):
            pnl = rng.choice(trades_pnl)
            equity += pnl
            peak = max(peak, equity)

            if equity <= 0:
                ruined = True
                break

        if ruined:
            ruin_count += 1
        final_equities.append(max(0, equity))

    return MonteCarloResult(
        p_ruin=ruin_count / n_simulations,
        median_final_equity=float(np.median(final_equities)),
        worst_case_equity=float(np.percentile(final_equities, 5)),
        best_case_equity=float(np.percentile(final_equities, 95)),
        n_simulations=n_simulations,
    )


# ── Internal helpers ──

def _compute_sharpe(pnls: np.ndarray) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = np.mean(pnls)
    std = np.std(pnls, ddof=1)
    return float(mean / std * np.sqrt(8760)) if std > 1e-10 else 0.0


def _stationary_bootstrap(data: np.ndarray, block_len: int, rng: np.random.RandomState) -> np.ndarray:
    """Stationary bootstrap (Politis-Romano) resampling."""
    n = len(data)
    result = np.empty(n)
    start = rng.randint(0, n)
    pos = start
    i = 0
    while i < n:
        result[i] = data[pos]
        pos = (pos + 1) % n
        i += 1
        if rng.random() < 1.0 / block_len:
            pos = rng.randint(0, n)
    return result
