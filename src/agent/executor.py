"""
Executor Component
Executes actions with safety guardrails and monitoring.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.models.state import Action, ActionType, AgentState, AuthorizationLevel


class PaymentExecutor:
    """
    Executes payment operations actions safely with guardrails.
    
    Responsibilities:
    - Execute approved actions
    - Monitor action outcomes
    - Trigger automatic rollbacks
    - Maintain audit trail
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Rollback triggers
        self.rollback_thresholds = {
            'success_rate_drop': 0.05,  # 5% drop triggers rollback
            'latency_increase': 0.50,   # 50% increase triggers rollback
            'error_rate_increase': 0.10,  # 10% increase triggers rollback
            'cost_increase': 0.20        # 20% increase triggers rollback
        }
        
        # Action execution log
        self.execution_log: List[Dict] = []
        
        # Active interventions
        self.active_interventions: Dict[str, Action] = {}
    
    def execute(
        self,
        action: Action,
        state: AgentState,
        observer
    ) -> Tuple[bool, str]:
        """
        Execute an action with safety checks.
        
        Args:
            action: Action to execute
            state: Current agent state
            observer: Payment observer for baseline metrics
        
        Returns:
            Tuple of (success, message)
        """
        # Pre-execution checks
        can_execute, reason = self._pre_execution_checks(action, state)
        if not can_execute:
            self.logger.warning(f"Action {action.action_id} blocked: {reason}")
            return False, reason
        
        # Record baseline metrics before action
        baseline_metrics = self._capture_baseline_metrics(observer)
        
        # Execute based on action type
        success, message = self._execute_by_type(action, state)
        
        if success:
            action.status = "executed"
            action.executed_at = datetime.now()
            self.active_interventions[action.action_id] = action
            
            # Log execution
            self._log_execution(action, baseline_metrics, success, message)
            
            # Update state
            state.actions_taken_last_hour += 1
            state.actions_executed += 1
            
            self.logger.info(
                f"Action {action.action_id} ({action.action_type.value}) "
                f"executed successfully: {message}"
            )
        else:
            action.status = "failed"
            self.logger.error(
                f"Action {action.action_id} ({action.action_type.value}) "
                f"failed: {message}"
            )
        
        return success, message
    
    def _pre_execution_checks(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, str]:
        """Perform safety checks before execution"""
        
        # Check authorization
        if action.authorization_level == AuthorizationLevel.MANUAL:
            if not action.approver:
                return False, "Manual authorization required"
        
        if action.authorization_level == AuthorizationLevel.SEMI_AUTOMATIC:
            if not action.approver and action.risk_level.value != 'low':
                return False, "Semi-automatic action requires approval for non-low risk"
        
        # Check state constraints
        can_take_action, reason = state.can_take_action(action)
        if not can_take_action:
            return False, reason
        
        # Check if similar action is already active
        for active_action in self.active_interventions.values():
            if (active_action.action_type == action.action_type and
                active_action.target == action.target):
                return False, f"Similar action already active: {active_action.action_id}"
        
        return True, "Checks passed"
    
    def _execute_by_type(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, str]:
        """Execute action based on its type"""
        
        if action.action_type == ActionType.CIRCUIT_BREAKER:
            return self._execute_circuit_breaker(action, state)
        elif action.action_type == ActionType.ADJUST_RETRY:
            return self._execute_retry_adjustment(action, state)
        elif action.action_type == ActionType.ROUTE_CHANGE:
            return self._execute_route_change(action, state)
        elif action.action_type == ActionType.METHOD_SUPPRESS:
            return self._execute_method_suppress(action, state)
        elif action.action_type == ActionType.ALERT_OPS:
            return self._execute_alert(action, state)
        elif action.action_type == ActionType.NO_ACTION:
            return True, "No action taken (monitoring only)"
        else:
            return False, f"Unknown action type: {action.action_type}"
    
    def _execute_circuit_breaker(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, str]:
        """Execute circuit breaker action"""
        issuer = action.parameters.get('issuer')
        duration_minutes = action.parameters.get('duration_minutes', 10)
        
        if not issuer:
            return False, "No issuer specified"
        
        # Activate circuit breaker
        state.active_circuit_breakers.add(issuer)
        
        self.logger.info(
            f"Circuit breaker activated for issuer {issuer} "
            f"for {duration_minutes} minutes"
        )
        
        return True, f"Circuit breaker activated for {issuer}"
    
    def _execute_retry_adjustment(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, str]:
        """Execute retry strategy adjustment"""
        target = action.target
        max_retries = action.parameters.get('max_retries')
        backoff_multiplier = action.parameters.get('backoff_multiplier')
        timeout_ms = action.parameters.get('timeout_ms')
        
        # Update retry strategy
        strategy = state.retry_strategies.get(target, {})
        
        if max_retries is not None:
            strategy['max_retries'] = max_retries
        if backoff_multiplier is not None:
            strategy['backoff_multiplier'] = backoff_multiplier
        if timeout_ms is not None:
            strategy['timeout_ms'] = timeout_ms
        
        state.retry_strategies[target] = strategy
        
        self.logger.info(f"Retry strategy updated for {target}: {strategy}")
        
        return True, f"Retry strategy adjusted for {target}"
    
    def _execute_route_change(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, str]:
        """Execute routing change"""
        target = action.target
        
        # Store routing override
        state.routing_overrides[target] = {
            'alternative_routing': action.parameters.get('alternative_routing', False),
            'reduce_routing_pct': action.parameters.get('reduce_routing_pct', 0),
            'applied_at': datetime.now()
        }
        
        self.logger.info(f"Routing changed for {target}")
        
        return True, f"Routing adjusted for {target}"
    
    def _execute_method_suppress(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, str]:
        """Execute payment method suppression"""
        method = action.parameters.get('payment_method')
        
        if not method:
            return False, "No payment method specified"
        
        state.suppressed_methods.add(method)
        
        self.logger.warning(f"Payment method {method} suppressed")
        
        return True, f"Payment method {method} temporarily suppressed"
    
    def _execute_alert(
        self,
        action: Action,
        state: AgentState
    ) -> Tuple[bool, str]:
        """Execute ops team alert"""
        pattern_type = action.parameters.get('pattern_type')
        severity = action.parameters.get('severity', 0)
        description = action.parameters.get('description', 'No description')
        
        # In a real system, this would send to PagerDuty, Slack, etc.
        alert_message = (
            f"PAYMENT ALERT\n"
            f"Type: {pattern_type}\n"
            f"Severity: {severity:.2f}\n"
            f"Description: {description}\n"
            f"Timestamp: {datetime.now().isoformat()}"
        )
        
        self.logger.warning(alert_message)
        
        # Simulate sending alert
        print(f"\n🚨 {alert_message}\n")
        
        return True, "Alert sent to ops team"
    
    def _capture_baseline_metrics(self, observer) -> Dict:
        """Capture baseline metrics before action"""
        return {
            'success_rate': observer.get_success_rate('overall', 'current'),
            'avg_latency': observer.get_latency_stats('overall').get('mean', 0),
            'transaction_volume': observer.get_transaction_volume('overall', 'current'),
            'timestamp': datetime.now()
        }
    
    def _log_execution(
        self,
        action: Action,
        baseline_metrics: Dict,
        success: bool,
        message: str
    ):
        """Log action execution"""
        log_entry = {
            'action_id': action.action_id,
            'action_type': action.action_type.value,
            'target': action.target,
            'executed_at': datetime.now().isoformat(),
            'success': success,
            'message': message,
            'baseline_metrics': baseline_metrics,
            'estimated_impact': action.estimated_impact,
            'parameters': action.parameters
        }
        
        self.execution_log.append(log_entry)
    
    def monitor_and_rollback(
        self,
        state: AgentState,
        observer
    ) -> List[str]:
        """
        Monitor active interventions and trigger rollbacks if needed.
        
        Returns:
            List of action IDs that were rolled back
        """
        rolled_back = []
        current_metrics = self._capture_baseline_metrics(observer)
        
        for action_id, action in list(self.active_interventions.items()):
            # Find baseline for this action
            baseline = self._find_baseline_for_action(action_id)
            if not baseline:
                continue
            
            # Check for rollback conditions
            should_rollback, reason = self._should_rollback(
                action, baseline, current_metrics
            )
            
            if should_rollback:
                success = self._rollback_action(action, state)
                if success:
                    rolled_back.append(action_id)
                    state.rollbacks_last_hour += 1
                    self.logger.warning(
                        f"Action {action_id} rolled back: {reason}"
                    )
                    print(f"\n⚠️  ROLLBACK: {action.action_type.value} for {action.target} - {reason}\n")
        
        return rolled_back
    
    def _should_rollback(
        self,
        action: Action,
        baseline: Dict,
        current: Dict
    ) -> Tuple[bool, str]:
        """Determine if action should be rolled back"""
        
        # Check success rate
        success_drop = baseline['success_rate'] - current['success_rate']
        if success_drop > self.rollback_thresholds['success_rate_drop']:
            return True, f"Success rate dropped {success_drop:.1%}"
        
        # Check latency
        if baseline['avg_latency'] > 0:
            latency_increase = (
                (current['avg_latency'] - baseline['avg_latency']) /
                baseline['avg_latency']
            )
            if latency_increase > self.rollback_thresholds['latency_increase']:
                return True, f"Latency increased {latency_increase:.1%}"
        
        # Check if action duration has expired
        if action.executed_at:
            duration = datetime.now() - action.executed_at
            max_duration = timedelta(
                minutes=action.parameters.get('duration_minutes', 30)
            )
            if duration > max_duration:
                return True, "Action duration expired"
        
        return False, ""
    
    def _rollback_action(self, action: Action, state: AgentState) -> bool:
        """Rollback an executed action"""
        
        try:
            if action.action_type == ActionType.CIRCUIT_BREAKER:
                issuer = action.parameters.get('issuer')
                state.active_circuit_breakers.discard(issuer)
            
            elif action.action_type == ActionType.ADJUST_RETRY:
                target = action.target
                if target in state.retry_strategies:
                    del state.retry_strategies[target]
            
            elif action.action_type == ActionType.ROUTE_CHANGE:
                target = action.target
                if target in state.routing_overrides:
                    del state.routing_overrides[target]
            
            elif action.action_type == ActionType.METHOD_SUPPRESS:
                method = action.parameters.get('payment_method')
                state.suppressed_methods.discard(method)
            
            # Remove from active interventions
            if action.action_id in self.active_interventions:
                del self.active_interventions[action.action_id]
            
            action.status = "rolled_back"
            action.completed_at = datetime.now()
            
            return True
        
        except Exception as e:
            self.logger.error(f"Rollback failed for {action.action_id}: {e}")
            return False
    
    def _find_baseline_for_action(self, action_id: str) -> Optional[Dict]:
        """Find the baseline metrics for an action"""
        for log_entry in reversed(self.execution_log):
            if log_entry['action_id'] == action_id:
                return log_entry.get('baseline_metrics')
        return None
    
    def get_active_interventions(self) -> List[Action]:
        """Get list of currently active interventions"""
        return list(self.active_interventions.values())
    
    def get_execution_history(self, limit: int = 50) -> List[Dict]:
        """Get recent execution history"""
        return self.execution_log[-limit:]
