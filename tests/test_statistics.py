"""
Statistics.

Two kinds of test here. The numerical functions are checked against
analytically known values, because a subtly wrong incomplete beta would
produce confident nonsense rather than an obvious failure. The detectors are
checked behaviourally - false alarm rate on healthy traffic, detection delay
on degraded traffic - because those are the properties that decide whether
the agent is trusted or ignored.
"""

import random

import pytest

from src.analysis.statistics import (
    CusumDetector,
    betainc,
    beta_quantile,
    compare_proportions,
    estimate_rate,
    normal_cdf,
    probability_below,
    _z_for_confidence,
)


# ── Numerics ─────────────────────────────────────────────────────────────────

def test_betainc_matches_analytic_forms():
    """I_x(1,1)=x, I_x(2,1)=x^2, I_x(1,2)=2x-x^2, I_x(3,1)=x^3."""
    for x in (0.01, 0.05, 0.2, 0.5, 0.77, 0.95, 0.999):
        assert abs(betainc(1, 1, x) - x) < 1e-12
        assert abs(betainc(2, 1, x) - x ** 2) < 1e-12
        assert abs(betainc(1, 2, x) - (2 * x - x * x)) < 1e-12
        assert abs(betainc(3, 1, x) - x ** 3) < 1e-12


def test_betainc_symmetry():
    """I_x(a,b) = 1 - I_{1-x}(b,a) must hold, or the branch switch is wrong."""
    for a, b in ((2.5, 4.5), (0.5, 0.5), (30.0, 3.0), (1.2, 8.8)):
        for x in (0.05, 0.3, 0.5, 0.8, 0.97):
            assert abs(betainc(a, b, x) - (1 - betainc(b, a, 1 - x))) < 1e-10


def test_betainc_boundaries_and_monotonicity():
    assert betainc(2, 3, 0.0) == 0.0
    assert betainc(2, 3, 1.0) == 1.0

    previous = 0.0
    for i in range(1, 100):
        value = betainc(2, 3, i / 100)
        assert value >= previous
        previous = value


def test_beta_quantile_inverts_betainc():
    for a, b in ((2, 5), (30, 3), (0.5, 0.5), (19, 1)):
        for q in (0.025, 0.1, 0.5, 0.9, 0.975):
            x = beta_quantile(a, b, q)
            assert abs(betainc(a, b, x) - q) < 1e-6


def test_normal_cdf_known_values():
    assert abs(normal_cdf(0.0) - 0.5) < 1e-12
    assert abs(normal_cdf(1.96) - 0.975) < 1e-4
    assert abs(normal_cdf(-1.96) - 0.025) < 1e-4


def test_critical_z_values():
    assert abs(_z_for_confidence(0.95) - 1.95996) < 1e-4
    assert abs(_z_for_confidence(0.99) - 2.57583) < 1e-4


# ── Rate estimation ──────────────────────────────────────────────────────────

def test_more_evidence_narrows_the_interval():
    small = estimate_rate(3, 1)
    large = estimate_rate(300, 100)

    assert abs(small.observed - large.observed) < 1e-9
    assert large.width < small.width


def test_identical_observed_rate_gives_different_conclusions():
    """
    The whole point of estimating rather than thresholding: 3/4 and 300/400
    are the same observed rate and completely different evidence.
    """
    weak = probability_below(3, 1, threshold=0.85)
    moderate = probability_below(30, 10, threshold=0.85)
    strong = probability_below(300, 100, threshold=0.85)

    assert weak < 0.5          # not enough evidence to conclude anything
    assert 0.5 < moderate < 0.95
    assert strong > 0.99


def test_posterior_is_pulled_toward_the_prior_when_evidence_is_thin():
    estimate = estimate_rate(0, 2, prior_mean=0.95, prior_strength=20)
    # Two failures should not convince us the rate is zero
    assert estimate.mean > 0.8
    assert estimate.observed == 0.0


