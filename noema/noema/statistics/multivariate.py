"""Multivariate statistical methods.

PCA, ICA, factor decomposition, correlation analysis, Mahalanobis distance.
Every function returns typed dataclasses with statistics and diagnostics.

Uses: numpy, scipy, scikit-learn
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats
from sklearn.decomposition import PCA, FastICA


@dataclass
class PCA_Result:
    """Principal Component Analysis results.

    Attributes:
        components: Principal component loadings (n_features × n_components).
        explained_variance: Variance explained by each PC.
        explained_variance_ratio: Proportion of variance explained.
        cumulative_variance_ratio: Cumulative proportion explained.
        eigenvalues: Eigenvalues of the covariance matrix.
        n_components: Number of components retained.
        n_samples: Number of observations.
        n_features: Number of original variables.
        feature_names: Optional names of features.
    """
    components: np.ndarray = field(default_factory=lambda: np.array([]))
    explained_variance: np.ndarray = field(default_factory=lambda: np.array([]))
    explained_variance_ratio: np.ndarray = field(default_factory=lambda: np.array([]))
    cumulative_variance_ratio: np.ndarray = field(default_factory=lambda: np.array([]))
    eigenvalues: np.ndarray = field(default_factory=lambda: np.array([]))
    n_components: int = 0
    n_samples: int = 0
    n_features: int = 0
    feature_names: list[str] = field(default_factory=list)

    @property
    def kaiser_criterion_components(self) -> int:
        """Number of components with eigenvalue > 1 (Kaiser criterion)."""
        return int(np.sum(self.eigenvalues > 1.0))

    @property
    def components_for_variance(self, threshold: float = 0.90) -> int:
        """Number of components needed to explain `threshold` variance."""
        return int(np.searchsorted(self.cumulative_variance_ratio, threshold) + 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_components": self.n_components,
            "n_samples": self.n_samples,
            "n_features": self.n_features,
            "explained_variance": self.explained_variance.tolist(),
            "explained_variance_ratio": self.explained_variance_ratio.tolist(),
            "cumulative_variance_ratio": self.cumulative_variance_ratio.tolist(),
            "kaiser_criterion_components": self.kaiser_criterion_components,
        }


@dataclass
class FactorResult:
    """Factor decomposition results.

    Attributes:
        loadings: Factor loading matrix (n_features × n_factors).
        communalities: Proportion of variance explained for each variable.
        uniqueness: Proportion of unique variance for each variable.
        eigenvalues: Eigenvalues.
        factor_scores: Optional factor scores (n_samples × n_factors).
        n_factors: Number of factors extracted.
        n_samples: Number of observations.
        n_features: Number of variables.
        feature_names: Optional feature names.
        method: Extraction method used.
    """
    loadings: np.ndarray = field(default_factory=lambda: np.array([]))
    communalities: np.ndarray = field(default_factory=lambda: np.array([]))
    uniqueness: np.ndarray = field(default_factory=lambda: np.array([]))
    eigenvalues: np.ndarray = field(default_factory=lambda: np.array([]))
    factor_scores: Optional[np.ndarray] = None
    n_factors: int = 0
    n_samples: int = 0
    n_features: int = 0
    feature_names: list[str] = field(default_factory=list)
    method: str = "pca"

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_factors": self.n_factors,
            "n_features": self.n_features,
            "communalities": self.communalities.tolist(),
            "uniqueness": self.uniqueness.tolist(),
            "method": self.method,
        }


def perform_pca(
    data: np.ndarray,
    n_components: Optional[int] = None,
    feature_names: Optional[list[str]] = None,
    standardize: bool = True,
) -> PCA_Result:
    """Perform Principal Component Analysis.

    Args:
        data: 2-D array (n_samples × n_features).
        n_components: Number of components. If None, retains all.
        feature_names: Optional names for features.
        standardize: If True, standardize to zero mean and unit variance.

    Returns:
        PCA_Result with components, variance explained, eigenvalues.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"Expected 2-D array, got {data.ndim}-D")

    n_samples, n_features = data.shape

    if standardize:
        mean = np.mean(data, axis=0)
        std = np.std(data, axis=0, ddof=1)
        std[std < 1e-10] = 1e-10
        data = (data - mean) / std

    n_comp = n_components or min(n_samples, n_features)
    n_comp = min(n_comp, min(n_samples, n_features))

    pca = PCA(n_components=n_comp)
    pca.fit(data)

    return PCA_Result(
        components=pca.components_,
        explained_variance=pca.explained_variance_,
        explained_variance_ratio=pca.explained_variance_ratio_,
        cumulative_variance_ratio=np.cumsum(pca.explained_variance_ratio_),
        eigenvalues=pca.explained_variance_,
        n_components=n_comp,
        n_samples=n_samples,
        n_features=n_features,
        feature_names=feature_names or [f"feature_{i}" for i in range(n_features)],
    )


