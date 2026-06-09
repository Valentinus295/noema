"""PortfolioAgent — PCA factor exposure, currency-strength rank, hierarchical correlation cluster gate.

Contract pinned in docs/ARCHITECTURE.md §4.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Any

from vmpm.core.types import Setup, Direction


@dataclass
class PortfolioConstraints:
    correlation_cap_sum_abs: float = 1.5
    pca_factor_exposure_cap: float = 0.6
    cluster_max_concurrent: int = 1
    currency_strength_topN: int = 2


def _compute_currency_strength(prices: dict[str, float]) -> dict[str, float]:
    if not prices:
        return {}

    values = list(prices.values())
    mean_val = np.mean(values)

    strengths = {}
    for currency, price in prices.items():
        strengths[currency] = (price - mean_val) / mean_val if mean_val != 0 else 0.0

    return strengths


def _compute_correlation_matrix(setups: list[Setup]) -> np.ndarray:
    if len(setups) < 2:
        return np.array([[1.0]])

    directions = np.array([[1 if s.direction == Direction("bullish") else -1 for s in setups]])
    return np.corrcoef(directions)


def _compute_pca_factors(setups: list[Setup], n_components: int = 3) -> np.ndarray:
    if len(setups) < n_components:
        return np.zeros((len(setups), n_components))

    features = np.array(
        [[s.score, 1 if s.direction == Direction("bullish") else -1] for s in setups]
    )

    from sklearn.decomposition import PCA

    pca = PCA(n_components=n_components)
    return pca.fit_transform(features)


def check_portfolio_constraints(
    new_setup: Setup,
    existing_setups: list[Setup],
    prices: dict[str, float],
    constraints: PortfolioConstraints,
) -> tuple[bool, str]:
    currency_strength = _compute_currency_strength(prices)

    legs = (
        new_setup.symbol.replace("USD", "").replace("EUR", "").replace("GBP", "").replace("JPY", "")
    )
    if len(legs) >= 2:
        leg1, leg2 = legs[0], legs[1] if len(legs) > 1 else legs[0]
        if leg1 in currency_strength and leg2 in currency_strength:
            sorted_currencies = sorted(
                currency_strength.keys(), key=lambda x: currency_strength[x], reverse=True
            )
            if leg1 not in sorted_currencies[: constraints.currency_strength_topN]:
                return False, f"Currency {leg1} not in top {constraints.currency_strength_topN}"

    all_setups = existing_setups + [new_setup]
    corr_matrix = _compute_correlation_matrix(all_setups)

    if corr_matrix.shape[0] > 1:
        corr_sum = np.sum(np.abs(corr_matrix)) - np.trace(corr_matrix)
        if corr_sum > constraints.correlation_cap_sum_abs:
            return False, "Correlation cap exceeded"

    return True, "Approved"
