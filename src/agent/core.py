"""
Payment Agent Core
Main orchestrator that coordinates all agent components.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from src.models.state import (
    ActionType,
    AgentMemory,
    AgentState,
    AuthorizationLevel,
    DecisionContext,
    PaymentTransaction,
    RiskLevel,
)
from src.agent.decision_maker import PaymentDecisionMaker
from src.agent.executor import PaymentExecutor
from src.agent.learner import PaymentLearner
from src.agent.observer import PaymentObserver
from src.agent.reasoner import PaymentReasoner
from src.control.plane import ControlPlane
from src.store.journal import NullJournal


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
        auto_approve_low_risk: bool = True,
        min_severity_to_act: float = 0.3,
        outcome_evaluation_seconds: int = 300,
        journal=None
    ):
        """
        Initialize the payment agent.

        Args:
            window_size_minutes: Sliding window size for observations
            analysis_interval_seconds: How often to run analysis
            auto_approve_low_risk: Whether to auto-approve low-risk actions
            min_severity_to_act: Pattern severity below which the agent stays put
            outcome_evaluation_seconds: How long an intervention must run before
                its outcome is scored. Shorten it for demos; in production this
                wants to be long enough for the effect to actually show up.
        """
        # Durable record of what the agent saw, concluded and did. Defaults to
        # a no-op so persistence stays opt-in and nothing has to branch on it.
        self.journal = journal or NullJournal()

        # Core components
        self.observer = PaymentObserver(window_size_minutes=window_size_minutes)
        self.reasoner = PaymentReasoner()
        self.decision_maker = PaymentDecisionMaker()
        self.executor = PaymentExecutor()
        self.learner = PaymentLearner()

        # Agent state. The control plane journals every revision it publishes.
        self.state = AgentState(control_plane=ControlPlane(journal=self.journal))
        self.memory = AgentMemory()
        
        # Configuration
        self.analysis_interval = analysis_interval_seconds
        self.auto_approve_low_risk = auto_approve_low_risk
        self.min_severity_to_act = min_severity_to_act

        # How long an intervention must run before its outcome is scored
        self.outcome_evaluation_seconds = outcome_evaluation_seconds

        # Decision score an action must reach to be worth executing
        self.min_action_score = 0.0
        
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
        self.journal.record_transactions([transaction])

    def process_batch(self, transactions: List[PaymentTransaction]):
        """Process a batch of transactions"""
        self.observer.ingest_batch(transactions)
        self.journal.record_transactions(transactions)
    
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
            'alerts_raised': [],
            'rollbacks_executed': [],
            'expired_interventions': [],
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
        
        self.journal.record_cycle(self.cycle_count, results)

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
        # Feed sequential detectors every outcome since the last cycle, in
        # order. They notice a shifted rate that no single window would flag.
        for key, outcomes in self.observer.drain_outcome_stream().items():
            issuer = key.split(':', 1)[1]
            baseline = self.reasoner.baselines['issuer_success_rates'][issuer]
            self.reasoner.observe_outcomes(key, baseline, outcomes)

        # Detect patterns
        patterns = self.reasoner.analyze(self.observer)

        # Store in memory and account for them
        for pattern in patterns:
            self.memory.add_pattern(pattern)
            self.journal.record_pattern(pattern, cycle=self.cycle_count)
        self.state.patterns_detected += len(patterns)

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
            if pattern.severity < self.min_severity_to_act:
                continue

            # Notify ops about every actionable pattern, independent of whether
            # a mitigation is chosen. Alerting is not an alternative to fixing.
            self._emit_alert(pattern, results)

            hypotheses = self.reasoner.generate_hypotheses(pattern)

            context = DecisionContext(
                pattern=pattern,
                hypotheses=hypotheses,
                available_actions=[],  # Will be generated by decision maker
                current_state=self.state,
                historical_outcomes=self.learner.action_outcomes,
                constraints={}
            )

            ranked = self.decision_maker.rank_actions(context)
            if not ranked:
                self.logger.info(f"No candidate actions for pattern {pattern.pattern_id}")
                continue

            self._execute_best_available(ranked, pattern, results)

    def _execute_best_available(self, ranked: List, pattern, results: Dict):
        """
        Try candidates in score order until one is actually executed.

        A single refusal (rate limit, duplicate intervention, missing approval)
        must not leave the pattern unaddressed when a viable second choice
        exists.
        """
        rejections = []

        for action, score, _ in ranked:
            if score < self.min_action_score:
                # Candidates are ranked, so nothing below this clears the bar
                rejections.append(
                    f"{action.action_type.value}: score {score:.2f} below "
                    f"minimum {self.min_action_score:.2f}"
                )
                break

            if action.action_type == ActionType.NO_ACTION:
                # The baseline out-scored every intervention: standing pat is
                # the decision. Stop here rather than reaching past it.
                self.logger.info(
                    f"Holding for pattern {pattern.pattern_id}: "
                    f"no intervention beat no-action (score {score:.2f})"
                )
                return

            allowed, reason = self._check_approval(action)
            if not allowed:
                rejections.append(f"{action.action_type.value}: {reason}")
                continue

            success, message = self.executor.execute(
                action, self.state, self.observer
            )

            if not success:
                rejections.append(f"{action.action_type.value}: {message}")
                continue

            self.memory.add_action(action)
            self.journal.record_action(action, cycle=self.cycle_count, score=score)

            results['actions_taken'].append({
                'action_id': action.action_id,
                'type': action.action_type.value,
                'target': action.target,
                'risk_level': action.risk_level.value,
                'score': round(score, 3),
                'estimated_impact': action.estimated_impact,
                'reasoning': action.reasoning,
                'rejected_alternatives': rejections,
            })
            return

        if rejections:
            self.logger.info(
                f"No action executed for pattern {pattern.pattern_id}; "
                f"all candidates refused: {'; '.join(rejections)}"
            )

    def _check_approval(self, action) -> tuple:
        """
        Decide whether the agent may execute this action unattended.

        Returns:
            Tuple of (allowed, reason)
        """
        if action.authorization_level == AuthorizationLevel.AUTOMATIC:
            return True, "automatic"

        if action.authorization_level == AuthorizationLevel.SEMI_AUTOMATIC:
            if self.auto_approve_low_risk and action.risk_level == RiskLevel.LOW:
                action.approver = 'agent:auto_low_risk'
                return True, "auto-approved (low risk)"
            return False, "awaiting operator approval (semi-automatic)"

        return False, "requires explicit human approval (manual)"

    def _emit_alert(self, pattern, results: Dict):
        """Send an ops notification for a pattern, alongside any mitigation."""
        alert = self.decision_maker.create_alert_action(pattern)
        success, _ = self.executor.execute(alert, self.state, self.observer)
        if success:
            results['alerts_raised'].append({
                'pattern_id': pattern.pattern_id,
                'pattern_type': pattern.pattern_type,
                'severity': pattern.severity,
                'target': alert.target,
            })

    def _monitor_phase(self, results: Dict):
        """Monitoring phase - revert harmful actions, retire finished ones"""
        expired_before = len(self.executor.expired_actions)

        rolled_back = self.executor.monitor_and_rollback(
            self.state, self.observer
        )

        results['rollbacks_executed'] = rolled_back
        results['expired_interventions'] = self.executor.expired_actions[expired_before:]

        if rolled_back:
            self.logger.warning(f"Rolled back {len(rolled_back)} actions")
    
    def _learn_phase(self, results: Dict):
        """Learning phase - update from outcomes"""
        current_metrics = self.executor.capture_metrics(self.observer)

        # Evaluate interventions that have been running long enough to have had
        # an effect, plus any that finished (expired or rolled back) since the
        # last cycle - those would otherwise never be scored at all.
        candidates = list(self.executor.get_active_interventions())
        candidates += [
            action for action in self.memory.action_history
            if action.completed_at and not action.actual_impact
        ]

        for action in candidates:
            if not action.executed_at or action.actual_impact:
                continue

            settled = action.completed_at is not None
            elapsed = (datetime.now() - action.executed_at).total_seconds()
            if not settled and elapsed < self.outcome_evaluation_seconds:
                continue

            baseline = self.executor.baseline_for_action(action.action_id)
            if baseline:
                self.learner.record_outcome(action, baseline, current_metrics)
                self.journal.record_outcome(action, baseline, current_metrics)
                self.journal.record_action(action, cycle=self.cycle_count)

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
            'control_plane': {
                'revision': self.state.control_plane.revision,
                'policy': self.state.control_plane.current.to_dict(),
            },
            'state': {
                'success_rate': self.state.overall_success_rate,
                'avg_latency_ms': self.state.average_latency_ms,
                'total_transactions': self.state.total_transactions,
                'active_circuit_breakers': sorted(self.state.active_circuit_breakers),
                'suppressed_methods': sorted(self.state.suppressed_methods),
                'actions_taken_last_hour': self.state.actions_taken_last_hour,
                'rollbacks_last_hour': self.state.rollbacks_last_hour
            },
            'performance': {
                'patterns_detected': self.state.patterns_detected,
                'true_positives': self.state.true_positives,
                'false_positives': self.state.false_positives,
                'actions_attempted': self.state.actions_attempted,
                'actions_executed': self.state.actions_executed,
                'alerts_raised': self.state.alerts_raised
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
