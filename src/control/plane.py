"""
Control Plane
The agent's only output.

Every intervention the agent performs is a change to one versioned policy
document. Nothing mutates payment behaviour by any other route.

Two properties follow from that, and they are the reason this exists:

1. Rollback is exact. Reverting means republishing an earlier revision, not
   running bespoke undo logic per action type. Hand-written undo drifts out of
   sync with the code that applied the change - the two are edited at different
   times by different people - and the drift is silent until an incident.

2. Every change is attributable. Each revision records who made it, why, and
   which action it came from, so "why is UPI suppressed right now" always has
   an answer.

Revisions are immutable and append-only. Reverting appends a new revision whose
content matches an older one; it never rewrites history.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple


def _freeze(mapping: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Defensive copy of a nested mapping, so revisions cannot be edited later."""
    return {key: dict(value) for key, value in mapping.items()}


@dataclass(frozen=True)
class ControlPlaneRevision:
    """
    An immutable snapshot of payment policy.

    This is the whole contract between the agent and the traffic it governs: a
    traffic source needs to read nothing else to behave correctly.
    """

    revision: int
    created_at: datetime
    author: str
    reason: str
    parent_revision: Optional[int] = None
    action_id: Optional[str] = None

    circuit_breakers: FrozenSet[str] = frozenset()
    suppressed_methods: FrozenSet[str] = frozenset()
    retry_strategies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    routing_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Target -> fraction of affected traffic deliberately left untreated, so
    # the intervention can be measured against a concurrent control group.
    holdouts: Dict[str, float] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """True if no intervention is in force."""
        return not (
            self.circuit_breakers
            or self.suppressed_methods
            or self.retry_strategies
            or self.routing_overrides
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'revision': self.revision,
            'parent_revision': self.parent_revision,
            'created_at': self.created_at.isoformat(),
            'author': self.author,
            'reason': self.reason,
            'action_id': self.action_id,
            'circuit_breakers': sorted(self.circuit_breakers),
            'suppressed_methods': sorted(self.suppressed_methods),
            'retry_strategies': _freeze(self.retry_strategies),
            'routing_overrides': _freeze(self.routing_overrides),
            'holdouts': dict(self.holdouts),
        }


