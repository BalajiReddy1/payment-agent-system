"""
Payment Agent Core
Main orchestrator that coordinates all agent components.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from src.models.state import AgentMemory, AgentState, DecisionContext, PaymentTransaction
from src.agent.decision_maker import PaymentDecisionMaker
from src.agent.executor import PaymentExecutor
from src.agent.learner import PaymentLearner
from src.agent.observer import PaymentObserver
from src.agent.reasoner import PaymentReasoner


class PaymentAgent:
    """
    Autonomous payment operations agent.
    
    Implements the complete agent loop:
    Observe → Reason → Decide → Act → Learn
    """
    
    def __init__(
        self,
        window_size_minutes: int = 10,
        analysis_interval_seconds: int = 30,
        auto_approve_low_risk: bool = True
    ):
        """
        Initialize the payment agent.
        
        Args:
            window_size_minutes: Sliding window size for observations
            analysis_interval_seconds: How often to run analysis
            auto_approve_low_risk: Whether to auto-approve low-risk actions
        """
        # Core components
        self.observer = PaymentObserver(window_size_minutes=window_size_minutes)
        self.reasoner = PaymentReasoner()
        self.decision_maker = PaymentDecisionMaker()
        self.executor = PaymentExecutor()
        self.learner = PaymentLearner()
        
        # Agent state
        self.state = AgentState()
        self.memory = AgentMemory()
        
        # Configuration
        self.analysis_interval = analysis_interval_seconds
        self.auto_approve_low_risk = auto_approve_low_risk
        
        # Logging
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Metrics
        self.cycle_count = 0
        self.last_analysis_time = None
    
    def process_transaction(self, transaction: PaymentTransaction):
        """
        Process a single incoming transaction.
        
        This is the entry point for streaming payment data.
        """
        self.observer.ingest_transaction(transaction)
    
    def process_batch(self, transactions: List[PaymentTransaction]):
        """Process a batch of transactions"""
        self.observer.ingest_batch(transactions)
    
    def run_cycle(self) -> Dict:
        """
        Execute one complete agent cycle: Observe → Reason → Decide → Act → Learn
        
        Returns:
            Dictionary with cycle results and metrics
        """
        self.cycle_count += 1
        cycle_start = time.time()
        
        self.logger.info(f"Starting agent cycle #{self.cycle_count}")
        
        results = {
            'cycle': self.cycle_count,
            'timestamp': datetime.now().isoformat(),
            'patterns_detected': [],
            'actions_taken': [],
            'rollbacks_executed': [],
            'learning_updates': {}
        }
        
        try:
            # 1. OBSERVE: Update state with current observations
            self._observe_phase(results)
            
            # 2. REASON: Detect patterns and form hypotheses
            patterns = self._reason_phase(results)
            
            # 3. DECIDE & ACT: Make decisions and execute actions
            if patterns:
                self._decide_and_act_phase(patterns, results)
            
            # 4. MONITOR: Check for rollbacks
            self._monitor_phase(results)
            
            # 5. LEARN: Update from outcomes
            self._learn_phase(results)
            
            # Update baselines
            self.reasoner.update_baselines(self.observer)
            
        except Exception as e:
            self.logger.error(f"Error in agent cycle: {e}", exc_info=True)
            results['error'] = str(e)
        
        cycle_duration = time.time() - cycle_start
        results['cycle_duration_seconds'] = cycle_duration
        self.last_analysis_time = datetime.now()
        
        self.logger.info(
            f"Cycle #{self.cycle_count} completed in {cycle_duration:.2f}s - "
            f"{len(results['patterns_detected'])} patterns, "
            f"{len(results['actions_taken'])} actions"
        )
        
        return results
    
    def _observe_phase(self, results: Dict):
        """Observation phase"""
        # Update agent state with current metrics
        self.state.update_metrics(list(self.observer.transactions_window))
        
        # Get summary
        summary = self.observer.get_summary()
        results['observation_summary'] = summary
        
        self.logger.debug(
            f"Observed {summary['total_transactions']} transactions, "
            f"{summary['overall_success_rate']:.2%} success rate"
        )
    
    def _reason_phase(self, results: Dict) -> List:
        """Reasoning phase - detect patterns and generate hypotheses"""
        # Detect patterns
        patterns = self.reasoner.analyze(self.observer)
        
        # Store in memory
        for pattern in patterns:
            self.memory.add_pattern(pattern)
        
        # Generate hypotheses for each pattern
        for pattern in patterns:
            hypotheses = self.reasoner.generate_hypotheses(pattern)
            
            results['patterns_detected'].append({
                'pattern_id': pattern.pattern_id,
                'type': pattern.pattern_type,
                'description': pattern.description,
                'severity': pattern.severity,
                'confidence': pattern.confidence,
                'affected': f"{pattern.affected_dimension}:{pattern.affected_value}",
                'hypotheses': [
                    {
                        'root_cause': h.root_cause,
                        'probability': h.probability
                    }
                    for h in hypotheses
                ]
            })
        
        self.logger.info(f"Detected {len(patterns)} patterns")
        
        return patterns
    
    def _decide_and_act_phase(self, patterns: List, results: Dict):
        """Decision and action phase"""
        for pattern in patterns:
            # Skip if severity is too low
            if pattern.severity < 0.3:
                continue
            
            # Generate hypotheses
            hypotheses = self.reasoner.generate_hypotheses(pattern)
            
            # Create decision context
            context = DecisionContext(
                pattern=pattern,
                hypotheses=hypotheses,
                available_actions=[],  # Will be generated by decision maker
                current_state=self.state,
                historical_outcomes=self.learner.action_outcomes,
                constraints={}
            )
            
            # Make decision
            action, reasoning = self.decision_maker.decide(context)
            
            if action is None:
                self.logger.info(f"No action selected for pattern {pattern.pattern_id}")
                continue
            
            # Check if action needs approval
            needs_approval = not (
                self.auto_approve_low_risk and
                action.risk_level.value == 'low'
            )
            
            if needs_approval and action.authorization_level.value != 'automatic':
                self.logger.info(
                    f"Action {action.action_id} requires approval "
                    f"(risk: {action.risk_level.value})"
                )
                # In a real system, would request approval here
                # For demo, we'll auto-approve medium risk
                if action.risk_level.value == 'medium':
                    action.approver = 'auto_approved_for_demo'
                else:
                    continue
            
            # Execute action
            success, message = self.executor.execute(
                action, self.state, self.observer
            )
            
            if success:
                self.memory.add_action(action)
                self.state.actions_successful += 1
                
                results['actions_taken'].append({
                    'action_id': action.action_id,
                    'type': action.action_type.value,
                    'target': action.target,
                    'risk_level': action.risk_level.value,
                    'estimated_impact': action.estimated_impact,
                    'reasoning_summary': reasoning[:200] + '...' if len(reasoning) > 200 else reasoning
                })
    
    def _monitor_phase(self, results: Dict):
        """Monitoring phase - check for rollbacks"""
        rolled_back = self.executor.monitor_and_rollback(
            self.state, self.observer
        )
        
        results['rollbacks_executed'] = rolled_back
        
        if rolled_back:
            self.logger.warning(f"Rolled back {len(rolled_back)} actions")
    
    def _learn_phase(self, results: Dict):
        """Learning phase - update from outcomes"""
        # Record outcomes for recently completed actions
        for action in self.executor.get_active_interventions():
            if action.executed_at:
                duration = datetime.now() - action.executed_at
                
                # After 5 minutes, evaluate the action
                if duration.seconds >= 300 and not action.actual_impact:
                    baseline = self.executor._find_baseline_for_action(action.action_id)
                    if baseline:
                        current_metrics = self.executor._capture_baseline_metrics(self.observer)
                        self.learner.record_outcome(action, baseline, current_metrics)
        
        # Get learning summary
        learning_summary = self.learner.get_learning_summary()
        results['learning_updates'] = {
            'total_outcomes': learning_summary['total_outcomes_recorded'],
            'top_actions': len(learning_summary['top_actions'])
        }
        
        # Periodically update decision weights
        if self.cycle_count % 10 == 0:
            self.learner.update_decision_weights(self.decision_maker)
            self.logger.info("Updated decision weights based on learning")
    
    def get_status(self) -> Dict:
        """Get current agent status"""
        return {
            'is_active': self.state.is_active,
            'cycle_count': self.cycle_count,
            'last_analysis': self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            'state': {
                'success_rate': self.state.overall_success_rate,
                'avg_latency_ms': self.state.average_latency_ms,
                'total_transactions': self.state.total_transactions,
                'active_circuit_breakers': list(self.state.active_circuit_breakers),
                'suppressed_methods': list(self.state.suppressed_methods),
                'actions_taken_last_hour': self.state.actions_taken_last_hour,
                'rollbacks_last_hour': self.state.rollbacks_last_hour
            },
            'performance': {
                'patterns_detected': self.state.patterns_detected,
                'true_positives': self.state.true_positives,
                'false_positives': self.state.false_positives,
                'actions_executed': self.state.actions_executed,
                'actions_successful': self.state.actions_successful
            },
            'observation_summary': self.observer.get_summary(),
            'active_interventions': [
                {
                    'action_id': action.action_id,
                    'type': action.action_type.value,
                    'target': action.target,
                    'executed_at': action.executed_at.isoformat() if action.executed_at else None
                }
                for action in self.executor.get_active_interventions()
            ],
            'learning_summary': self.learner.get_learning_summary()
        }
    
    def run_continuous(self, duration_seconds: Optional[int] = None):
        """
        Run the agent continuously.
        
        Args:
            duration_seconds: How long to run (None = forever)
        """
        start_time = time.time()
        
        self.logger.info("Starting continuous agent operation")
        
        try:
            while True:
                # Check if duration exceeded
                if duration_seconds and (time.time() - start_time) >= duration_seconds:
                    break
                
                # Run one cycle
                results = self.run_cycle()
                
                # Sleep until next analysis
                time.sleep(self.analysis_interval)
        
        except KeyboardInterrupt:
            self.logger.info("Agent stopped by user")
        
        finally:
            self.logger.info(
                f"Agent shutting down after {self.cycle_count} cycles"
            )
