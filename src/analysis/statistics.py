"""
Statistics for detection and evaluation.

Everything here is standard library only, so the agent core stays
dependency-free and testable anywhere. The functions are the small number of
things the agent genuinely needs:

- Beta-binomial estimation of a success rate, with credible intervals. A
  success rate measured over 12 transactions and one measured over 12,000 are
  not the same evidence, and a bare threshold cannot tell them apart. This is
  what lets the agent say "probably degraded" instead of "below 0.8".
- CUSUM changepoint detection, for noticing that a rate has *shifted* rather
  than that a single window happened to look bad.
- A two-proportion test, for measuring whether an intervention actually helped
  when compared against a concurrent control group.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# Continued fraction convergence controls (Numerical Recipes conventions)
_MAX_ITERATIONS = 300
_EPSILON = 3.0e-12
_TINY = 1.0e-30


def log_beta(a: float, b: float) -> float:
    """Natural log of the Beta function B(a, b)."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """
    Continued fraction for the incomplete beta function, via modified Lentz.

    Converges quickly for x < (a+1)/(a+b+2); callers use the symmetry
    I_x(a,b) = 1 - I_{1-x}(b,a) to stay on that side.
    """
    qab, qap, qam = a + b, a + 1.0, a - 1.0

    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _TINY:
        d = _TINY
    d = 1.0 / d
    result = d

    for m in range(1, _MAX_ITERATIONS + 1):
        m2 = 2 * m

        # Even step
        numerator = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + numerator / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        result *= d * c

        # Odd step
        numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + numerator / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        result *= delta

        if abs(delta - 1.0) < _EPSILON:
            break

    return result


def betainc(a: float, b: float, x: float) -> float:
    """
    Regularized incomplete beta function I_x(a, b).

    Equivalently: the CDF of a Beta(a, b) distribution evaluated at x.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )

    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def beta_quantile(a: float, b: float, q: float, tolerance: float = 1e-9) -> float:
    """
    Inverse Beta CDF, by bisection.

    Bisection rather than Newton because it cannot diverge, and a few dozen
    iterations of a cheap function is irrelevant next to a payment round trip.
    """
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0

    low, high = 0.0, 1.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if betainc(a, b, mid) < q:
            low = mid
        else:
            high = mid
        if high - low < tolerance:
            break

    return (low + high) / 2.0


