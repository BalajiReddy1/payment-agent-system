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
from src.agent.incidents import IncidentTracker
from src.agent.reasoner import PaymentReasoner
from src.analysis.experiment import ExperimentRegistry
from src.analysis.memory import IncidentMemory
from src.control.plane import ControlPlane, ControlPlaneRevision
from src.safety.approvals import ApprovalQueue, needs_human
from src.store.journal import NullJournal


def _advisor_failure(exc: Exception) -> str:
    """
    A short, operator-readable reason an assessment is missing.

    Provider errors arrive as several hundred characters of JSON. What an
    operator needs is which of three things happened: the quota is gone, the
    model is busy, or something else went wrong.
    """
    code = getattr(exc, "code", None)
    if code == 429:
        return "Quota exhausted for the configured models."
    if code in (500, 502, 503, 504):
        return "The model was busy and did not answer in time."
    if code == 400:
        return "The advisor was rejected by the provider. Check the API key."
    return "The advisor could not be reached."


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
        holdout_fraction: float = 0.10,
        journal=None,
        advisor=None
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
            holdout_fraction: Share of affected traffic deliberately left
                untreated so an intervention can be measured against a
                concurrent control. Set to 0 to disable measurement - the
                agent will still act, it just will not know whether it helped.
            advisor: Optional callable(incident_context) -> str, the slow lane.
                Invoked once when an incident opens, never per cycle. Omitted
                by default so the agent runs - and tests run - without any
                model call at all.
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

        # Holdout experiments: how the agent finds out whether its
        # interventions actually work, rather than assuming they did.
        self.experiments = ExperimentRegistry(default_holdout=holdout_fraction)

        # What the agent remembers about incidents like this one, and what
        # measurably worked on them. This is where an experiment result stops
        # being a fact about the past and becomes a prior for the next decision.
        self.memory_of_incidents = IncidentMemory()

        # Where an action goes when the agent has decided it is right but is
        # not allowed to do it alone. Refusing and moving on - the previous
        # behaviour - meant the agent concluded a breaker was needed and then
        # told nobody.
        self.approvals = ApprovalQueue()

        # Two-lane brain. The fast lane (detection above) runs every cycle in
        # microseconds; the advisor is the slow lane and fires once per
        # incident. Calling a model per cycle would be untenable on latency
        # and cost, and would re-opine every few seconds on an unchanged
        # situation.
        self.incident_tracker = IncidentTracker()
        self.advisor = advisor

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

        # Observations required in each experiment arm before an intervention's
        # measured lift is trusted enough to record
        self.min_experiment_observations = 30
        
        # Logging
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Which pattern prompted which action, so an outcome can be filed
        # against the incident that caused it
        self._pattern_for_action: Dict[str, object] = {}

        # Metrics
        self.cycle_count = 0
        self.last_analysis_time = None

        # Interventions inherited from a previous run, kept so an operator can
        # see what this agent adopted rather than decided.
        self.recovered: List[Dict] = []

    def recover(self) -> List[Dict]:
        """
        Adopt whatever the previous run left in force.

        A restarted agent's control plane starts empty, but the policy the
        previous one published is still being obeyed by whatever routes
        payments. Without this the new agent cannot see those interventions, so
        it never expires or rolls them back: a circuit breaker outlives the
        process that opened it and stays shut on an issuer that recovered
        hours ago.

        Called by the factory when a journal is supplied. Safe to call when
        there is nothing to recover, and safe to call twice - adopting an
        identical policy publishes no revision.

        Returns:
            The open interventions found, as dicts, for logging and display.
        """
        recorded = self.journal.last_revision()
        if recorded:
            previous = ControlPlaneRevision.from_dict(recorded)
            if not previous.is_empty() or previous.holdouts:
                self.state.control_plane.adopt(previous)
                self.logger.warning(
                    "Recovered policy from a previous run: %s. These are in "
                    "force now and this agent is responsible for ending them.",
                    ', '.join(sorted(previous.circuit_breakers
                                     | previous.suppressed_methods
                                     | set(previous.routing_overrides))) or 'holdouts only',
                )

        self.recovered = [dict(row) for row in self.journal.open_interventions()]
        if self.recovered:
            self.logger.warning(
                "%d intervention(s) executed but never completed before the "
                "last shutdown", len(self.recovered)
            )
        return self.recovered


    def process_transaction(self, transaction: PaymentTransaction):
        """
        Process a single incoming transaction.
        
        This is the entry point for streaming payment data.
        """
        self.observer.ingest_transaction(transaction)
        self.experiments.record(transaction)
        self.journal.record_transactions([transaction])

    def process_batch(self, transactions: List[PaymentTransaction]):
        """Process a batch of transactions"""
        self.observer.ingest_batch(transactions)
        self.experiments.record_batch(transactions)
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
            'incidents_opened': [],
            'incidents_closed': [],
            'approvals_lapsed': [],
            'learning_updates': {}
        }
        
        # Per-phase timings, measured where the phases actually run rather
        # than reconstructed by a benchmark calling the components separately.
        # A cycle does work between the phases - journalling, incident
        # tracking, experiment bookkeeping - that a reconstruction silently
        # omits, so the parts only add up to the whole if they are timed here.
        phases: Dict[str, float] = {}

        def timed(name, function, *args):
            start = time.perf_counter()
            try:
                return function(*args)
            finally:
                phases[name] = (time.perf_counter() - start) * 1000.0

        try:
            # 1. OBSERVE: Update state with current observations
            timed('observe', self._observe_phase, results)

            # 2. REASON: Detect patterns and form hypotheses
            patterns = timed('reason', self._reason_phase, results)

            # 3. DECIDE & ACT: Make decisions and execute actions
            if patterns:
                timed('decide_act', self._decide_and_act_phase, patterns, results)
            else:
                phases['decide_act'] = 0.0

            # 4. MONITOR: Check for rollbacks
            timed('monitor', self._monitor_phase, results)

            # 5. LEARN: Update from outcomes
            timed('learn', self._learn_phase, results)

            # Update baselines
            timed('baselines', self.reasoner.update_baselines, self.observer)

        except Exception as e:
            self.logger.error(f"Error in agent cycle: {e}", exc_info=True)
            results['error'] = str(e)
        
        cycle_duration = time.time() - cycle_start
        results['cycle_duration_seconds'] = cycle_duration
        results['phase_ms'] = phases
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

        # Collapse repeated detections into incidents, and consult the slow
        # lane exactly once per newly opened incident.
        for pattern in patterns:
            incident, is_new = self.incident_tracker.observe(pattern)
            if is_new:
                results['incidents_opened'].append(incident.incident_id)
                self._consult_advisor(incident, pattern)

        for incident in self.incident_tracker.close_stale():
            results['incidents_closed'].append(incident.incident_id)
            self.logger.info(
                "Incident %s on %s closed after %.0fs and %d detections",
                incident.incident_id, incident.target,
                incident.duration_seconds, incident.detections
            )

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
                constraints={},
                recommendations=self.memory_of_incidents.recommend(pattern),
                recalled_incidents=self.memory_of_incidents.explain(pattern),
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
            self._pattern_for_action[action.action_id] = pattern
            incident = self.incident_tracker.incidents.get(
                IncidentTracker.key_for(pattern)
            )
            if incident is not None:
                incident.actions_taken.append(action.action_type.value)
            self._start_experiment(action)
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
        Decide whether the agent may execute this action unattended, and if
        not, put it somewhere a human will see it.

        Returns:
            Tuple of (allowed, reason)
        """
        if not needs_human(action, self.auto_approve_low_risk):
            if (
                action.authorization_level != AuthorizationLevel.AUTOMATIC
                and not action.approver
            ):
                action.approver = 'agent:auto_low_risk'
                return True, "auto-approved (low risk)"
            return True, "automatic"

        request = self.approvals.submit(
            action,
            requested_by='agent',
            reason=f"{action.action_type.value} on {action.target}",
        )
        return False, (
            f"queued for {action.authorization_level.value} approval "
            f"as {request.request_id}"
        )

    def _stop_experiment(self, action_id: str):
        """End an intervention's experiment and release its holdout."""
        experiment = self.experiments.stop(action_id)
        if experiment is None:
            return

        self.state.control_plane.clear_holdout(
            experiment.target,
            author='agent',
            reason=f'{experiment.experiment_id} ended',
            action_id=action_id,
        )

        result = experiment.result()
        if result:
            self.logger.info(
                "%s on %s: %s",
                experiment.experiment_id, experiment.target, result.describe()
            )

    def _start_experiment(self, action):
        """
        Begin measuring an intervention against a concurrent holdout.

        Only for interventions with a definable affected population - there is
        no meaningful control group for a global timeout change.
        """
        if self.experiments.default_holdout <= 0:
            return
        if action.action_type not in (
            ActionType.CIRCUIT_BREAKER,
            ActionType.ROUTE_CHANGE,
            ActionType.METHOD_SUPPRESS,
        ):
            # Only interventions with a definable affected population can be
            # measured; there is no control group for a global timeout change.
            return

        target = (
            action.parameters.get('issuer')
            or action.parameters.get('payment_method')
            or action.target
        )

        experiment = self.experiments.start(
            action_id=action.action_id,
            action_type=action.action_type.value,
            target=target,
        )
        self.state.control_plane.set_holdout(
            target,
            experiment.holdout_fraction,
            author='agent',
            reason=f'holdout for {experiment.experiment_id}',
            action_id=action.action_id,
        )
        self.logger.info(
            "Started %s: %.0f%% of %s traffic held out as control",
            experiment.experiment_id, experiment.holdout_fraction * 100, target
        )

    def approve(self, request_id: str, approver: str, note=None) -> tuple:
        """
        Grant a queued approval and execute the action.

        Separate from proposing on purpose: the agent fills this queue and
        never drains it.
        """
        ok, message, action = self.approvals.approve(request_id, approver, note)
        if not ok:
            return False, message

        success, detail = self.executor.execute(action, self.state, self.observer)
        if success:
            self.memory.add_action(action)
            self._start_experiment(action)
            self.journal.record_action(action, cycle=self.cycle_count)
        return success, f"{message}; {detail}"

    def deny(self, request_id: str, approver: str, note=None) -> tuple:
        """Refuse a queued approval."""
        return self.approvals.deny(request_id, approver, note)

    def _consult_advisor(self, incident, pattern):
        """
        Ask the slow lane for an opinion on a newly opened incident.

        Failure here must never stop the agent: the deterministic lane has
        already decided what to do, and the advisor's contribution is
        explanation and context, not authority. A model outage should degrade
        the narrative, not the mitigation.
        """
        if self.advisor is None:
            return

        context = {
            'incident_id': incident.incident_id,
            'pattern_type': pattern.pattern_type,
            'target': pattern.affected_value,
            'severity': pattern.severity,
            'confidence': pattern.confidence,
            'evidence': list(pattern.evidence),
            'hypotheses': [
                {'root_cause': h.root_cause, 'probability': h.probability}
                for h in self.reasoner.generate_hypotheses(pattern)
            ],
            'similar_incidents': self.memory_of_incidents.explain(pattern),
            'what_worked_before': self.memory_of_incidents.recommend(pattern),
        }

        try:
            incident.advice = self.advisor(context)
            incident.advice_unavailable = None
        except Exception as exc:
            # Recorded, not just logged: an operator looking at an incident with
            # no assessment should be told the model could not be reached rather
            # than left to assume the lane had nothing to say.
            incident.advice_unavailable = _advisor_failure(exc)
            self.logger.warning(
                "Advisor failed for %s (continuing without it): %s",
                incident.incident_id, exc
            )

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

        # An approval nobody answered lapses rather than being granted by
        # default; a tier that eventually approves itself is a delay, not a
        # control.
        for request in self.approvals.expire_stale():
            results['approvals_lapsed'].append(request.request_id)

        # An intervention that has ended stops accruing experiment data, and
        # its holdout is released so traffic returns to normal routing.
        for action_id in rolled_back + results['expired_interventions']:
            self._stop_experiment(action_id)

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

            # A concurrent control group, where one exists, is the honest
            # measure. Before/after is confounded by everything else that
            # changed meanwhile - above all by the incident resolving itself.
            experiment = self.experiments.for_action(action.action_id)

            if experiment is not None:
                # Wait for the experiment to gather enough traffic in both
                # arms. Scoring the instant the action executes - before any
                # transaction has been through it - would record a
                # measurement of nothing, and outcomes are recorded once.
                ready = experiment.has_sufficient_data(self.min_experiment_observations)
                if not ready and not settled:
                    continue
                measured = experiment.result() if ready else None
            else:
                if not settled and elapsed < self.outcome_evaluation_seconds:
                    continue
                measured = None

            baseline = self.executor.baseline_for_action(action.action_id)
            if not baseline:
                continue

            self.learner.record_outcome(
                action, baseline, current_metrics, measured_lift=measured
            )

            # File the result under the pattern that prompted it, so the next
            # comparable incident starts from evidence rather than from scratch.
            pattern = self._pattern_for_action.get(action.action_id)
            if pattern is not None:
                self.memory_of_incidents.remember_pattern(
                    pattern, action, action.actual_impact
                )
            self.journal.record_outcome(action, baseline, current_metrics)
            self.journal.record_action(action, cycle=self.cycle_count)

        # Get learning summary
        learning_summary = self.learner.get_learning_summary()
        results['learning_updates'] = {
            'total_outcomes': learning_summary['total_outcomes_recorded'],
            'top_actions': len(learning_summary['top_actions'])
        }
        results['experiments'] = [
            e.summary() for e in self.experiments.experiments.values()
        ]
        
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
            'learning_summary': self.learner.get_learning_summary(),
            'experiments': [e.summary() for e in self.experiments.experiments.values()],
            'incidents': [i.summary() for i in self.incident_tracker.all()[:20]],
            'approvals': self.approvals.summaries()
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
