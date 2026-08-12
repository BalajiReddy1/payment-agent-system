"""
Incident memory.

What the agent remembers about incidents it has seen before, and what actually
worked on them.

Holdout experiments produce a measured lift for each intervention. Without
somewhere to put that, the measurement dies with the incident and the agent
starts every outage as if it were the first. This module is where a measured
result becomes a prior for the next decision: "the last three times SBI looked
like this, a circuit breaker measured +18%, +22% and +15%".

Similarity is computed over structured features rather than text embeddings.
Incidents here are not prose - they are a pattern type, a dimension, a target,
a severity and an error signature - and comparing those directly is both more
accurate and more explainable than comparing sentences about them. It also
means the agent can say *why* two incidents are alike, which matters when a
human is deciding whether to trust the recommendation.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.utils.stats import mean

# How much each feature contributes to similarity. Pattern type and the
# affected dimension dominate: an issuer degradation and a retry storm are not
# the same incident however similar their severity happens to be.
FEATURE_WEIGHTS = {
    'pattern_type': 0.40,
    'dimension': 0.15,
    'target': 0.20,
    'severity': 0.15,
    'error_signature': 0.10,
}


@dataclass
class IncidentRecord:
    """One past incident, and what was done about it."""

    pattern_type: str
    dimension: str
    target: str
    severity: float
    confidence: float
    error_signature: Tuple[str, ...] = ()

    action_type: Optional[str] = None
    measured_lift: Optional[float] = None
    significant: bool = False
    attribution: str = 'none'
    occurred_at: datetime = field(default_factory=datetime.now)

    @property
    def has_trustworthy_outcome(self) -> bool:
        """True when this incident's outcome was actually measured."""
        return (
            self.attribution == 'holdout'
            and self.significant
            and self.measured_lift is not None
        )

    def describe(self) -> str:
        when = self.occurred_at.strftime('%b %d %H:%M')
        if self.measured_lift is None:
            return f"{when}: {self.pattern_type} on {self.target}, no measured outcome"
        verdict = 'measured' if self.has_trustworthy_outcome else 'unverified'
        return (
            f"{when}: {self.pattern_type} on {self.target} -> "
            f"{self.action_type} gave {self.measured_lift:+.1%} ({verdict})"
        )