class ControlPlane:
    """
    The revision log, and the only way to change payment policy.

    Every mutating method takes an author and a reason. That is deliberate:
    an unattributed change to production payment routing is not something the
    API should make easy to write.
    """

    def __init__(self, journal=None):
        """
        Args:
            journal: Optional sink with a `record_revision(revision)` method.
                Every published revision is offered to it.
        """
        self._revisions: List[ControlPlaneRevision] = [
            ControlPlaneRevision(
                revision=0,
                created_at=datetime.now(),
                author='system',
                reason='initial empty policy',
            )
        ]
        self._journal = journal
        self._listeners: List[Any] = []

    # ── Reading ──────────────────────────────────────────────────────────────

    @property
    def current(self) -> ControlPlaneRevision:
        """The revision currently in force."""
        return self._revisions[-1]

    @property
    def revision(self) -> int:
        return self.current.revision

    def history(self, limit: Optional[int] = None) -> List[ControlPlaneRevision]:
        """Revisions, newest first."""
        ordered = list(reversed(self._revisions))
        return ordered[:limit] if limit else ordered

    def get(self, revision: int) -> Optional[ControlPlaneRevision]:
        for candidate in self._revisions:
            if candidate.revision == revision:
                return candidate
        return None

    def subscribe(self, listener):
        """Register a callable invoked with each newly published revision."""
        self._listeners.append(listener)

    # ── Writing ──────────────────────────────────────────────────────────────

    def trip_breaker(self, issuer: str, **meta) -> ControlPlaneRevision:
        """Stop routing to an issuer."""
        return self._publish(
            circuit_breakers=self.current.circuit_breakers | {issuer},
            **meta,
        )

    def clear_breaker(self, issuer: str, **meta) -> ControlPlaneRevision:
        """Resume routing to an issuer."""
        return self._publish(
            circuit_breakers=self.current.circuit_breakers - {issuer},
            **meta,
        )

    def suppress_method(self, method: str, **meta) -> ControlPlaneRevision:
        """Stop offering a payment method."""
        return self._publish(
            suppressed_methods=self.current.suppressed_methods | {method},
            **meta,
        )

    def restore_method(self, method: str, **meta) -> ControlPlaneRevision:
        """Offer a payment method again."""
        return self._publish(
            suppressed_methods=self.current.suppressed_methods - {method},
            **meta,
        )

    def set_retry_strategy(
        self, target: str, strategy: Mapping[str, Any], **meta
    ) -> ControlPlaneRevision:
        """Apply a retry policy to a target, merging with any already in force."""
        strategies = _freeze(self.current.retry_strategies)
        merged = dict(strategies.get(target, {}))
        merged.update(strategy)
        strategies[target] = merged
        return self._publish(retry_strategies=strategies, **meta)

    def clear_retry_strategy(self, target: str, **meta) -> ControlPlaneRevision:
        strategies = _freeze(self.current.retry_strategies)
        strategies.pop(target, None)
        return self._publish(retry_strategies=strategies, **meta)

    def set_routing_override(
        self, target: str, override: Mapping[str, Any], **meta
    ) -> ControlPlaneRevision:
        overrides = _freeze(self.current.routing_overrides)
        overrides[target] = dict(override)
        return self._publish(routing_overrides=overrides, **meta)

    def clear_routing_override(self, target: str, **meta) -> ControlPlaneRevision:
        overrides = _freeze(self.current.routing_overrides)
        overrides.pop(target, None)
        return self._publish(routing_overrides=overrides, **meta)

    def set_holdout(self, target: str, fraction: float, **meta) -> ControlPlaneRevision:
        """Withhold a fraction of a target's traffic from its intervention."""
        holdouts = dict(self.current.holdouts)
        holdouts[target] = fraction
        return self._publish(holdouts=holdouts, **meta)

    def clear_holdout(self, target: str, **meta) -> ControlPlaneRevision:
        holdouts = dict(self.current.holdouts)
        holdouts.pop(target, None)
        return self._publish(holdouts=holdouts, **meta)

    def revert_to(
        self, revision: int, author: str, reason: str, action_id: Optional[str] = None
    ) -> ControlPlaneRevision:
        """
        Republish the contents of an earlier revision as a new one.

        History is append-only: reverting to revision 3 creates revision 9 whose
        content matches revision 3, so the fact that a revert happened - and who
        did it - stays in the record.
        """
        target = self.get(revision)
        if target is None:
            raise KeyError(f"No such control plane revision: {revision}")

        return self._publish(
            author=author,
            reason=reason,
            action_id=action_id,
            circuit_breakers=target.circuit_breakers,
            suppressed_methods=target.suppressed_methods,
            retry_strategies=_freeze(target.retry_strategies),
            routing_overrides=_freeze(target.routing_overrides),
            holdouts=dict(target.holdouts),
        )

    def undo_revision(
        self, revision: int, author: str, reason: str, action_id: Optional[str] = None
    ) -> ControlPlaneRevision:
        """
        Undo one revision's effect, leaving any later changes in place.

        The inverse is *derived* by diffing the revision against its parent, so
        it always matches what the change actually did. A hand-written undo
        branch per action type is a second implementation of the same knowledge,
        and the two drift apart silently.

        Use revert_to() instead when the intent is to restore a whole earlier
        policy rather than to withdraw one intervention.
        """
        target = self.get(revision)
        if target is None:
            raise KeyError(f"No such control plane revision: {revision}")

        parent = self.get(target.parent_revision) if target.parent_revision is not None else None
        if parent is None:
            parent = self._revisions[0]

        current = self.current

        # Sets: drop what the revision added, restore what it removed
        breakers = (current.circuit_breakers - (target.circuit_breakers - parent.circuit_breakers))
        breakers |= (parent.circuit_breakers - target.circuit_breakers)

        methods = (current.suppressed_methods - (target.suppressed_methods - parent.suppressed_methods))
        methods |= (parent.suppressed_methods - target.suppressed_methods)

        return self._publish(
            author=author,
            reason=reason,
            action_id=action_id,
            circuit_breakers=breakers,
            suppressed_methods=methods,
            retry_strategies=_invert_map(
                current.retry_strategies, parent.retry_strategies, target.retry_strategies
            ),
            routing_overrides=_invert_map(
                current.routing_overrides, parent.routing_overrides, target.routing_overrides
            ),
        )

    def _publish(
        self,
        author: str,
        reason: str,
        action_id: Optional[str] = None,
        **changes,
    ) -> ControlPlaneRevision:
        """Append a new revision built from the current one plus `changes`."""
        previous = self.current

        candidate = replace(
            previous,
            revision=previous.revision + 1,
            parent_revision=previous.revision,
            created_at=datetime.now(),
            author=author,
            reason=reason,
            action_id=action_id,
            **changes,
        )

        # A change that changes nothing should not create a revision; otherwise
        # the log fills with noise and diffs become useless.
        if _same_policy(previous, candidate):
            return previous

        self._revisions.append(candidate)

        if self._journal is not None:
            self._journal.record_revision(candidate)
        for listener in self._listeners:
            listener(candidate)

        return candidate


