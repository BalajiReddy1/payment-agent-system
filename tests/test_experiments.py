"""
Holdout experiments.

The agent used to measure an intervention by comparing the success rate before
it with the success rate after. That cannot distinguish "the circuit breaker
worked" from "the outage ended by itself", and an agent that learns from it
learns to repeat whatever it happened to be doing when things improved.

These tests hold the replacement in place: a concurrent control group, an
honest confidence interval, and a learner that refuses to learn from anything
weaker.
"""

from datetime import datetime

import pytest

from src.analysis.experiment import CONTROL, TREATMENT, ExperimentRegistry
from src.factory import build_system
from src.models.state import AgentState, PaymentStatus
from src.simulation.payment_simulator import PaymentSimulator

from conftest import make_transaction


# ── Assignment ───────────────────────────────────────────────────────────────

def test_assignment_is_deterministic():
    """
    A replayed transaction must land in the arm it originally did, or replay
    based evaluation silently compares different populations.
    """
    for i in range(200):
        txn_id = f"txn-{i}"
        first = ExperimentRegistry.assign(txn_id, 0.1)
        assert ExperimentRegistry.assign(txn_id, 0.1) == first


def test_assignment_respects_the_holdout_fraction():
    arms = [ExperimentRegistry.assign(f"txn-{i}", 0.20) for i in range(4000)]
    control_share = arms.count(CONTROL) / len(arms)
    assert 0.17 < control_share < 0.23


def test_zero_holdout_treats_everything():
    assert all(
        ExperimentRegistry.assign(f"txn-{i}", 0.0) == TREATMENT
        for i in range(100)
    )


def test_registry_rejects_an_absurd_holdout():
    with pytest.raises(ValueError):
        ExperimentRegistry(default_holdout=0.6)


# ── Registry lifecycle ───────────────────────────────────────────────────────

def test_start_and_stop_an_experiment():
    registry = ExperimentRegistry(default_holdout=0.1)
    experiment = registry.start('act-1', 'circuit_breaker', 'HDFC_BANK')

    assert experiment.active
    assert registry.for_target('HDFC_BANK') is experiment
    assert registry.for_action('act-1') is experiment
    assert registry.active() == [experiment]

    registry.stop('act-1')

    assert not experiment.active
    assert registry.for_target('HDFC_BANK') is None
    assert registry.active() == []
    # Results survive the experiment ending
    assert registry.for_action('act-1') is experiment


def test_holdouts_are_published_for_active_experiments_only():
    registry = ExperimentRegistry(default_holdout=0.15)
    registry.start('act-1', 'circuit_breaker', 'HDFC_BANK')
    registry.start('act-2', 'method_suppress', 'upi')

    assert registry.holdouts() == {'HDFC_BANK': 0.15, 'upi': 0.15}

    registry.stop('act-1')
    assert registry.holdouts() == {'upi': 0.15}


def test_untagged_transactions_are_ignored():
    registry = ExperimentRegistry()
    registry.start('act-1', 'circuit_breaker', 'HDFC_BANK')

    assert not registry.record(make_transaction())


def test_recording_accumulates_per_arm():
    registry = ExperimentRegistry()
    experiment = registry.start('act-1', 'circuit_breaker', 'HDFC_BANK')

    for _ in range(9):
        txn = make_transaction(status=PaymentStatus.SUCCESS)
        txn.experiment_target, txn.experiment_arm = 'HDFC_BANK', TREATMENT
        assert registry.record(txn)

    txn = make_transaction(status=PaymentStatus.FAILED)
    txn.experiment_target, txn.experiment_arm = 'HDFC_BANK', CONTROL
    registry.record(txn)

    assert experiment.treatment.successes == 9
    assert experiment.control.total == 1
    assert experiment.observations == 10


def test_result_needs_both_arms():
    registry = ExperimentRegistry()
    experiment = registry.start('act-1', 'circuit_breaker', 'HDFC_BANK')

    txn = make_transaction()
    txn.experiment_target, txn.experiment_arm = 'HDFC_BANK', TREATMENT
    registry.record(txn)

    assert experiment.result() is None
    assert experiment.summary()['verdict'] == 'insufficient data'


# ── The simulator honours holdouts ───────────────────────────────────────────

def test_control_traffic_keeps_hitting_the_broken_issuer():
    """
    The holdout is only meaningful if it genuinely bypasses the intervention.
    """
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)
    state.control_plane.trip_breaker('HDFC_BANK', author='test', reason='outage')
    state.control_plane.set_holdout('HDFC_BANK', 0.2, author='test', reason='measure')

    batch = simulator.generate_stream(count=1500, start_time=datetime.now())
    still_on_hdfc = [t for t in batch if t.issuer == 'HDFC_BANK']

    assert still_on_hdfc, "the holdout should leave some traffic on the issuer"
    assert all(t.experiment_arm == CONTROL for t in still_on_hdfc)
    assert all(t.experiment_target == 'HDFC_BANK' for t in still_on_hdfc)


def test_treated_traffic_is_tagged_and_rerouted():
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)
    state.control_plane.trip_breaker('HDFC_BANK', author='test', reason='outage')
    state.control_plane.set_holdout('HDFC_BANK', 0.2, author='test', reason='measure')

    batch = simulator.generate_stream(count=1500, start_time=datetime.now())
    treated = [t for t in batch if t.experiment_arm == TREATMENT]

    assert treated
    assert all(t.issuer != 'HDFC_BANK' for t in treated)
    assert all(t.processor == 'rerouted' for t in treated)


