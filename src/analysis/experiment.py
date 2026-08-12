"""
Holdout experiments.

How the agent finds out whether an intervention actually worked.

The obvious approach - compare the success rate before the intervention with
the success rate after - is confounded by everything else that changed in
between. Most damagingly, it is confounded by the incident resolving on its
own: an issuer that recovers by itself makes every intervention look like a
triumph, and the agent learns to repeat whatever it happened to be doing.

Instead, when an intervention is applied it is applied to most of the affected
traffic and deliberately withheld from a small holdout, chosen at random per
transaction. Both arms then run *at the same time*, through the same outage,
so the difference between them is attributable to the intervention rather than
to time passing.

The cost is real and worth stating: the holdout is traffic the agent knowingly
leaves unprotected. That is the price of knowing whether the protection works,
and it is why the fraction is small and configurable.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.analysis.statistics import ComparisonResult, compare_proportions

TREATMENT = 'treatment'
CONTROL = 'control'


@dataclass
class ArmCounts:
    """Observed outcomes for one arm of an experiment."""

    successes: int = 0
    total: int = 0

    def record(self, success: bool):
        self.total += 1
        if success:
            self.successes += 1

    @property
    def rate(self) -> float:
        return self.successes / self.total if self.total else 0.0


@dataclass
class Experiment:
    """
    One intervention, measured against a concurrent holdout.

    `target` is what the intervention applies to (an issuer, a payment method);
    every transaction that would have been affected is assigned to an arm.
    """

    experiment_id: str
    action_id: str
    action_type: str
    target: str
    holdout_fraction: float
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None

    treatment: ArmCounts = field(default_factory=ArmCounts)
    control: ArmCounts = field(default_factory=ArmCounts)

    @property
    def active(self) -> bool:
        return self.ended_at is None

    @property
    def observations(self) -> int:
        return self.treatment.total + self.control.total

    def record(self, arm: str, success: bool):
        if arm == TREATMENT:
            self.treatment.record(success)
        elif arm == CONTROL:
            self.control.record(success)

    def has_sufficient_data(self, min_per_arm: int = 30) -> bool:
        """
        Whether both arms have enough observations to be worth comparing.

        Comparing one transaction against one transaction produces a number,
        but not information; scoring an action on that would feed the learner
        noise dressed as measurement.
        """
        return self.treatment.total >= min_per_arm and self.control.total >= min_per_arm

    def result(self, confidence: float = 0.95) -> Optional[ComparisonResult]:
        """
        Measured lift, or None while either arm is still empty.

        The caller should also check `significant` before believing the sign of
        a small difference.
        """
        return compare_proportions(
            self.treatment.successes, self.treatment.total,
            self.control.successes, self.control.total,
            confidence=confidence,
        )

    def summary(self) -> Dict:
        result = self.result()
        return {
            'experiment_id': self.experiment_id,
            'action_id': self.action_id,
            'action_type': self.action_type,
            'target': self.target,
            'holdout_fraction': self.holdout_fraction,
            'active': self.active,
            'treatment': {'successes': self.treatment.successes, 'total': self.treatment.total},
            'control': {'successes': self.control.successes, 'total': self.control.total},
            'lift': result.difference if result else None,
            'lift_ci': [result.lower, result.upper] if result else None,
            'p_value': result.p_value if result else None,
            'significant': result.significant if result else False,
            'verdict': result.describe() if result else 'insufficient data',
        }


class ExperimentRegistry:
    """
    Tracks running experiments and assigns transactions to arms.

    Assignment is a deterministic hash of the transaction id, not a coin flip.
    That matters for two reasons: a replayed transaction lands in the same arm
    it originally did, so evaluation is reproducible; and retries of the same
    payment do not straddle arms.
    """

    def __init__(self, default_holdout: float = 0.10):
        if not 0.0 <= default_holdout < 0.5:
            raise ValueError(
                f"default_holdout must be in [0, 0.5), got {default_holdout}. "
                f"A holdout at or above half the traffic is no longer a holdout."
            )
        self.default_holdout = default_holdout
        self.experiments: Dict[str, Experiment] = {}
        self._by_target: Dict[str, str] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(
        self,
        action_id: str,
        action_type: str,
        target: str,
        holdout_fraction: Optional[float] = None,
    ) -> Experiment:
        """Begin measuring an intervention against a holdout."""
        holdout = self.default_holdout if holdout_fraction is None else holdout_fraction
        experiment = Experiment(
            experiment_id=f"exp-{action_id[:8]}",
            action_id=action_id,
            action_type=action_type,
            target=target,
            holdout_fraction=holdout,
        )
        self.experiments[experiment.experiment_id] = experiment
        self._by_target[target] = experiment.experiment_id
        return experiment

    def stop(self, action_id: str) -> Optional[Experiment]:
        """End the experiment for an action, keeping its results."""
        experiment = self.for_action(action_id)
        if experiment is None:
            return None

        experiment.ended_at = datetime.now()
        if self._by_target.get(experiment.target) == experiment.experiment_id:
            del self._by_target[experiment.target]
        return experiment

    # ── Lookup ───────────────────────────────────────────────────────────────

    def for_target(self, target: str) -> Optional[Experiment]:
        experiment_id = self._by_target.get(target)
        return self.experiments.get(experiment_id) if experiment_id else None

    def for_action(self, action_id: str) -> Optional[Experiment]:
        for experiment in self.experiments.values():
            if experiment.action_id == action_id:
                return experiment
        return None

    def active(self) -> List[Experiment]:
        return [e for e in self.experiments.values() if e.active]

    # ── Assignment and recording ─────────────────────────────────────────────

    def holdouts(self) -> Dict[str, float]:
        """Target -> holdout fraction, for publication to the control plane."""
        return {
            experiment.target: experiment.holdout_fraction
            for experiment in self.experiments.values()
            if experiment.active
        }

    @staticmethod
    def assign(transaction_id: str, holdout_fraction: float) -> str:
        """
        Deterministically place a transaction in treatment or control.

        Uses a stable hash rather than random(), so the same transaction always
        lands in the same arm however many times it is replayed.
        """
        if holdout_fraction <= 0.0:
            return TREATMENT

        digest = hashlib.sha256(transaction_id.encode('utf-8')).digest()
        bucket = int.from_bytes(digest[:4], 'big') / 0xFFFFFFFF
        return CONTROL if bucket < holdout_fraction else TREATMENT

    def record(self, transaction) -> bool:
        """
        Record a transaction against its experiment, if it belongs to one.

        Returns:
            True if the transaction counted toward an experiment.
        """
        target = getattr(transaction, 'experiment_target', None)
        arm = getattr(transaction, 'experiment_arm', None)
        if not target or not arm:
            return False

        experiment = self.for_target(target)
        if experiment is None or not experiment.active:
            return False

        from src.models.state import PaymentStatus
        experiment.record(arm, transaction.status == PaymentStatus.SUCCESS)
        return True

    def record_batch(self, transactions) -> int:
        return sum(1 for t in transactions if self.record(t))

    def summaries(self) -> List[Dict]:
        return [e.summary() for e in self.experiments.values()]