def perform_ica(
    data: np.ndarray,
    n_components: Optional[int] = None,
    feature_names: Optional[list[str]] = None,
    max_iter: int = 200,
    random_state: Optional[int] = None,
) -> PCA_Result:
    """Perform Independent Component Analysis.

    Args:
        data: 2-D array (n_samples × n_features).
        n_components: Number of independent components.
        feature_names: Optional feature names.
        max_iter: Maximum iterations for ICA.
        random_state: Random seed for reproducibility.

    Returns:
        PCA_Result with ICA mixing matrix as components.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"Expected 2-D array, got {data.ndim}-D")

    n_samples, n_features = data.shape
    n_comp = n_components or n_features
    n_comp = min(n_comp, n_features)

    ica = FastICA(n_components=n_comp, max_iter=max_iter, random_state=random_state)
    ica.fit(data)

    # ICA doesn't provide variance ratios — compute via reconstruction
    S = ica.transform(data)
    # Variance of each IC
    var_ic = np.var(S, axis=0)
    var_total = np.sum(var_ic)

    return PCA_Result(
        components=ica.mixing_.T,  # (n_components, n_features)
        explained_variance=var_ic,
        explained_variance_ratio=var_ic / var_total if var_total > 0 else var_ic,
        cumulative_variance_ratio=np.cumsum(var_ic / var_total if var_total > 0 else var_ic),
        eigenvalues=var_ic,
        n_components=n_comp,
        n_samples=n_samples,
        n_features=n_features,
        feature_names=feature_names or [f"feature_{i}" for i in range(n_features)],
    )


def factor_decomposition(
    data: np.ndarray,
    n_factors: Optional[int] = None,
    feature_names: Optional[list[str]] = None,
    method: str = "pca",
    rotation: Optional[str] = "varimax",
) -> FactorResult:
    """Perform factor decomposition.

    Identifies latent factors underlying observed variables.
    Useful for decomposing currency returns into common factors.

    Args:
        data: 2-D array (n_samples × n_features).
        n_factors: Number of factors to extract. If None, uses Kaiser criterion.
        feature_names: Optional feature names.
        method: Extraction method ("pca", "ml").
        rotation: Rotation method ("varimax", "quartimax", None).

    Returns:
        FactorResult with loadings, communalities, eigenvalues.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"Expected 2-D array, got {data.ndim}-D")

    n_samples, n_features = data.shape

    # Standardize
    mean = np.mean(data, axis=0)
    std = np.std(data, axis=0, ddof=1)
    std[std < 1e-10] = 1e-10
    z_data = (data - mean) / std

    # Compute correlation matrix and eigenvalues
    corr = np.corrcoef(z_data.T)
    eigenvalues, eigenvectors = np.linalg.eigh(corr)
    # Sort descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    # Determine number of factors
    if n_factors is None:
        n_factors = int(np.sum(eigenvalues > 1.0))
        n_factors = max(n_factors, 1)
    n_factors = min(n_factors, n_features)

    # Unrotated loadings (sqrt(eigenvalue) * eigenvector)
    loadings = eigenvectors[:, :n_factors] * np.sqrt(eigenvalues[:n_factors])

    # Rotation (varimax)
    if rotation == "varimax" and n_factors > 1:
        loadings = _varimax_rotation(loadings)

    # Communalities and uniqueness
    communalities = np.sum(loadings ** 2, axis=1)
    uniqueness = 1.0 - communalities

    # Factor scores (Bartlett method)
    try:
        # Bartlett scores: F = (L' R^{-1} L)^{-1} L' R^{-1} z
        R_inv = np.linalg.inv(corr + np.eye(n_features) * 1e-6)
        L_R_inv = loadings.T @ R_inv
        M = np.linalg.inv(L_R_inv @ loadings + np.eye(n_factors) * 1e-6)
        factor_scores = z_data @ R_inv @ loadings @ M
    except np.linalg.LinAlgError:
        factor_scores = None

    return FactorResult(
        loadings=loadings,
        communalities=communalities,
        uniqueness=uniqueness,
        eigenvalues=eigenvalues[:n_factors],
        factor_scores=factor_scores,
        n_factors=n_factors,
        n_samples=n_samples,
        n_features=n_features,
        feature_names=feature_names or [f"var_{i}" for i in range(n_features)],
        method=method,
    )


