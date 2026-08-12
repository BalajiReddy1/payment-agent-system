"""Statistical analysis used by detection and evaluation."""

from src.analysis.statistics import (
    ComparisonResult,
    CusumDetector,
    RateEstimate,
    betainc,
    beta_quantile,
    compare_proportions,
    estimate_rate,
    normal_cdf,
    probability_below,
)

__all__ = [
    'ComparisonResult', 'CusumDetector', 'RateEstimate',
    'betainc', 'beta_quantile', 'compare_proportions',
    'estimate_rate', 'normal_cdf', 'probability_below',
]