def _invert_map(
    current: Mapping[str, Mapping[str, Any]],
    parent: Mapping[str, Mapping[str, Any]],
    target: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Undo a revision's map changes against the current state.

    Keys the revision introduced are dropped; keys it altered or deleted are
    restored to the parent's value. Keys it never touched are left alone, so a
    later intervention on a different target survives.
    """
    result = _freeze(current)

    for key in set(target) - set(parent):
        result.pop(key, None)

    for key in set(parent):
        if parent.get(key) != target.get(key):
            result[key] = dict(parent[key])

    return result


def _same_policy(a: ControlPlaneRevision, b: ControlPlaneRevision) -> bool:
    """True if two revisions express identical policy, ignoring metadata."""
    return (
        a.circuit_breakers == b.circuit_breakers
        and a.suppressed_methods == b.suppressed_methods
        and a.retry_strategies == b.retry_strategies
        and a.routing_overrides == b.routing_overrides
        and a.holdouts == b.holdouts
    )


def diff(
    before: ControlPlaneRevision, after: ControlPlaneRevision
) -> List[str]:
    """
    Human-readable description of what changed between two revisions.

    Used in the decision log and in approval requests, where an operator needs
    to see the effect of a proposed change rather than a policy blob.
    """
    lines: List[str] = []

    lines += _diff_set('circuit breaker', before.circuit_breakers, after.circuit_breakers)
    lines += _diff_set('method suppression', before.suppressed_methods, after.suppressed_methods)
    lines += _diff_map('retry strategy', before.retry_strategies, after.retry_strategies)
    lines += _diff_map('routing override', before.routing_overrides, after.routing_overrides)
    lines += _diff_holdouts(before.holdouts, after.holdouts)

    return lines


def _diff_holdouts(before: Mapping[str, float], after: Mapping[str, float]) -> List[str]:
    """
    Report holdout changes.

    Omitted until now, which made a holdout the one policy change that could
    enter the audit trail showing nothing at all - and it is the change that
    most needs explaining, because it knowingly leaves a slice of real payments
    unprotected in order to measure whether the protection works. An operator
    reviewing the history saw a revision with an empty diff.
    """
    lines = []
    for target in sorted(set(after) - set(before)):
        lines.append(f"+ holdout: {target} = {after[target]:.0%} left as control")
    for target in sorted(set(before) - set(after)):
        lines.append(f"- holdout: {target}")
    for target in sorted(set(before) & set(after)):
        if before[target] != after[target]:
            lines.append(
                f"~ holdout: {target} = {before[target]:.0%} -> {after[target]:.0%}"
            )
    return lines


def _diff_set(label: str, before: Iterable[str], after: Iterable[str]) -> List[str]:
    before, after = set(before), set(after)
    lines = [f"+ {label}: {item}" for item in sorted(after - before)]
    lines += [f"- {label}: {item}" for item in sorted(before - after)]
    return lines


def _diff_map(
    label: str,
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    lines = []
    for key in sorted(set(after) - set(before)):
        lines.append(f"+ {label}: {key} = {_readable(after[key])}")
    for key in sorted(set(before) - set(after)):
        lines.append(f"- {label}: {key}")
    for key in sorted(set(before) & set(after)):
        if before[key] != after[key]:
            lines.append(
                f"~ {label}: {key} = {_readable(before[key])} -> {_readable(after[key])}"
            )
    return lines


def _readable(value: Mapping[str, Any]) -> str:
    """
    Render a policy value for human eyes.

    Bookkeeping fields - when it was applied, which are recorded on the
    revision itself anyway - are dropped. A diff exists to answer "what
    changed", and repeating a timestamp inside it buries the answer.
    """
    interesting = {
        key: val for key, val in value.items()
        if not key.endswith('_at') and val not in (None, False, 0)
    }
    if not interesting:
        return '{}'
    return ', '.join(f"{key}={val}" for key, val in sorted(interesting.items()))