def _varimax_rotation(loadings: np.ndarray, max_iter: int = 500, tol: float = 1e-6) -> np.ndarray:
    """Varimax rotation for factor loadings."""
    n, k = loadings.shape
    rot_loadings = loadings.copy()

    for _ in range(max_iter):
        # Normalize
        h = np.sqrt(np.sum(rot_loadings ** 2, axis=1))
        h[h < 1e-10] = 1e-10
        U = rot_loadings / h[:, np.newaxis]

        # Gradient of varimax criterion
        U_sq = U ** 2
        U_cubed = U ** 3
        G = n * (U_cubed - U * np.mean(U_sq, axis=0, keepdims=True))

        # SVD of U^T G
        M = U.T @ G
        u, s, vt = np.linalg.svd(M)

        # Rotation matrix
        R = u @ vt

        # Update
        old_loadings = rot_loadings.copy()
        rot_loadings = rot_loadings @ R

        # Check convergence
        if np.max(np.abs(rot_loadings - old_loadings)) < tol:
            break

    return rot_loadings


def correlation_matrix(
    data: np.ndarray,
    feature_names: Optional[list[str]] = None,
    method: str = "pearson",
) -> dict[str, Any]:
    """Compute correlation matrix with significance values.

    Args:
        data: 2-D array (n_samples × n_features).
        feature_names: Optional feature names.
        method: "pearson" (linear), "spearman" (rank), or "kendall" (tau).

    Returns:
        Dictionary with 'correlation_matrix', 'p_values', 'feature_names'.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"Expected 2-D array, got {data.ndim}-D")

    n_samples, n_features = data.shape
    corr = np.zeros((n_features, n_features))
    p_vals = np.zeros((n_features, n_features))

    for i in range(n_features):
        for j in range(n_features):
            if i == j:
                corr[i, j] = 1.0
                p_vals[i, j] = 0.0
            elif j > i:
                if method == "spearman":
                    r, p = scipy_stats.spearmanr(data[:, i], data[:, j])
                elif method == "kendall":
                    r, p = scipy_stats.kendalltau(data[:, i], data[:, j])
                else:
                    r, p = scipy_stats.pearsonr(data[:, i], data[:, j])
                corr[i, j] = corr[j, i] = float(r)
                p_vals[i, j] = p_vals[j, i] = float(p)

    return {
        "correlation_matrix": corr.tolist(),
        "p_values": p_vals.tolist(),
        "feature_names": feature_names or [f"var_{i}" for i in range(n_features)],
        "n_samples": n_samples,
        "method": method,
    }


def partial_correlation(
    data: np.ndarray,
    feature_names: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Compute partial correlation matrix (conditioning on all other variables).

    Args:
        data: 2-D array (n_samples × n_features).
        feature_names: Optional feature names.

    Returns:
        Dictionary with 'partial_correlation_matrix', 'precision_matrix'.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"Expected 2-D array, got {data.ndim}-D")

    n_samples, n_features = data.shape
    names = feature_names or [f"var_{i}" for i in range(n_features)]

    # Partial correlation = -precision[i,j] / sqrt(precision[i,i] * precision[j,j])
    corr = np.corrcoef(data.T)
    reg = 1e-6 * np.eye(n_features)
    precision = np.linalg.inv(corr + reg)

    partial_corr = np.zeros((n_features, n_features))
    for i in range(n_features):
        for j in range(n_features):
            if i == j:
                partial_corr[i, j] = 1.0
            else:
                partial_corr[i, j] = -precision[i, j] / np.sqrt(precision[i, i] * precision[j, j])

    return {
        "partial_correlation_matrix": partial_corr.tolist(),
        "precision_matrix": precision.tolist(),
        "feature_names": names,
        "n_samples": n_samples,
    }


def mahalanobis_distance(
    data: np.ndarray,
    point: Optional[np.ndarray] = None,
) -> dict[str, Any]:
    """Compute Mahalanobis distances for all observations.

    Multivariate distance measure accounting for covariance structure.
    Useful for outlier detection in multi-dimensional feature spaces.

    Args:
        data: 2-D array (n_samples × n_features).
        point: Optional reference point. If None, uses mean of data.

    Returns:
        Dictionary with 'distances', 'mean', 'covariance', 'threshold_99'.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"Expected 2-D array, got {data.ndim}-D")

    n_samples, n_features = data.shape
    mean = np.mean(data, axis=0) if point is None else np.asarray(point)
    cov = np.cov(data, rowvar=False)

    # Regularize covariance for inversion
    reg = 1e-8 * np.eye(n_features)
    try:
        cov_inv = np.linalg.inv(cov + reg)
    except np.linalg.LinAlgError:
        cov_inv = np.linalg.pinv(cov)

    diff = data - mean
    distances = np.sqrt(np.sum(diff @ cov_inv * diff, axis=1))

    # 99% threshold (chi-square with n_features df)
    threshold_99 = float(np.sqrt(scipy_stats.chi2.ppf(0.99, n_features)))

    return {
        "distances": distances.tolist(),
        "mean": mean.tolist(),
        "covariance": cov.tolist(),
        "threshold_99_percentile": threshold_99,
        "n_outliers_99": int(np.sum(distances > threshold_99)),
        "n_samples": n_samples,
        "n_features": n_features,
    }
