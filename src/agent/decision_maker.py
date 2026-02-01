"""
Decision Maker Component
Makes context-aware decisions about interventions based on patterns and hypotheses.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.models.state import (
    Action,
    ActionType,
    AgentState,
    AuthorizationLevel,
    DecisionContext,
    Hypothesis,
    Pattern,
    RiskLevel,
)


class PaymentDecisionMaker:
    """
    Makes informed decisions about payment interventions.
    
    Capabilities:
    - Multi-objective optimization (success rate, latency, cost, risk)
    - Trade-off analysis
    - Risk assessment
    - Authorization level determination
    - Explainable decision-making
    """
    
    def __init__(self):
        # Objective weights (can be tuned)
        self.weights = {
            'success_rate': 0.40,  # 40% weight on success rate
            'latency': 0.25,       # 25% weight on latency
            'cost': 0.20,          # 20% weight on cost
            'risk': 0.15           # 15% weight on risk
        }
        
        # Action configurations
        self.action_configs = self._initialize_action_configs()
        
        # Impact limits
        self.impact_limits = {
            RiskLevel.LOW: 0.05,      # Can affect up to 5% of traffic
            RiskLevel.MEDIUM: 0.10,   # Up to 10% of traffic
            RiskLevel.HIGH: 0.20,     # Up to 20% of traffic
            RiskLevel.CRITICAL: 1.00  # Can affect all traffic
        }
    
    def _initialize_action_configs(self) -> Dict[ActionType, Dict]:
        """Initialize configuration for each action type"""
        return {
            ActionType.ADJUST_RETRY: {
                'risk_level': RiskLevel.LOW,
                'authorization': AuthorizationLevel.AUTOMATIC,
                'typical_cost_impact': 0.0,  # No additional cost
                'typical_latency_impact': -50.0,  # May reduce latency
                'typical_success_impact': 0.05,  # May improve success by 5%
                'rollback_difficulty': 'easy'
            },
            ActionType.CIRCUIT_BREAKER: {
                'risk_level': RiskLevel.MEDIUM,
                'authorization': AuthorizationLevel.AUTOMATIC,
                'typical_cost_impact': 0.02,  # $0.02 per transaction to alternative
                'typical_latency_impact': -100.0,  # Faster to fail fast
                'typical_success_impact': 0.15,  # Can improve success by 15%
                'rollback_difficulty': 'easy'
            },
            ActionType.ROUTE_CHANGE: {
                'risk_level': RiskLevel.MEDIUM,
                'authorization': AuthorizationLevel.SEMI_AUTOMATIC,
                'typical_cost_impact': 0.05,  # More expensive routing
                'typical_latency_impact': 50.0,  # May add latency
                'typical_success_impact': 0.10,  # Can improve success by 10%
                'rollback_difficulty': 'medium'
            },
            ActionType.METHOD_SUPPRESS: {
                'risk_level': RiskLevel.HIGH,
                'authorization': AuthorizationLevel.MANUAL,
                'typical_cost_impact': 0.0,
                'typical_latency_impact': 0.0,
                'typical_success_impact': -0.05,  # May reduce options for users
                'rollback_difficulty': 'medium'
            },
            ActionType.ALERT_OPS: {
                'risk_level': RiskLevel.LOW,
                'authorization': AuthorizationLevel.AUTOMATIC,
                'typical_cost_impact': 0.0,
                'typical_latency_impact': 0.0,
                'typical_success_impact': 0.0,
                'rollback_difficulty': 'easy'
            },
            ActionType.NO_ACTION: {
                'risk_level': RiskLevel.LOW,
                'authorization': AuthorizationLevel.AUTOMATIC,
                'typical_cost_impact': 0.0,
                'typical_latency_impact': 0.0,
                'typical_success_impact': 0.0,
                'rollback_difficulty': 'easy'
            }
        }
    
    def decide(self, context: DecisionContext) -> Tuple[Optional[Action], str]:
        """
        Main decision method - choose the best action given the context.
        
        Args:
            context: DecisionContext with pattern, hypotheses, state, etc.
        
        Returns:
            Tuple of (selected action, reasoning)
        """
        pattern = context.pattern
        state = context.current_state
        
        # Generate possible actions
        possible_actions = self._generate_actions(pattern, context)
        
        if not possible_actions:
            return None, "No viable actions available for this pattern"
        
        # Evaluate each action
        evaluated_actions = []
        for action in possible_actions:
            score, explanation = self._evaluate_action(action, context)
            evaluated_actions.append((action, score, explanation))
        
        # Sort by score
        evaluated_actions.sort(key=lambda x: x[1], reverse=True)
        
        # Select best action
        best_action, best_score, best_explanation = evaluated_actions[0]
        
        # Check if action is allowed
        can_execute, reason = state.can_take_action(best_action)
        if not can_execute:
            return None, f"Best action blocked: {reason}"
        
        # Build comprehensive reasoning
        reasoning = self._build_reasoning(
            pattern, best_action, evaluated_actions, context
        )
        
        best_action.reasoning = reasoning
        
        return best_action, reasoning
    
    def _generate_actions(self, pattern: Pattern, context: DecisionContext) -> List[Action]:
        """Generate possible actions for a pattern"""
        actions = []
        
        if pattern.pattern_type == 'issuer_degradation':
            actions.extend(self._generate_issuer_actions(pattern, context))
        elif pattern.pattern_type == 'retry_storm':
            actions.extend(self._generate_retry_actions(pattern, context))
        elif pattern.pattern_type == 'method_fatigue':
            actions.extend(self._generate_method_actions(pattern, context))
        elif pattern.pattern_type == 'latency_spike':
            actions.extend(self._generate_latency_actions(pattern, context))
        elif pattern.pattern_type == 'error_cluster':
            actions.extend(self._generate_error_actions(pattern, context))
        elif pattern.pattern_type == 'geographic_issue':
            actions.extend(self._generate_geographic_actions(pattern, context))
        
        # Always add "do nothing" option
        actions.append(self._create_no_action(pattern))
        
        # Always add "alert ops" option
        actions.append(self._create_alert_action(pattern))
        
        return actions
    
    def _generate_issuer_actions(self, pattern: Pattern, context: DecisionContext) -> List[Action]:
        """Generate actions for issuer degradation"""
        actions = []
        issuer = pattern.affected_value
        
        # Action 1: Circuit breaker
        if issuer not in context.current_state.active_circuit_breakers:
            actions.append(Action(
                action_id='',
                action_type=ActionType.CIRCUIT_BREAKER,
                target=issuer,
                parameters={
                    'issuer': issuer,
                    'duration_minutes': 10,
                    'route_to': 'alternative_issuers'
                },
                risk_level=RiskLevel.MEDIUM,
                authorization_level=AuthorizationLevel.AUTOMATIC,
                estimated_impact={
                    'success_rate_delta': 0.15,
                    'latency_delta_ms': -200.0,
                    'cost_delta_per_txn': 0.02,
                    'affected_traffic_pct': pattern.metrics.get('volume', 0) / max(context.current_state.total_transactions, 1)
                },
                reasoning='',
                confidence=pattern.confidence,
                created_at=datetime.now()
            ))
        
        # Action 2: Route change (less aggressive)
        actions.append(Action(
            action_id='',
            action_type=ActionType.ROUTE_CHANGE,
            target=issuer,
            parameters={
                'issuer': issuer,
                'reduce_routing_pct': 50,  # Route 50% less traffic to this issuer
                'duration_minutes': 15
            },
            risk_level=RiskLevel.LOW,
            authorization_level=AuthorizationLevel.AUTOMATIC,
            estimated_impact={
                'success_rate_delta': 0.08,
                'latency_delta_ms': 20.0,
                'cost_delta_per_txn': 0.01,
                'affected_traffic_pct': pattern.metrics.get('volume', 0) / max(context.current_state.total_transactions, 1) * 0.5
            },
            reasoning='',
            confidence=pattern.confidence * 0.9,
            created_at=datetime.now()
        ))
        
        return actions
    
    def _generate_retry_actions(self, pattern: Pattern, context: DecisionContext) -> List[Action]:
        """Generate actions for retry storms"""
        actions = []
        
        # Action 1: Reduce retry aggressiveness
        actions.append(Action(
            action_id='',
            action_type=ActionType.ADJUST_RETRY,
            target='global_retry_strategy',
            parameters={
                'max_retries': 2,  # Reduce from default (e.g., 3 or 4)
                'backoff_multiplier': 2.0,  # Increase backoff
                'duration_minutes': 15
            },
            risk_level=RiskLevel.LOW,
            authorization_level=AuthorizationLevel.AUTOMATIC,
            estimated_impact={
                'success_rate_delta': -0.02,  # May reduce success slightly
                'latency_delta_ms': -100.0,  # Will reduce latency
                'cost_delta_per_txn': -0.005,  # Lower processing costs
                'affected_traffic_pct': pattern.metrics.get('retry_percentage', 0)
            },
            reasoning='',
            confidence=pattern.confidence,
            created_at=datetime.now()
        ))
        
        return actions
    
    def _generate_method_actions(self, pattern: Pattern, context: DecisionContext) -> List[Action]:
        """Generate actions for payment method fatigue"""
        actions = []
        method = pattern.affected_value
        
        # Action 1: Reduce retries for this method
        actions.append(Action(
            action_id='',
            action_type=ActionType.ADJUST_RETRY,
            target=f'method_{method}',
            parameters={
                'payment_method': method,
                'max_retries': 1,  # Limit retries for fatigued method
                'duration_minutes': 20
            },
            risk_level=RiskLevel.LOW,
            authorization_level=AuthorizationLevel.AUTOMATIC,
            estimated_impact={
                'success_rate_delta': 0.05,  # Better user experience
                'latency_delta_ms': -150.0,
                'cost_delta_per_txn': 0.0,
                'affected_traffic_pct': pattern.metrics.get('volume', 0) / max(context.current_state.total_transactions, 1)
            },
            reasoning='',
            confidence=pattern.confidence,
            created_at=datetime.now()
        ))
        
        return actions
    
    def _generate_latency_actions(self, pattern: Pattern, context: DecisionContext) -> List[Action]:
        """Generate actions for latency spikes"""
        actions = []
        
        # Action 1: Reduce timeouts to fail faster
        actions.append(Action(
            action_id='',
            action_type=ActionType.ADJUST_RETRY,
            target='timeout_settings',
            parameters={
                'timeout_ms': 3000,  # Reduce timeout to 3 seconds
                'duration_minutes': 10
            },
            risk_level=RiskLevel.LOW,
            authorization_level=AuthorizationLevel.AUTOMATIC,
            estimated_impact={
                'success_rate_delta': -0.03,  # May fail some slow transactions
                'latency_delta_ms': -500.0,  # Significant latency improvement
                'cost_delta_per_txn': 0.0,
                'affected_traffic_pct': 1.0  # Affects all traffic
            },
            reasoning='',
            confidence=pattern.confidence * 0.8,
            created_at=datetime.now()
        ))
        
        return actions
    
    def _generate_error_actions(self, pattern: Pattern, context: DecisionContext) -> List[Action]:
        """Generate actions for error clusters"""
        # For error clusters, primarily alert ops team
        return []
    
    def _generate_geographic_actions(self, pattern: Pattern, context: DecisionContext) -> List[Action]:
        """Generate actions for geographic issues"""
        actions = []
        region = pattern.affected_value
        
        # Action 1: Route to different processors for this region
        actions.append(Action(
            action_id='',
            action_type=ActionType.ROUTE_CHANGE,
            target=f'region_{region}',
            parameters={
                'region': region,
                'alternative_routing': True,
                'duration_minutes': 20
            },
            risk_level=RiskLevel.MEDIUM,
            authorization_level=AuthorizationLevel.SEMI_AUTOMATIC,
            estimated_impact={
                'success_rate_delta': 0.20,  # Significant improvement expected
                'latency_delta_ms': 100.0,  # May add latency
                'cost_delta_per_txn': 0.03,
                'affected_traffic_pct': pattern.metrics.get('volume', 0) / max(context.current_state.total_transactions, 1)
            },
            reasoning='',
            confidence=pattern.confidence,
            created_at=datetime.now()
        ))
        
        return actions
    
    def _create_no_action(self, pattern: Pattern) -> Action:
        """Create a 'do nothing' action"""
        return Action(
            action_id='',
            action_type=ActionType.NO_ACTION,
            target='none',
            parameters={},
            risk_level=RiskLevel.LOW,
            authorization_level=AuthorizationLevel.AUTOMATIC,
            estimated_impact={
                'success_rate_delta': 0.0,
                'latency_delta_ms': 0.0,
                'cost_delta_per_txn': 0.0,
                'affected_traffic_pct': 0.0
            },
            reasoning='Monitor situation without intervention',
            confidence=1.0,
            created_at=datetime.now()
        )
    
    def _create_alert_action(self, pattern: Pattern) -> Action:
        """Create an 'alert ops team' action"""
        return Action(
            action_id='',
            action_type=ActionType.ALERT_OPS,
            target='ops_team',
            parameters={
                'pattern_type': pattern.pattern_type,
                'severity': pattern.severity,
                'description': pattern.description
            },
            risk_level=RiskLevel.LOW,
            authorization_level=AuthorizationLevel.AUTOMATIC,
            estimated_impact={
                'success_rate_delta': 0.0,
                'latency_delta_ms': 0.0,
                'cost_delta_per_txn': 0.0,
                'affected_traffic_pct': 0.0
            },
            reasoning='Notify operations team for awareness',
            confidence=1.0,
            created_at=datetime.now()
        )
    
    def _evaluate_action(self, action: Action, context: DecisionContext) -> Tuple[float, str]:
        """
        Evaluate an action using multi-objective optimization.
        
        Returns:
            Tuple of (score, explanation)
        """
        impact = action.estimated_impact
        
        # Calculate individual objective scores (0-1, higher is better)
        success_score = self._score_success_impact(
            impact.get('success_rate_delta', 0.0),
            context.pattern.severity
        )
        
        latency_score = self._score_latency_impact(
            impact.get('latency_delta_ms', 0.0),
            context.current_state.average_latency_ms
        )
        
        cost_score = self._score_cost_impact(
            impact.get('cost_delta_per_txn', 0.0)
        )
        
        risk_score = self._score_risk(
            action.risk_level,
            impact.get('affected_traffic_pct', 0.0),
            context.current_state
        )
        
        # Weighted combination
        total_score = (
            self.weights['success_rate'] * success_score +
            self.weights['latency'] * latency_score +
            self.weights['cost'] * cost_score +
            self.weights['risk'] * risk_score
        )
        
        # Apply confidence factor
        total_score *= action.confidence
        
        explanation = (
            f"Success: {success_score:.2f}, "
            f"Latency: {latency_score:.2f}, "
            f"Cost: {cost_score:.2f}, "
            f"Risk: {risk_score:.2f}, "
            f"Total: {total_score:.2f}"
        )
        
        return total_score, explanation
    
    def _score_success_impact(self, delta: float, pattern_severity: float) -> float:
        """Score the success rate impact (higher delta = better)"""
        # Positive delta is good, scale by pattern severity
        if delta > 0:
            return min(delta / 0.20 * pattern_severity, 1.0)
        else:
            # Negative delta is bad
            return max(0.0, 1.0 + delta / 0.10)
    
    def _score_latency_impact(self, delta_ms: float, current_latency: float) -> float:
        """Score latency impact (negative delta = better, means reduction)"""
        # Negative delta (reduction) is good
        if delta_ms < 0:
            reduction_pct = abs(delta_ms) / max(current_latency, 100)
            return min(reduction_pct * 2, 1.0)
        else:
            # Positive delta (increase) is bad
            increase_pct = delta_ms / max(current_latency, 100)
            return max(0.0, 1.0 - increase_pct)
    
    def _score_cost_impact(self, delta_per_txn: float) -> float:
        """Score cost impact (lower delta = better)"""
        # No cost increase is perfect
        if delta_per_txn == 0:
            return 1.0
        # Small increases are acceptable
        elif delta_per_txn <= 0.02:
            return 0.8
        # Medium increases are okay
        elif delta_per_txn <= 0.05:
            return 0.5
        # Large increases are bad
        else:
            return 0.2
    
    def _score_risk(self, risk_level: RiskLevel, affected_pct: float, state: AgentState) -> float:
        """Score the risk of an action (lower risk = better)"""
        # Base risk score
        risk_scores = {
            RiskLevel.LOW: 1.0,
            RiskLevel.MEDIUM: 0.7,
            RiskLevel.HIGH: 0.4,
            RiskLevel.CRITICAL: 0.1
        }
        base_score = risk_scores.get(risk_level, 0.5)
        
        # Penalize if affecting too much traffic
        limit = self.impact_limits[risk_level]
        if affected_pct > limit:
            penalty = (affected_pct - limit) / limit
            base_score *= max(0.1, 1.0 - penalty)
        
        # Penalize if recent rollbacks
        if state.rollbacks_last_hour > 0:
            base_score *= 0.8
        
        return base_score
    
    def _build_reasoning(
        self,
        pattern: Pattern,
        selected_action: Action,
        all_evaluated: List[Tuple[Action, float, str]],
        context: DecisionContext
    ) -> str:
        """Build comprehensive reasoning for the decision"""
        
        reasoning_parts = []
        
        # Context
        reasoning_parts.append(f"## Pattern Detected\n")
        reasoning_parts.append(f"Type: {pattern.pattern_type}")
        reasoning_parts.append(f"Severity: {pattern.severity:.2f}")
        reasoning_parts.append(f"Description: {pattern.description}")
        reasoning_parts.append(f"Confidence: {pattern.confidence:.2f}\n")
        
        # Hypotheses
        if context.hypotheses:
            reasoning_parts.append(f"## Hypothesized Root Causes\n")
            for hyp in sorted(context.hypotheses, key=lambda h: h.probability, reverse=True)[:3]:
                reasoning_parts.append(
                    f"- {hyp.root_cause} (probability: {hyp.probability:.2f})"
                )
            reasoning_parts.append("")
        
        # Selected action
        reasoning_parts.append(f"## Selected Action\n")
        reasoning_parts.append(f"Type: {selected_action.action_type.value}")
        reasoning_parts.append(f"Target: {selected_action.target}")
        reasoning_parts.append(f"Risk Level: {selected_action.risk_level.value}")
        reasoning_parts.append(f"Authorization: {selected_action.authorization_level.value}\n")
        
        # Expected impact
        reasoning_parts.append(f"## Expected Impact\n")
        impact = selected_action.estimated_impact
        reasoning_parts.append(f"- Success Rate: {impact.get('success_rate_delta', 0):.1%} change")
        reasoning_parts.append(f"- Latency: {impact.get('latency_delta_ms', 0):.0f}ms change")
        reasoning_parts.append(f"- Cost: ${impact.get('cost_delta_per_txn', 0):.3f} per transaction")
        reasoning_parts.append(f"- Affected Traffic: {impact.get('affected_traffic_pct', 0):.1%}\n")
        
        # Alternatives considered
        reasoning_parts.append(f"## Alternatives Considered\n")
        for action, score, explanation in all_evaluated[:3]:
            if action.action_id == selected_action.action_id:
                continue
            reasoning_parts.append(
                f"- {action.action_type.value}: score {score:.2f} ({explanation})"
            )
        
        return "\n".join(reasoning_parts)
