"""
Learner Component
Learns from action outcomes to improve future decisions.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np

from src.models.state import Action, Pattern


class PaymentLearner:
    """
    Learns from past actions and outcomes to improve agent performance.
    
    Capabilities:
    - Action outcome tracking
    - Pattern effectiveness learning
    - Strategy refinement
    - Threshold adjustment
    """
    
    def __init__(self):
        # Action effectiveness tracking
        self.action_outcomes: Dict[str, List[Dict]] = defaultdict(list)
        
        # Pattern detection refinement
        self.pattern_accuracy: Dict[str, Dict] = defaultdict(
            lambda: {'true_positives': 0, 'false_positives': 0, 'true_negatives': 0}
        )
        
        # Decision quality metrics
        self.decision_quality: List[Dict] = []
        
        # Learned parameters
        self.learned_thresholds = {}
        self.learned_weights = {}
    
    def record_outcome(
        self,
        action: Action,
        baseline_metrics: Dict,
        actual_metrics: Dict
    ):
        """
        Record the outcome of an executed action.
        
        Args:
            action: The executed action
            baseline_metrics: Metrics before action
            actual_metrics: Metrics after action
        """
        # Calculate actual impact
        actual_impact = {
            'success_rate_delta': (
                actual_metrics.get('success_rate', 0) -
                baseline_metrics.get('success_rate', 0)
            ),
            'latency_delta': (
                actual_metrics.get('avg_latency', 0) -
                baseline_metrics.get('avg_latency', 0)
            ),
            'timestamp': datetime.now()
        }
        
        # Compare to estimated impact
        estimated_impact = action.estimated_impact
        
        outcome = {
            'action_id': action.action_id,
            'action_type': action.action_type.value,
            'target': action.target,
            'estimated_impact': estimated_impact,
            'actual_impact': actual_impact,
            'prediction_error': self._calculate_prediction_error(
                estimated_impact, actual_impact
            ),
            'baseline_metrics': baseline_metrics,
            'actual_metrics': actual_metrics,
            'recorded_at': datetime.now()
        }
        
        # Store outcome
        action_key = f"{action.action_type.value}_{action.target}"
        self.action_outcomes[action_key].append(outcome)
        
        # Update action's actual impact
        action.actual_impact = actual_impact
    
    def _calculate_prediction_error(
        self,
        estimated: Dict,
        actual: Dict
    ) -> float:
        """Calculate error between estimated and actual impact"""
        # Mean absolute percentage error
        errors = []
        
        for key in ['success_rate_delta', 'latency_delta_ms']:
            est_val = estimated.get(key, 0)
            act_val = actual.get(key.replace('_ms', ''), 0)
            
            if abs(est_val) > 0.001:  # Avoid division by zero
                error = abs((est_val - act_val) / est_val)
                errors.append(error)
        
        return np.mean(errors) if errors else 0.0
    
    def evaluate_pattern_detection(
        self,
        pattern: Pattern,
        was_valid: bool
    ):
        """
        Evaluate whether a detected pattern was a true positive or false positive.
        
        Args:
            pattern: The detected pattern
            was_valid: Whether the pattern was genuinely problematic
        """
        pattern_type = pattern.pattern_type
        
        if was_valid:
            self.pattern_accuracy[pattern_type]['true_positives'] += 1
        else:
            self.pattern_accuracy[pattern_type]['false_positives'] += 1
    
    def get_action_effectiveness(
        self,
        action_type: str,
        target: str = None
    ) -> Dict[str, float]:
        """
        Get effectiveness statistics for an action type.
        
        Returns:
            Dictionary with success rate, avg improvement, prediction accuracy
        """
        if target:
            action_key = f"{action_type}_{target}"
        else:
            # Aggregate across all targets for this action type
            action_key = action_type
        
        outcomes = self.action_outcomes.get(action_key, [])
        
        if not outcomes:
            return {
                'sample_size': 0,
                'avg_success_improvement': 0.0,
                'avg_latency_improvement': 0.0,
                'prediction_accuracy': 0.0,
                'success_rate': 0.0
            }
        
        success_improvements = []
        latency_improvements = []
        prediction_errors = []
        successes = 0
        
        for outcome in outcomes:
            actual = outcome['actual_impact']
            
            # Success improvement
            success_delta = actual.get('success_rate_delta', 0)
            success_improvements.append(success_delta)
            
            # Latency improvement (negative is good)
            latency_delta = actual.get('latency_delta', 0)
            latency_improvements.append(-latency_delta)  # Invert so positive is good
            
            # Prediction error
            prediction_errors.append(outcome['prediction_error'])
            
            # Count as success if improved success rate
            if success_delta > 0:
                successes += 1
        
        return {
            'sample_size': len(outcomes),
            'avg_success_improvement': float(np.mean(success_improvements)),
            'avg_latency_improvement': float(np.mean(latency_improvements)),
            'prediction_accuracy': 1.0 - float(np.mean(prediction_errors)),
            'success_rate': successes / len(outcomes)
        }
    
    def get_pattern_accuracy(self, pattern_type: str) -> Dict[str, float]:
        """
        Get accuracy statistics for a pattern type.
        
        Returns:
            Dictionary with precision, recall, etc.
        """
        stats = self.pattern_accuracy[pattern_type]
        tp = stats['true_positives']
        fp = stats['false_positives']
        
        if tp + fp == 0:
            precision = 1.0
        else:
            precision = tp / (tp + fp)
        
        return {
            'precision': precision,
            'true_positives': tp,
            'false_positives': fp,
            'total_detections': tp + fp
        }
    
    def recommend_threshold_adjustments(
        self,
        reasoner
    ) -> Dict[str, float]:
        """
        Recommend adjustments to pattern detection thresholds based on learned accuracy.
        
        Args:
            reasoner: PaymentReasoner instance
        
        Returns:
            Dictionary of recommended threshold adjustments
        """
        recommendations = {}
        
        for pattern_type, accuracy in self.pattern_accuracy.items():
            precision = self.get_pattern_accuracy(pattern_type)['precision']
            
            current_threshold = reasoner.thresholds.get(pattern_type)
            if current_threshold is None:
                continue
            
            # If too many false positives, increase threshold
            if precision < 0.70:
                adjustment = 1.2  # Increase by 20%
                recommendations[pattern_type] = current_threshold * adjustment
            
            # If very high precision, could lower threshold to catch more
            elif precision > 0.95 and accuracy['true_positives'] > 10:
                adjustment = 0.9  # Decrease by 10%
                recommendations[pattern_type] = current_threshold * adjustment
        
        return recommendations
    
    def get_learning_summary(self) -> Dict:
        """Get a summary of what the agent has learned"""
        summary = {
            'total_outcomes_recorded': sum(
                len(outcomes) for outcomes in self.action_outcomes.values()
            ),
            'action_effectiveness': {},
            'pattern_accuracy': {},
            'top_actions': [],
            'generated_at': datetime.now().isoformat()
        }
        
        # Action effectiveness
        for action_key in self.action_outcomes.keys():
            effectiveness = self.get_action_effectiveness(action_key)
            if effectiveness['sample_size'] >= 3:  # Only include if enough samples
                summary['action_effectiveness'][action_key] = effectiveness
        
        # Pattern accuracy
        for pattern_type in self.pattern_accuracy.keys():
            summary['pattern_accuracy'][pattern_type] = self.get_pattern_accuracy(pattern_type)
        
        # Top actions by effectiveness
        action_scores = []
        for action_key, outcomes in self.action_outcomes.items():
            if len(outcomes) >= 3:
                effectiveness = self.get_action_effectiveness(action_key)
                score = (
                    effectiveness['avg_success_improvement'] * 0.6 +
                    effectiveness['prediction_accuracy'] * 0.4
                )
                action_scores.append((action_key, score, effectiveness))
        
        action_scores.sort(key=lambda x: x[1], reverse=True)
        summary['top_actions'] = [
            {
                'action': action,
                'score': score,
                'details': details
            }
            for action, score, details in action_scores[:5]
        ]
        
        return summary
    
    def update_decision_weights(
        self,
        decision_maker,
        learning_rate: float = 0.1
    ):
        """
        Update decision maker's objective weights based on outcomes.
        
        This implements a simple reinforcement learning approach.
        """
        # Calculate correlation between each objective and actual success
        objective_scores = {
            'success_rate': [],
            'latency': [],
            'cost': [],
            'risk': []
        }
        
        for outcomes in self.action_outcomes.values():
            for outcome in outcomes:
                actual_success = outcome['actual_impact'].get('success_rate_delta', 0)
                
                # Simplified: just track if objectives aligned with success
                if actual_success > 0:
                    # This action was successful
                    estimated = outcome['estimated_impact']
                    
                    # Check which objectives were positive
                    if estimated.get('success_rate_delta', 0) > 0:
                        objective_scores['success_rate'].append(1.0)
                    if estimated.get('latency_delta_ms', 0) < 0:  # Negative latency is good
                        objective_scores['latency'].append(1.0)
                    if estimated.get('cost_delta_per_txn', 0) <= 0.02:  # Low cost is good
                        objective_scores['cost'].append(1.0)
        
        # Update weights based on which objectives correlate with success
        for objective, scores in objective_scores.items():
            if scores:
                avg_score = np.mean(scores)
                current_weight = decision_maker.weights.get(objective, 0.25)
                
                # Adjust weight toward objectives that lead to success
                new_weight = current_weight + learning_rate * (avg_score - 0.5)
                decision_maker.weights[objective] = max(0.05, min(0.60, new_weight))
        
        # Normalize weights to sum to 1.0
        total_weight = sum(decision_maker.weights.values())
        for objective in decision_maker.weights:
            decision_maker.weights[objective] /= total_weight