def normal_cdf(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


@dataclass(frozen=True)
class RateEstimate:
    """
    A success rate estimated from evidence, not just counted.

    `mean` is the posterior mean; the interval expresses how much the sample
    size justifies believing it.
    """

    successes: int
    failures: int
    mean: float
    lower: float
    upper: float
    credible_mass: float

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def width(self) -> float:
        """Interval width - how uncertain the estimate still is."""
        return self.upper - self.lower

    @property
    def observed(self) -> float:
        """The raw observed rate, ignoring the prior."""
        return self.successes / self.total if self.total else 0.0


def estimate_rate(
    successes: int,
    failures: int,
    prior_mean: float = 0.95,
    prior_strength: float = 20.0,
    credible_mass: float = 0.95,
) -> RateEstimate:
    """
    Beta-binomial estimate of a success rate.

    Args:
        successes: Successful transactions observed.
        failures: Failed transactions observed.
        prior_mean: The rate believed before observing anything - normally the
            learned baseline for this issuer or method.
        prior_strength: How much evidence the prior is worth, in transactions.
            20 means "the prior is worth about 20 observations", so around 60
            real observations dominate it.
        credible_mass: Width of the reported interval.

    Returns:
        A RateEstimate whose interval narrows as evidence accumulates.
    """
    prior_alpha = max(prior_mean * prior_strength, 1e-6)
    prior_beta = max((1.0 - prior_mean) * prior_strength, 1e-6)

    alpha = prior_alpha + successes
    beta = prior_beta + failures

    tail = (1.0 - credible_mass) / 2.0

    return RateEstimate(
        successes=successes,
        failures=failures,
        mean=alpha / (alpha + beta),
        lower=beta_quantile(alpha, beta, tail),
        upper=beta_quantile(alpha, beta, 1.0 - tail),
        credible_mass=credible_mass,
    )


def probability_below(
    successes: int,
    failures: int,
    threshold: float,
    prior_mean: float = 0.95,
    prior_strength: float = 20.0,
) -> float:
    """
    P(true success rate < threshold), given the evidence.

    This is the number the agent should act on. "3 failures out of 4" and
    "300 failures out of 400" produce very different answers here while
    producing an identical observed rate.
    """
    prior_alpha = max(prior_mean * prior_strength, 1e-6)
    prior_beta = max((1.0 - prior_mean) * prior_strength, 1e-6)

    return betainc(prior_alpha + successes, prior_beta + failures, threshold)


@dataclass(frozen=True)
class ComparisonResult:
    """Outcome of comparing two proportions."""

    treatment_rate: float
    control_rate: float
    difference: float
    lower: float
    upper: float
    z_score: float
    p_value: float
    treatment_n: int
    control_n: int

    @property
    def significant(self) -> bool:
        """True if the interval excludes zero at the requested confidence."""
        return self.lower > 0.0 or self.upper < 0.0

    def describe(self) -> str:
        direction = "improved" if self.difference > 0 else "reduced"
        verdict = "significant" if self.significant else "not significant"
        return (
            f"{direction} success rate by {abs(self.difference):.1%} "
            f"(95% CI {self.lower:+.1%} to {self.upper:+.1%}, "
            f"p={self.p_value:.3f}, {verdict}; "
            f"n={self.treatment_n} vs {self.control_n})"
        )


def compare_proportions(
    treatment_successes: int,
    treatment_total: int,
    control_successes: int,
    control_total: int,
    confidence: float = 0.95,
) -> Optional[ComparisonResult]:
    """
    Two-proportion z-test with a confidence interval on the difference.

    Used to answer "did the intervention help", by comparing the treated
    population against a concurrent control rather than against the same
    population before the intervention. Before/after comparisons are
    confounded by everything else that changed in the meantime - not least
    the incident resolving on its own.

    Returns:
        None when either group has no observations.
    """
    if treatment_total <= 0 or control_total <= 0:
        return None

    p_treatment = treatment_successes / treatment_total
    p_control = control_successes / control_total
    difference = p_treatment - p_control

    # Pooled estimate for the test statistic
    pooled = (treatment_successes + control_successes) / (treatment_total + control_total)
    pooled_variance = pooled * (1.0 - pooled) * (1.0 / treatment_total + 1.0 / control_total)
    standard_error = math.sqrt(pooled_variance) if pooled_variance > 0 else 0.0

    if standard_error > 0:
        z_score = difference / standard_error
        p_value = 2.0 * (1.0 - normal_cdf(abs(z_score)))
    else:
        z_score = 0.0
        p_value = 1.0

    # Unpooled standard error for the interval
    interval_variance = (
        p_treatment * (1.0 - p_treatment) / treatment_total
        + p_control * (1.0 - p_control) / control_total
    )
    interval_error = math.sqrt(interval_variance) if interval_variance > 0 else 0.0
    z_critical = _z_for_confidence(confidence)
    margin = z_critical * interval_error

    return ComparisonResult(
        treatment_rate=p_treatment,
        control_rate=p_control,
        difference=difference,
        lower=difference - margin,
        upper=difference + margin,
        z_score=z_score,
        p_value=p_value,
        treatment_n=treatment_total,
        control_n=control_total,
    )


def _z_for_confidence(confidence: float) -> float:
    """Two-sided critical z value, by bisection on the normal CDF."""
    target = 1.0 - (1.0 - confidence) / 2.0
    low, high = 0.0, 10.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if normal_cdf(mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


@dataclass
class CusumState:
    """Current state of a CUSUM detector."""

    statistic: float = 0.0
    observations: int = 0
    run_start: Optional[int] = None


class CusumDetector:
    """
    Sequential detector for a downward shift in a success rate.

    A threshold on a windowed average answers "does this window look bad".
    This answers a more useful question: "has the underlying rate shifted, and
    when did it start". It accumulates evidence, so a sustained few-percent
    degradation is caught even though no single window ever breaches a fixed
    threshold, and it decays on recovery so a healed issuer stops alarming.

    The statistic is a log-likelihood ratio between two explicit hypotheses -
    "the rate is `baseline`" versus "the rate is `degraded_rate`" - which is
    the optimal test for that comparison and, unlike an ad-hoc mean-shift
    statistic, makes the threshold interpretable: h = log(1/alpha) targets a
    false-alarm probability of roughly alpha per excursion. A mean-shift
    formulation could not separate signal from noise here at any threshold.
    """

    # log(1/0.001). Measured on synthetic Bernoulli streams (see
    # test_statistics.py): ~4% false alarms per 2000 healthy observations at
    # a 95% baseline, detecting a drop to 90% in ~310 transactions, to 80% in
    # ~74, to 50% in ~22. Chosen deliberately conservative - a payment ops
    # agent that cries wolf gets ignored, and the Bayesian estimate below is
    # what confirms an alarm before anything is acted on.
    DEFAULT_THRESHOLD = 6.9

    def __init__(
        self,
        baseline: float = 0.95,
        degraded_rate: float = 0.90,
        threshold: float = DEFAULT_THRESHOLD,
    ):
        """
        Args:
            baseline: Success rate when healthy.
            degraded_rate: The degradation worth detecting. Detection is
                fastest for shifts of about this size; larger drops are caught
                sooner, smaller ones more slowly.
            threshold: Log-odds required to alarm. log(1/alpha) for a target
                false-alarm rate alpha.
        """
        if not 0.0 < degraded_rate < baseline < 1.0:
            raise ValueError(
                "Expected 0 < degraded_rate < baseline < 1, got "
                f"degraded_rate={degraded_rate}, baseline={baseline}"
            )

        self.baseline = baseline
        self.degraded_rate = degraded_rate
        self.threshold = threshold

        # Per-observation log-likelihood contributions
        self._success_score = math.log(degraded_rate / baseline)
        self._failure_score = math.log((1.0 - degraded_rate) / (1.0 - baseline))

        self.state = CusumState()

    def reset(self):
        self.state = CusumState()

    def update(self, success: bool) -> CusumState:
        """Feed one observation; returns the detector state after it."""
        self.state.observations += 1

        score = self._success_score if success else self._failure_score
        previous = self.state.statistic
        self.state.statistic = max(0.0, previous + score)

        if previous <= 0.0 < self.state.statistic:
            # A fresh excursion started here
            self.state.run_start = self.state.observations
        elif self.state.statistic <= 0.0:
            self.state.run_start = None

        return self.state

    def update_many(self, outcomes: Sequence[bool]) -> CusumState:
        for outcome in outcomes:
            self.update(outcome)
        return self.state

    @property
    def alarmed(self) -> bool:
        """
        Whether the rate is currently shifted.

        Deliberately not sticky: the agent asks "is this issuer degraded now",
        and a latch would keep reporting an outage that has already healed.
        """
        return self.state.statistic > self.threshold

    @property
    def changepoint(self) -> Optional[int]:
        """Observation index (1-based) where the current excursion began."""
        return self.state.run_start if self.alarmed else None

    @property
    def excess_failures(self) -> float:
        """How many failures beyond baseline expectation have accumulated."""
        return self.state.statistic
