"""
Safety Guardrails
Defines ethical and operational boundaries for the Payment Agent.
Enforces limits on what the agent can do autonomously.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.models.state import Action, ActionType, AgentState


class AuthorizationLevel(Enum):
    """Authorization levels for actions."""
    AUTOMATIC = "automatic"      # Agent can execute without approval
    SEMI_AUTOMATIC = "semi_auto" # Agent recommends, requires quick approval
    MANUAL = "manual"            # Requires explicit human approval
    BLOCKED = "blocked"          # Action not allowed


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
    min_score_for_action: float = 0.5
    
    # Approval thresholds
    auto_approve_impact_threshold: float = 5.0  # Below this = auto-approve
    manual_approve_impact_threshold: float = 20.0  # Above this = manual


class SafetyGuardrails:
    """
    Enforces safety constraints on agent actions.
    
    Implements the problem statement requirement:
    "define ethical and operational boundaries—what the agent is allowed 
    to change autonomously, when human approval is required"
    """
    
    def __init__(self, limits: Optional[SafetyLimits] = None):
        self.limits = limits or SafetyLimits()
        self.action_history: List[Dict] = []
        self.blocked_reasons: List[str] = []
    
    def check_action_allowed(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, AuthorizationLevel, str]:
        """
        Check if an action is allowed under current safety constraints.
        
        Returns:
            Tuple of (allowed, authorization_level, reason)
        """
        # Check 1: Action rate limit
        if not self._check_rate_limit(state):
            return False, AuthorizationLevel.BLOCKED, \
                f"Rate limit exceeded: max {self.limits.max_actions_per_hour} actions/hour"
        
        # Check 2: Rollback limit
        if state.rollbacks_last_hour >= self.limits.max_rollbacks_per_hour:
            return False, AuthorizationLevel.BLOCKED, \
                f"Too many rollbacks: {state.rollbacks_last_hour}/{self.limits.max_rollbacks_per_hour}"
        
        # Check 3: Concurrent interventions
        active_count = len([a for a in state.active_actions 
                           if a.status.value == 'executing'])
        if active_count >= self.limits.max_concurrent_interventions:
            return False, AuthorizationLevel.BLOCKED, \
                f"Too many concurrent interventions: {active_count}"
        
        # Check 4: Confidence threshold
        if action.confidence < self.limits.min_confidence_for_action:
            return False, AuthorizationLevel.BLOCKED, \
                f"Confidence too low: {action.confidence:.2f} < {self.limits.min_confidence_for_action}"
        
        # Check 5: Traffic impact
        authorization = self._determine_authorization(action)
        
        if authorization == AuthorizationLevel.BLOCKED:
            return False, authorization, "Action exceeds maximum allowed impact"
        
        return True, authorization, "Action within safety limits"
    
    def _check_rate_limit(self, state: AgentState) -> bool:
        """Check if we're within the action rate limit."""
        return state.actions_executed < self.limits.max_actions_per_hour * 24
    
    def _determine_authorization(self, action: Action) -> AuthorizationLevel:
        """Determine the required authorization level for an action."""
        
        # Map action types to base authorization levels
        action_auth_map = {
            ActionType.ADJUST_RETRY: AuthorizationLevel.AUTOMATIC,
            ActionType.ALERT_OPS: AuthorizationLevel.AUTOMATIC,
            ActionType.CIRCUIT_BREAKER: AuthorizationLevel.SEMI_AUTOMATIC,
            ActionType.ROUTE_CHANGE: AuthorizationLevel.SEMI_AUTOMATIC,
            ActionType.METHOD_SUPPRESS: AuthorizationLevel.MANUAL,
        }
        
        base_level = action_auth_map.get(action.action_type, AuthorizationLevel.MANUAL)
        
        # Escalate based on estimated impact
        impact = action.estimated_impact.get('traffic_affected_percent', 0)
        
        if impact > self.limits.manual_approve_impact_threshold:
            return AuthorizationLevel.MANUAL
        elif impact > self.limits.auto_approve_impact_threshold:
            if base_level == AuthorizationLevel.AUTOMATIC:
                return AuthorizationLevel.SEMI_AUTOMATIC
        
        return base_level
    
    def get_safety_status(self) -> Dict:
        """Get current safety status summary."""
        return {
            'limits': {
                'max_traffic_impact': self.limits.max_traffic_impact_percent,
                'max_actions_per_hour': self.limits.max_actions_per_hour,
                'max_rollbacks_per_hour': self.limits.max_rollbacks_per_hour,
            },
            'recent_blocks': self.blocked_reasons[-5:] if self.blocked_reasons else []
        }
