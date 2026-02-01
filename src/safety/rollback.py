"""
Automatic Rollback Logic
Detects when actions are causing harm and triggers automatic rollback.
Implements the problem statement requirement:
"how incorrect decisions are detected and rolled back"
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.models.state import Action


@dataclass
class RollbackThresholds:
    """Thresholds that trigger automatic rollback."""
    
    # Success rate drop (absolute)
    success_rate_drop: float = 0.05
    
    # Latency increase (percentage)
    latency_increase_percent: float = 50.0
    
    # Error rate increase (absolute)
    error_rate_increase: float = 0.10
    
    # Cost increase (percentage)
    cost_increase_percent: float = 20.0
    
    # Monitoring window (seconds)
    monitoring_window_seconds: int = 300


class RollbackManager:
    """
    Monitors action outcomes and triggers automatic rollback when needed.
    """
    
    def __init__(self, thresholds: Optional[RollbackThresholds] = None):
        self.thresholds = thresholds or RollbackThresholds()
        self.baseline_metrics: Dict = {}
        self.rollback_history: List[Dict] = []
    
    def set_baseline(self, metrics: Dict):
        """Set baseline metrics before an action is executed."""
        self.baseline_metrics = {
            'success_rate': metrics.get('success_rate', 0.95),
            'avg_latency_ms': metrics.get('avg_latency_ms', 200),
            'error_rate': metrics.get('error_rate', 0.05),
            'cost_per_txn': metrics.get('cost_per_txn', 0.10),
            'timestamp': datetime.now()
        }
    
    def check_rollback_needed(
        self,
        action: Action,
        current_metrics: Dict
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an action should be rolled back based on current metrics.
        
        Returns:
            Tuple of (should_rollback, reason)
        """
        if not self.baseline_metrics:
            return False, None
        
        baseline = self.baseline_metrics
        
        # Check 1: Success rate dropped
        success_drop = baseline['success_rate'] - current_metrics.get('success_rate', 0)
        if success_drop > self.thresholds.success_rate_drop:
            reason = f"Success rate dropped by {success_drop:.1%} (threshold: {self.thresholds.success_rate_drop:.1%})"
            self._record_rollback(action, reason)
            return True, reason
        
        # Check 2: Latency increased
        if baseline['avg_latency_ms'] > 0:
            latency_increase = (
                (current_metrics.get('avg_latency_ms', 0) - baseline['avg_latency_ms']) 
                / baseline['avg_latency_ms'] * 100
            )
            if latency_increase > self.thresholds.latency_increase_percent:
                reason = f"Latency increased by {latency_increase:.0f}% (threshold: {self.thresholds.latency_increase_percent:.0f}%)"
                self._record_rollback(action, reason)
                return True, reason
        
        # Check 3: Error rate increased
        error_increase = current_metrics.get('error_rate', 0) - baseline.get('error_rate', 0)
        if error_increase > self.thresholds.error_rate_increase:
            reason = f"Error rate increased by {error_increase:.1%} (threshold: {self.thresholds.error_rate_increase:.1%})"
            self._record_rollback(action, reason)
            return True, reason
        
        return False, None
    
    def _record_rollback(self, action: Action, reason: str):
        """Record a rollback event."""
        self.rollback_history.append({
            'action_id': action.action_id,
            'action_type': action.action_type.value,
            'target': action.target,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })
    
    def execute_rollback(self, action: Action) -> Dict:
        """
        Execute rollback for an action.
        
        Returns:
            Rollback result details
        """
        # Mark action as rolled back
        action.rolled_back_at = datetime.now()
        
        return {
            'action_id': action.action_id,
            'action_type': action.action_type.value,
            'rolled_back': True,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_rollback_history(self, limit: int = 10) -> List[Dict]:
        """Get recent rollback history."""
        return self.rollback_history[-limit:]