def test_no_holdout_means_no_tagging():
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)
    state.control_plane.trip_breaker('HDFC_BANK', author='test', reason='outage')

    batch = simulator.generate_stream(count=400, start_time=datetime.now())

    assert all(t.experiment_arm is None for t in batch)
    assert not any(t.issuer == 'HDFC_BANK' for t in batch)


# ── End to end ───────────────────────────────────────────────────────────────

def run_incident(cycles=10, holdout=0.10, severity=0.85):
    agent, simulator, _ = build_system(
        window_size_minutes=5,
        outcome_evaluation_seconds=0,
        holdout_fraction=holdout,
    )
    simulator.inject_issuer_degradation(
        'AXIS_BANK', severity=severity, duration_seconds=7200
    )
    for _ in range(cycles):
        agent.process_batch(simulator.generate_stream(count=400, start_time=datetime.now()))
        agent.run_cycle()
        # Stand in for the operator so the measured path is exercised
        for request in agent.approvals.pending():
            agent.approve(request.request_id, 'ops@example.com')
    return agent, simulator


def test_agent_measures_a_significant_lift():
    agent, _simulator = run_incident()

    experiments = [e for e in agent.experiments.experiments.values() if e.observations > 0]
    assert experiments, "an intervention should have started an experiment"

    result = experiments[0].result()
    assert result is not None
    assert result.significant
    assert result.difference > 0.1
    # The interval should exclude zero, which is what makes it a claim
    assert result.lower > 0


def test_holdout_is_published_to_the_control_plane():
    agent, _simulator = run_incident()

    holdout_revisions = [
        r for r in agent.state.control_plane.history()
        if 'holdout' in r.reason
    ]
    assert holdout_revisions


def test_disabling_the_holdout_still_lets_the_agent_act():
    """Measurement is optional; intervening is not."""
    agent, simulator = run_incident(holdout=0.0)

    assert agent.state.actions_executed > 0
    assert simulator.control_count == 0
    assert not agent.experiments.experiments


def test_learner_prefers_holdout_attribution():
    agent, _simulator = run_incident()

    outcomes = [o for outs in agent.learner.action_outcomes.values() for o in outs]
    assert outcomes

    attributions = {o['actual_impact'].get('attribution') for o in outcomes}
    assert 'holdout' in attributions


def test_learner_ignores_unmeasured_outcomes():
    """
    Weights must not move on a before/after delta - it cannot tell the
    intervention working from the incident ending.
    """
    from src.agent.decision_maker import PaymentDecisionMaker
    from src.agent.learner import PaymentLearner

    from conftest import make_action

    learner = PaymentLearner()
    decision_maker = PaymentDecisionMaker()
    before = dict(decision_maker.weights)

    for _ in range(10):
        action = make_action()
        learner.record_outcome(
            action,
            baseline_metrics={'success_rate': 0.60, 'avg_latency': 200},
            actual_metrics={'success_rate': 0.95, 'avg_latency': 180},
            measured_lift=None,
        )

    learner.update_decision_weights(decision_maker)

    assert decision_maker.weights == before


def test_experiment_summary_is_serialisable():
    agent, _simulator = run_incident(cycles=6)

    for summary in (e.summary() for e in agent.experiments.experiments.values()):
        assert 'verdict' in summary
        assert 'lift' in summary
        assert isinstance(summary['significant'], bool)


# ── What a reader is told ────────────────────────────────────────────────────

def fill(experiment, treatment=(0, 0), control=(0, 0)):
    """Record (successes, total) into each arm directly."""
    t_ok, t_n = treatment
    c_ok, c_n = control
    for i in range(t_n):
        experiment.treatment.record(i < t_ok)
    for i in range(c_n):
        experiment.control.record(i < c_ok)
    return experiment


def new_experiment():
    return ExperimentRegistry().start('act-1', 'route_change', 'SBI')


def test_a_thin_control_arm_is_not_announced_as_significant():
    """
    The regression. A live run with three control transactions rendered
    "improved success rate by 94.7% ... significant" on the console - a
    stronger claim than the agent itself would act on, made to the person
    deciding whether to trust it. has_sufficient_data() already governed what
    the learner would believe; it now governs what the console says too.
    """
    experiment = fill(new_experiment(), treatment=(36, 38), control=(0, 3))
    summary = experiment.summary()

    assert not summary['sufficient_data']
    assert not summary['significant']
    assert 'still collecting' in summary['verdict']
    # And the sentence must not assert and retract the same claim
    assert 'significant' not in summary['verdict']
    assert 'too few observations to conclude' in summary['verdict']


def test_the_measurement_is_still_reported_while_it_is_thin():
    """Withholding the number would be its own kind of dishonesty."""
    summary = fill(new_experiment(), treatment=(36, 38), control=(0, 3)).summary()

    assert summary['lift'] is not None
    assert summary['treatment'] == {'successes': 36, 'total': 38}
    assert summary['control'] == {'successes': 0, 'total': 3}


def test_a_well_powered_experiment_is_announced_as_significant():
    experiment = fill(new_experiment(), treatment=(95, 100), control=(60, 100))
    summary = experiment.summary()

    assert summary['sufficient_data']
    assert summary['significant']
    assert 'still collecting' not in summary['verdict']


def test_enough_data_and_no_effect_is_not_significant_either():
    summary = fill(new_experiment(), treatment=(90, 100), control=(89, 100)).summary()

    assert summary['sufficient_data']
    assert not summary['significant']


def test_the_reported_interval_stays_inside_the_possible_range():
    summary = fill(new_experiment(), treatment=(36, 38), control=(0, 3)).summary()

    lower, upper = summary['lift_ci']
    assert -1.0 <= lower <= upper <= 1.0