def test_posterior_follows_the_data_when_evidence_is_thick():
    estimate = estimate_rate(200, 800, prior_mean=0.95, prior_strength=20)
    assert abs(estimate.mean - 0.2) < 0.02


def test_credible_interval_brackets_the_mean():
    estimate = estimate_rate(40, 10)
    assert estimate.lower < estimate.mean < estimate.upper
    assert 0.0 <= estimate.lower and estimate.upper <= 1.0


# ── Comparison ───────────────────────────────────────────────────────────────

def test_compare_proportions_detects_a_real_difference():
    result = compare_proportions(900, 1000, 800, 1000)

    assert abs(result.difference - 0.1) < 1e-9
    assert result.significant
    assert result.p_value < 0.001
    assert result.lower > 0


def test_compare_proportions_is_not_fooled_by_noise():
    result = compare_proportions(95, 100, 93, 100)

    assert not result.significant
    assert result.p_value > 0.05
    assert result.lower < 0 < result.upper


def test_compare_proportions_needs_both_groups():
    assert compare_proportions(10, 10, 0, 0) is None
    assert compare_proportions(0, 0, 10, 10) is None


def test_compare_proportions_handles_identical_groups():
    result = compare_proportions(90, 100, 90, 100)
    assert result.difference == 0.0
    assert not result.significant


def test_comparison_describes_itself():
    result = compare_proportions(900, 1000, 800, 1000)
    text = result.describe()
    assert 'improved' in text and 'CI' in text and 'p=' in text


# ── Sequential detection ─────────────────────────────────────────────────────

def test_cusum_rejects_incoherent_parameters():
    with pytest.raises(ValueError):
        CusumDetector(baseline=0.9, degraded_rate=0.95)
    with pytest.raises(ValueError):
        CusumDetector(baseline=0.9, degraded_rate=0.0)


def test_cusum_stays_quiet_on_healthy_traffic():
    """
    False alarm budget. A payment agent that cries wolf gets switched off, so
    this is the property worth protecting.
    """
    alarms = 0
    trials = 60
    for trial in range(trials):
        random.seed(4000 + trial)
        detector = CusumDetector(baseline=0.95, degraded_rate=0.90)
        for _ in range(2000):
            detector.update(random.random() < 0.95)
            if detector.alarmed:
                alarms += 1
                break

    assert alarms / trials < 0.15, f"{alarms}/{trials} false alarms is too many"


def test_cusum_detects_a_sustained_degradation():
    delays = []
    for trial in range(40):
        random.seed(5000 + trial)
        detector = CusumDetector(baseline=0.95, degraded_rate=0.90)
        for i in range(4000):
            detector.update(random.random() < 0.80)
            if detector.alarmed:
                delays.append(i + 1)
                break

    assert len(delays) == 40, "every degraded run should eventually alarm"
    assert sum(delays) / len(delays) < 250


def test_cusum_reports_where_the_excursion_started():
    random.seed(6001)
    detector = CusumDetector(baseline=0.95, degraded_rate=0.90)

    for _ in range(300):
        detector.update(True)
    assert not detector.alarmed

    for _ in range(200):
        detector.update(random.random() < 0.4)

    assert detector.alarmed
    assert detector.changepoint is not None
    # The shift began after the healthy prefix
    assert detector.changepoint > 300


def test_cusum_clears_after_recovery():
    """Not sticky: a healed issuer must stop being reported as degraded."""
    detector = CusumDetector(baseline=0.95, degraded_rate=0.90)

    for _ in range(60):
        detector.update(False)
    assert detector.alarmed

    for _ in range(2000):
        detector.update(True)

    assert not detector.alarmed
    assert detector.changepoint is None


def test_cusum_statistic_never_goes_negative():
    detector = CusumDetector(baseline=0.95, degraded_rate=0.90)
    for _ in range(500):
        detector.update(True)
    assert detector.state.statistic >= 0.0