class IncidentMemory:
    """
    Recalls similar incidents and what measurably worked on them.

    Deliberately conservative about what counts as knowledge: only outcomes
    measured against a holdout and cleared for significance are allowed to
    influence a recommendation. An unverified before/after result is kept for
    context but never turned into advice.
    """

    def __init__(self, capacity: int = 2000):
        self.capacity = capacity
        self.incidents: List[IncidentRecord] = []

    # ── Writing ──────────────────────────────────────────────────────────────

    def remember(self, record: IncidentRecord):
        self.incidents.append(record)
        if len(self.incidents) > self.capacity:
            self.incidents = self.incidents[-self.capacity:]

    def remember_pattern(self, pattern, action=None, outcome: Optional[Dict] = None):
        """Record an incident from the agent's own types."""
        outcome = outcome or {}
        self.remember(IncidentRecord(
            pattern_type=pattern.pattern_type,
            dimension=pattern.affected_dimension,
            target=pattern.affected_value,
            severity=pattern.severity,
            confidence=pattern.confidence,
            error_signature=_signature(pattern),
            action_type=action.action_type.value if action else None,
            measured_lift=outcome.get('success_rate_delta'),
            significant=bool(outcome.get('significant')),
            attribution=outcome.get('attribution', 'none'),
        ))

    def load_from_journal(self, journal):
        """Rebuild memory from a durable journal, so restarts do not forget."""
        try:
            rows = journal.query(
                """
                SELECT p.pattern_type, p.dimension, p.affected_value, p.severity,
                       p.confidence, p.detected_at, a.action_type, o.actual_impact
                FROM patterns p
                LEFT JOIN actions a ON a.cycle = p.cycle AND a.run_id = p.run_id
                LEFT JOIN outcomes o ON o.action_id = a.action_id
                ORDER BY p.detected_at
                """
            )
        except Exception:  # a journal without these tables is not fatal
            return 0

        import json as _json

        loaded = 0
        for row in rows:
            impact = {}
            if row['actual_impact']:
                try:
                    impact = _json.loads(row['actual_impact']) or {}
                except (ValueError, TypeError):
                    impact = {}

            self.remember(IncidentRecord(
                pattern_type=row['pattern_type'] or '',
                dimension=row['dimension'] or '',
                target=row['affected_value'] or '',
                severity=row['severity'] or 0.0,
                confidence=row['confidence'] or 0.0,
                action_type=row['action_type'],
                measured_lift=impact.get('success_rate_delta'),
                significant=bool(impact.get('significant')),
                attribution=impact.get('attribution', 'none'),
                occurred_at=_parse_time(row['detected_at']),
            ))
            loaded += 1

        return loaded

    # ── Reading ──────────────────────────────────────────────────────────────

    def similarity(self, pattern, record: IncidentRecord) -> float:
        """
        How alike a live pattern and a remembered incident are, in [0, 1].

        Explainable by construction: the score is a weighted sum of feature
        agreements, so it can always be broken down for a human.
        """
        # Pattern type is a gate, not a weight. A retry storm and an issuer
        # degradation are categorically different incidents however closely
        # their severity or volume happen to line up, and letting the other
        # features accumulate across that boundary would let an unrelated
        # incident supply advice.
        if record.pattern_type != pattern.pattern_type:
            return 0.0

        scores = {
            'pattern_type': 1.0,
            'dimension': 1.0 if record.dimension == pattern.affected_dimension else 0.0,
            'target': 1.0 if record.target == pattern.affected_value else 0.0,
            'severity': max(0.0, 1.0 - abs(record.severity - pattern.severity)),
            'error_signature': _overlap(record.error_signature, _signature(pattern)),
        }
        return sum(FEATURE_WEIGHTS[name] * value for name, value in scores.items())

    def recall(
        self,
        pattern,
        limit: int = 5,
        min_similarity: float = 0.5,
    ) -> List[Tuple[IncidentRecord, float]]:
        """Most similar past incidents, most similar first."""
        scored = [
            (record, self.similarity(pattern, record))
            for record in self.incidents
        ]
        scored = [item for item in scored if item[1] >= min_similarity]
        scored.sort(key=lambda item: (item[1], item[0].occurred_at), reverse=True)
        return scored[:limit]

    def recommend(self, pattern, min_samples: int = 2) -> Dict[str, Dict]:
        """
        What measurably worked on incidents like this one.

        Returns:
            action type -> {'expected_lift', 'samples', 'similarity'}, built
            only from outcomes that were measured against a holdout and were
            significant. Actions never verified simply do not appear.
        """
        by_action: Dict[str, List[Tuple[float, float]]] = defaultdict(list)

        for record, score in self.recall(pattern, limit=200, min_similarity=0.5):
            if not record.has_trustworthy_outcome or not record.action_type:
                continue
            by_action[record.action_type].append((record.measured_lift, score))

        recommendations = {}
        for action_type, samples in by_action.items():
            if len(samples) < min_samples:
                continue
            recommendations[action_type] = {
                'expected_lift': mean([lift for lift, _ in samples]),
                'samples': len(samples),
                'similarity': mean([score for _, score in samples]),
            }

        return recommendations

    def explain(self, pattern, limit: int = 3) -> List[str]:
        """Human-readable recall, for decision reasoning and the UI."""
        return [
            f"{record.describe()} (similarity {score:.0%})"
            for record, score in self.recall(pattern, limit=limit)
        ]


def _signature(pattern) -> Tuple[str, ...]:
    """Stable feature signature for a pattern, used for overlap scoring."""
    return tuple(sorted(str(key) for key in (pattern.metrics or {}).keys()))[:6]


def _overlap(a: Tuple[str, ...], b: Tuple[str, ...]) -> float:
    """Jaccard overlap between two signatures."""
    set_a, set_b = set(a), set(b)
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def _parse_time(value) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now()
