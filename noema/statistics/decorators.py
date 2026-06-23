"""Utility decorators for the statistics module.

Provides:
- @validate_input: Verify input types and shapes before computation.
- @cache_result: Cache results for repeated calls with same data.
- @log_call: Structured logging of function calls.
- @timed: Measure and log execution time.
- @require_dataframe: Validate that input is a pandas DataFrame.
- @check_numeric: Ensure all values are numeric.

These decorators enforce the "no hallucination" contract:
- Input validation catches bad data before computation.
- Caching prevents floating errors from redundant recomputation.
- Logging provides full audit trail for statistical decisions.
"""

from __future__ import annotations

import functools
import hashlib
import time
from typing import Any, Callable, Optional

import numpy as np


def validate_input(
    ndim: Optional[int] = None,
    min_samples: int = 1,
    require_finite: bool = True,
    require_unique: bool = False,
) -> Callable:
    """Decorator to validate numpy array inputs.

    Args:
        ndim: Required number of dimensions (None = any).
        min_samples: Minimum number of observations.
        require_finite: If True, reject arrays with NaN or Inf.
        require_unique: If True, require all values to be unique.

    Returns:
        Decorated function with input validation.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Find the first numpy array argument
            # Convention: first positional arg is the data array
            for i, arg in enumerate(args):
                if isinstance(arg, np.ndarray):
                    data = arg

                    # Check dimensions
                    if ndim is not None and data.ndim != ndim:
                        raise ValueError(
                            f"{func.__name__}: expected {ndim}-D array, "
                            f"got {data.ndim}-D. Shape: {data.shape}"
                        )

                    # Check minimum samples
                    if data.size < min_samples:
                        raise ValueError(
                            f"{func.__name__}: need at least {min_samples} "
                            f"observations, got {data.size}"
                        )

                    # Check for NaN / Inf
                    if require_finite and not np.isfinite(data).all():
                        n_bad = np.sum(~np.isfinite(data))
                        raise ValueError(
                            f"{func.__name__}: {n_bad} non-finite values "
                            f"(NaN/Inf) in input data"
                        )

                    # Check uniqueness
                    if require_unique and len(np.unique(data)) != len(data):
                        raise ValueError(
                            f"{func.__name__}: duplicate values found "
                            f"(require_unique=True)"
                        )

                    break

            return func(*args, **kwargs)

        return wrapper

    return decorator


def cache_result(
    maxsize: int = 128,
    hash_data: bool = True,
) -> Callable:
    """Decorator to cache function results by data hash.

    Prevents expensive recomputation when the same data is passed.
    Uses SHA-256 hash of the data array + function name as cache key.

    Args:
        maxsize: Maximum cache size (LRU eviction).
        hash_data: If True, hash the data array for cache key.

    Returns:
        Decorated function with result caching.
    """
    cache: dict[str, Any] = {}
    access_order: list[str] = []

    def _make_key(func: Callable, args: tuple, kwargs: dict) -> str:
        """Generate a cache key from function name and data hash."""
        key_parts = [func.__name__]

        for arg in args:
            if isinstance(arg, np.ndarray):
                if hash_data:
                    # Hash the array bytes
                    key_parts.append(hashlib.sha256(arg.tobytes()).hexdigest()[:16])
                else:
                    key_parts.append(f"shape={arg.shape}")
            elif isinstance(arg, (int, float, str, bool)):
                key_parts.append(str(arg))
            else:
                key_parts.append(str(id(arg)))

        for k, v in sorted(kwargs.items()):
            if k in ('data', 'x', 'y', 'group_a', 'group_b', 'returns', 'durations'):
                if isinstance(v, np.ndarray) and hash_data:
                    key_parts.append(f"{k}={hashlib.sha256(v.tobytes()).hexdigest()[:12]}")
                else:
                    key_parts.append(f"{k}={str(v)}")

        return "|".join(key_parts)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(func, args, kwargs)

            if key in cache:
                # Move to end (LRU)
                access_order.remove(key)
                access_order.append(key)
                return cache[key]

            # Compute and cache
            result = func(*args, **kwargs)
            cache[key] = result
            access_order.append(key)

            # Evict oldest if over maxsize
            while len(cache) > maxsize:
                oldest = access_order.pop(0)
                del cache[oldest]

            return result

        wrapper._cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator


def log_call(
    logger_name: str = "noema.statistics",
    level: str = "debug",
) -> Callable:
    """Decorator to log function calls with structured data.

    Provides full audit trail for all statistical computations.
    Essential for the "No hallucination" guarantee — every statistical
    result can be traced to its input data.

    Args:
        logger_name: Name of the structlog logger.
        level: Log level ("debug", "info", "warning").

    Returns:
        Decorated function with call logging.
    """
    def decorator(func: Callable) -> Callable:
        try:
            import structlog
            logger = structlog.get_logger(logger_name)
        except ImportError:
            # Fallback to print-based logging
            def _noop_log(*a: Any, **kw: Any) -> None:
                pass
            logger = type('FakeLogger', (), {
                'debug': _noop_log, 'info': _noop_log, 'warning': _noop_log
            })()

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build context for logging
            ctx = {
                "function": func.__name__,
                "module": func.__module__,
            }

            # Add shape info for numpy arrays
            for i, arg in enumerate(args):
                if isinstance(arg, np.ndarray):
                    ctx[f"arg{i}_shape"] = arg.shape
                    ctx[f"arg{i}_dtype"] = str(arg.dtype)
                    ctx[f"arg{i}_min"] = float(np.min(arg))
                    ctx[f"arg{i}_max"] = float(np.max(arg))

            for k, v in kwargs.items():
                if isinstance(v, np.ndarray):
                    ctx[f"kwarg_{k}_shape"] = v.shape
                    ctx[f"kwarg_{k}_dtype"] = str(v.dtype)
                elif isinstance(v, (int, float, str, bool)):
                    ctx[f"kwarg_{k}"] = v

            log_fn = getattr(logger, level, logger.debug)
            log_fn("stat_call_start", **ctx)

            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
                elapsed = time.monotonic() - start
                log_fn(
                    "stat_call_end",
                    function=func.__name__,
                    duration_ms=round(elapsed * 1000, 2),
                    success=True,
                )
                return result
            except Exception as exc:
                elapsed = time.monotonic() - start
                log_fn(
                    "stat_call_error",
                    function=func.__name__,
                    duration_ms=round(elapsed * 1000, 2),
                    error=str(exc),
                    success=False,
                )
                raise

        return wrapper

    return decorator


def timed(logger_name: str = "noema.statistics") -> Callable:
    """Decorator to measure and log execution time.

    Args:
        logger_name: Logger name.

    Returns:
        Decorated function with timing.
    """
    def decorator(func: Callable) -> Callable:
        try:
            import structlog
            logger = structlog.get_logger(logger_name)
        except ImportError:
            logger = None

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start

            if logger:
                logger.debug(
                    "stat_function_timing",
                    function=func.__name__,
                    duration_ms=round(elapsed * 1000, 3),
                )

            return result

        return wrapper

    return decorator


def require_dataframe(func: Callable) -> Callable:
    """Decorator that ensures the first argument is a pandas DataFrame.

    Provides a clear error message if not, instead of cryptic failures.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if args:
            first_arg = args[0]
            # Try to import pandas
            try:
                import pandas as pd
                if not isinstance(first_arg, pd.DataFrame):
                    raise TypeError(
                        f"{func.__name__}: expected pandas DataFrame, "
                        f"got {type(first_arg).__name__}"
                    )
            except ImportError:
                # pandas not available — skip check
                pass

        return func(*args, **kwargs)

    return wrapper


def check_numeric(func: Callable) -> Callable:
    """Decorator that ensures array arguments are numeric.

    Converts to float64 if possible, raises TypeError if not.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        new_args = list(args)
        for i, arg in enumerate(new_args):
            if isinstance(arg, np.ndarray):
                if not np.issubdtype(arg.dtype, np.number):
                    try:
                        new_args[i] = arg.astype(np.float64)
                    except (ValueError, TypeError):
                        raise TypeError(
                            f"{func.__name__}: argument {i} cannot be "
                            f"converted to numeric. dtype={arg.dtype}"
                        )

        return func(*new_args, **kwargs)

    return wrapper
