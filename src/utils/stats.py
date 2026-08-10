"""
Small statistics helpers.

The agent core deliberately depends on nothing outside the standard library so
it can be imported, tested and replayed anywhere. These few functions are all
the numeric machinery the observer and learner need.
"""

import math
from typing import Sequence


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean, 0.0 for an empty sequence."""
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def percentile(values: Sequence[float], p: float) -> float:
    """
    Linear-interpolated percentile, matching numpy.percentile's default method.

    Args:
        values: Sample values (need not be sorted).
        p: Percentile to compute, 0-100.

    Returns:
        The percentile value, or 0.0 for an empty sample.
    """
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (len(ordered) - 1) * (p / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    return float(ordered[lower] * (upper - rank) + ordered[upper] * (rank - lower))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Constrain a value to [low, high]."""
    return max(low, min(high, value))
