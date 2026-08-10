"""
Safety Guardrails
Defines the operational boundaries for the Payment Agent: how much traffic it
may disturb, how often it may act, and when a human has to be involved.

The authorization tiers themselves live in src.models.state so that every code
path - the autonomous loop, the LLM tool layer, and this module - reads the
same map. A second, slightly different copy of that policy is worse than none,
because it lets a caller pick whichever definition suits it.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.models.state import (
    ACTION_AUTHORIZATION,
    Action,
    AgentState,
    AuthorizationLevel,
    required_authorization,
)

# Tiers in escalating order, for stable display
_TIER_ORDER = [
    AuthorizationLevel.AUTOMATIC,
    AuthorizationLevel.SEMI_AUTOMATIC,
    AuthorizationLevel.MANUAL,
]


@dataclass
class SafetyLimits:
    """Configurable safety limits for the agent."""

    # Traffic impact limits
    max_traffic_impact_percent: float = 15.0

    # Action rate limits
    max_actions_per_hour: int = 10
    max_rollbacks_per_hour: int = 3
    max_concurrent_interventions: int = 5

    # Risk thresholds
    min_confidence_for_action: float = 0.6

    # Impact thresholds that escalate the required authorization
    auto_approve_impact_threshold: float = 5.0
    manual_approve_impact_threshold: float = 20.0


class SafetyGuardrails:
    """
    Enforces safety constraints on agent actions.

    Implements the problem statement requirement: "define ethical and
    operational boundaries - what the agent is allowed to change autonomously,
    when human approval is required".
    """

    def __init__(self, limits: Optional[SafetyLimits] = None):
        self.limits = limits or SafetyLimits()
        self.blocked_reasons: List[str] = []

    def check_action_allowed(
        self,
        action: Action,
        state: AgentState,
        active_interventions: int = 0
    ) -> Tuple[bool, AuthorizationLevel, str]:
        """
        Check whether an action is permitted under current safety constraints.

        Args:
            action: The proposed action.
            state: Current agent state.
            active_interventions: How many interventions are already running.

        Returns:
            Tuple of (allowed, required authorization level, reason)
        """
        authorization = self.required_authorization(action)

        blocked = self._first_violation(action, state, active_interventions)
        if blocked:
            self.blocked_reasons.append(blocked)
            return False, authorization, blocked

        return True, authorization, "Action within safety limits"

    def _first_violation(
        self,
        action: Action,
        state: AgentState,
        active_interventions: int
    ) -> Optional[str]:
        """The first limit this action violates, or None if it violates none."""
        limits = self.limits

        if state.actions_taken_last_hour >= limits.max_actions_per_hour:
            return (
                f"Rate limit exceeded: "
                f"{state.actions_taken_last_hour}/{limits.max_actions_per_hour} actions this hour"
            )

        if state.rollbacks_last_hour >= limits.max_rollbacks_per_hour:
            return (
                f"Too many rollbacks: "
                f"{state.rollbacks_last_hour}/{limits.max_rollbacks_per_hour} this hour"
            )

        if active_interventions >= limits.max_concurrent_interventions:
            return f"Too many concurrent interventions: {active_interventions}"

        if action.confidence < limits.min_confidence_for_action:
            return (
                f"Confidence too low: "
                f"{action.confidence:.2f} < {limits.min_confidence_for_action}"
            )

        impact_pct = self._traffic_impact_percent(action)
        if impact_pct > limits.max_traffic_impact_percent:
            return (
                f"Blast radius too large: {impact_pct:.1f}% of traffic "
                f"(limit {limits.max_traffic_impact_percent}%)"
            )

        return None

    def required_authorization(self, action: Action) -> AuthorizationLevel:
        """
        The authorization tier this specific action needs.

        Starts from the action type's baseline tier and escalates it when the
        action would touch an unusually large share of traffic.
        """
        base_level = required_authorization(action.action_type)
        impact_pct = self._traffic_impact_percent(action)

        if impact_pct > self.limits.manual_approve_impact_threshold:
            return AuthorizationLevel.MANUAL

        if impact_pct > self.limits.auto_approve_impact_threshold:
            if base_level == AuthorizationLevel.AUTOMATIC:
                return AuthorizationLevel.SEMI_AUTOMATIC

        return base_level

    @staticmethod
    def _traffic_impact_percent(action: Action) -> float:
        """Share of traffic an action affects, as a percentage."""
        fraction = action.estimated_impact.get('affected_traffic_pct', 0.0) or 0.0
        return float(fraction) * 100.0

    def get_safety_status(self, state: Optional[AgentState] = None) -> Dict:
        """Current safety posture, for display and for the API."""
        status = {
            'limits': {
                'max_traffic_impact_percent': self.limits.max_traffic_impact_percent,
                'max_actions_per_hour': self.limits.max_actions_per_hour,
                'max_rollbacks_per_hour': self.limits.max_rollbacks_per_hour,
                'max_concurrent_interventions': self.limits.max_concurrent_interventions,
                'min_confidence_for_action': self.limits.min_confidence_for_action,
            },
            'authorization_tiers': self.authorization_tiers(),
            'recent_blocks': self.blocked_reasons[-5:],
        }

        if state is not None:
            status['usage'] = {
                'actions_this_hour': state.actions_taken_last_hour,
                'rollbacks_this_hour': state.rollbacks_last_hour,
            }

        return status

    @staticmethod
    def authorization_tiers() -> Dict[str, List[str]]:
        """Action types grouped by the tier they require, for display."""
        grouped: Dict[str, List[str]] = {tier.value: [] for tier in _TIER_ORDER}
        for action_type, level in sorted(
            ACTION_AUTHORIZATION.items(), key=lambda item: item[0].value
        ):
            grouped[level.value].append(action_type.value)
        return grouped
