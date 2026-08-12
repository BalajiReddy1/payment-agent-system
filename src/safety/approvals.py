"""
Approval queue.

Where an action goes when the agent has decided it is the right thing to do
but is not permitted to do it alone.

The alternative — refusing the action and moving on — is what the loop did
before, and it is quietly the worst option: the agent concludes a circuit
breaker is needed, declines to ask anyone, and the incident continues. An
authorization tier is only meaningful if there is somewhere for the request
to go and someone who can see it.

Two rules make this safe rather than decorative:

- Requests expire. An approval that nobody answers is *not* eventually granted;
  it lapses and is recorded as lapsed. The opposite policy - escalate, then
  proceed anyway - turns every tier into a delay rather than a control.
- Approving is a separate act from proposing. The agent may fill this queue but
  never drain it, which is why approve() takes an explicit approver identity and
  the model is not given the tool.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.models.state import Action, AuthorizationLevel

logger = logging.getLogger(__name__)

PENDING = 'pending'
APPROVED = 'approved'
DENIED = 'denied'
LAPSED = 'lapsed'


@dataclass
class ApprovalRequest:
    """One action waiting on a human."""

    request_id: str
    action: Action
    requested_by: str
    reason: str
    requested_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None

    status: str = PENDING
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    note: Optional[str] = None

    @property
    def pending(self) -> bool:
        return self.status == PENDING

    @property
    def seconds_remaining(self) -> Optional[float]:
        if self.expires_at is None or not self.pending:
            return None
        return max(0.0, (self.expires_at - datetime.now()).total_seconds())

    def summary(self) -> Dict:
        impact = self.action.estimated_impact or {}
        return {
            'request_id': self.request_id,
            'action_id': self.action.action_id,
            'action_type': self.action.action_type.value,
            'target': self.action.target,
            'risk_level': self.action.risk_level.value,
            'authorization': self.action.authorization_level.value,
            'requested_by': self.requested_by,
            'requested_at': self.requested_at.isoformat(),
            'reason': self.reason,
            'status': self.status,
            'decided_by': self.decided_by,
            'note': self.note,
            'seconds_remaining': self.seconds_remaining,
            'blast_radius': impact.get('affected_traffic_pct', 0.0),
            'expected_lift': impact.get('success_rate_delta', 0.0),
            'parameters': dict(self.action.parameters or {}),
        }


class ApprovalQueue:
    """
    Holds actions that require human authorization.

    Shared by every path that can propose an action, so an operator has one
    place to look rather than one per surface.
    """

    def __init__(self, ttl_seconds: float = 600.0, capacity: int = 200):
        self.ttl = timedelta(seconds=ttl_seconds)
        self.capacity = capacity
        self.requests: Dict[str, ApprovalRequest] = {}
        self._sequence = 0

    # ── Proposing ────────────────────────────────────────────────────────────

    def submit(
        self,
        action: Action,
        requested_by: str = 'agent',
        reason: str = '',
    ) -> ApprovalRequest:
        """Queue an action for authorization."""
        existing = self.pending_for(action.action_type.value, action.target)
        if existing is not None:
            # Re-proposing the same intervention every cycle would bury the
            # operator in duplicates of one decision.
            return existing

        self._sequence += 1
        request = ApprovalRequest(
            request_id=f"apr-{self._sequence:04d}",
            action=action,
            requested_by=requested_by,
            reason=reason or f"{action.action_type.value} on {action.target}",
            expires_at=datetime.now() + self.ttl,
        )
        self.requests[request.request_id] = request
        self._trim()

        logger.info(
            "Approval %s requested: %s on %s (%s, expires in %.0fs)",
            request.request_id, action.action_type.value, action.target,
            action.authorization_level.value, self.ttl.total_seconds(),
        )
        return request

    # ── Deciding ─────────────────────────────────────────────────────────────

    def approve(
        self,
        request_id: str,
        approver: str,
        note: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Action]]:
        """
        Authorize a queued action.

        Returns:
            Tuple of (ok, message, action ready to execute or None). The caller
            executes it; the queue's job is authorization, not execution.
        """
        request = self.requests.get(request_id)
        if request is None:
            return False, f"No approval request {request_id}", None
        if not request.pending:
            return False, f"{request_id} is already {request.status}", None
        if not approver or not approver.strip():
            return False, "An approver identity is required", None

        request.status = APPROVED
        request.decided_by = approver.strip()
        request.decided_at = datetime.now()
        request.note = note
        request.action.approver = request.decided_by

        logger.info("Approval %s granted by %s", request_id, request.decided_by)
        return True, f"{request_id} approved by {request.decided_by}", request.action

    def deny(
        self,
        request_id: str,
        approver: str,
        note: Optional[str] = None,
    ) -> Tuple[bool, str]:
        request = self.requests.get(request_id)
        if request is None:
            return False, f"No approval request {request_id}"
        if not request.pending:
            return False, f"{request_id} is already {request.status}"
        if not approver or not approver.strip():
            return False, "An approver identity is required"

        request.status = DENIED
        request.decided_by = approver.strip()
        request.decided_at = datetime.now()
        request.note = note

        logger.info("Approval %s denied by %s", request_id, request.decided_by)
        return True, f"{request_id} denied by {request.decided_by}"

    def expire_stale(self) -> List[ApprovalRequest]:
        """
        Lapse requests nobody answered.

        Deliberately lapse rather than auto-approve. A tier that eventually
        grants itself is a delay, not a control.
        """
        now = datetime.now()
        lapsed = []
        for request in self.requests.values():
            if request.pending and request.expires_at and request.expires_at <= now:
                request.status = LAPSED
                request.decided_at = now
                lapsed.append(request)
                logger.warning(
                    "Approval %s lapsed unanswered: %s on %s",
                    request.request_id, request.action.action_type.value,
                    request.action.target,
                )
        return lapsed

    # ── Reading ──────────────────────────────────────────────────────────────

    def pending(self) -> List[ApprovalRequest]:
        return [r for r in self.requests.values() if r.pending]

    def pending_for(self, action_type: str, target: str) -> Optional[ApprovalRequest]:
        for request in self.requests.values():
            if (
                request.pending
                and request.action.action_type.value == action_type
                and request.action.target == target
            ):
                return request
        return None

    def recent(self, limit: int = 20) -> List[ApprovalRequest]:
        return sorted(
            self.requests.values(), key=lambda r: r.requested_at, reverse=True
        )[:limit]

    def summaries(self, limit: int = 20) -> List[Dict]:
        return [r.summary() for r in self.recent(limit)]

    def _trim(self):
        if len(self.requests) <= self.capacity:
            return
        decided = sorted(
            (r for r in self.requests.values() if not r.pending),
            key=lambda r: r.requested_at,
        )
        for request in decided[: len(self.requests) - self.capacity]:
            del self.requests[request.request_id]


def needs_human(action: Action, auto_approve_low_risk: bool = True) -> bool:
    """
    Whether an action must be queued rather than executed.

    The one place this question is answered, so the autonomous loop and the
    tool layer cannot drift apart on it.
    """
    from src.models.state import RiskLevel

    if action.approver:
        return False
    if action.authorization_level == AuthorizationLevel.AUTOMATIC:
        return False
    if (
        action.authorization_level == AuthorizationLevel.SEMI_AUTOMATIC
        and auto_approve_low_risk
        and action.risk_level == RiskLevel.LOW
    ):
        return False
    return True
