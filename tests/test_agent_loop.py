"""
Whole-loop accounting.

The counters the dashboard and API report have to mean what they say: patterns
must actually be counted, alerts must not be filed as interventions, and the
learn phase must receive outcomes rather than sitting permanently empty.
"""

from datetime import datetime

from src.agent.core import PaymentAgent
from src.simulation.payment_simulator import PaymentSimulator


def run_agent(cycles=5, outcome_evaluation_seconds=0, severity=0.85):
    agent = PaymentAgent(
        window_size_minutes=5,
        outcome_evaluation_seconds=outcome_evaluation_seconds,
    )
    simulator = PaymentSimulator(base_success_rate=0.96, control_plane=agent.state)
    simulator.inject_issuer_degradation('HDFC_BANK', severity=severity, duration_seconds=3600)

    results = []
    for _ in range(cycles):
        agent.process_batch(simulator.generate_stream(count=250, start_time=datetime.now()))
        results.append(agent.run_cycle())
    return agent, results


def test_patterns_detected_counter_is_maintained():
    """It used to stay at zero forever while patterns were being found."""
    agent, results = run_agent()

    reported = sum(len(r['patterns_detected']) for r in results)
    assert reported > 0
    assert agent.state.patterns_detected == reported


def test_alerts_do_not_inflate_the_action_count():
    agent, results = run_agent()

    assert agent.state.alerts_raised > 0
    assert agent.state.actions_executed <= agent.state.actions_attempted
    # Alerts vastly outnumber interventions; if they were being counted as
    # actions the two would be indistinguishable.
    assert agent.state.actions_executed < agent.state.alerts_raised


def test_alerts_are_raised_for_severe_patterns():
    _agent, results = run_agent()
    assert any(r['alerts_raised'] for r in results)


def test_learn_phase_records_outcomes():
    agent, _results = run_agent(outcome_evaluation_seconds=0)

    summary = agent.get_status()['learning_summary']
    assert summary['total_outcomes_recorded'] > 0


def test_no_cycle_raises():
    _agent, results = run_agent()
    for result in results:
        assert 'error' not in result, result.get('error')


def test_status_payload_has_the_fields_the_api_reads():
    agent, _ = run_agent(cycles=1)
    status = agent.get_status()

    # These exact lookups are what api/main.py performs
    assert isinstance(status['is_active'], bool)
    assert isinstance(status['cycle_count'], int)
    status['state']['success_rate']
    status['state']['avg_latency_ms']
    status['state']['total_transactions']
    status['performance']['actions_executed']
    status['performance']['patterns_detected']


def test_refused_action_falls_through_to_next_candidate():
    """
    With a circuit breaker already active on the target, the agent should reach
    past it to the next viable candidate rather than doing nothing.
    """
    agent, results = run_agent(cycles=6)

    executed = [a['type'] for r in results for a in r['actions_taken']]
    assert len(executed) >= 2
    # More than one distinct intervention type was used across the incident
    assert len(set(executed)) >= 2
