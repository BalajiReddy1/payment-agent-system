"""
Whole-loop accounting.

The counters the dashboard and API report have to mean what they say: patterns
must actually be counted, alerts must not be filed as interventions, and the
learn phase must receive outcomes rather than sitting permanently empty.
"""

import random
from datetime import datetime

from src.agent.core import PaymentAgent
from src.simulation.payment_simulator import PaymentSimulator


def run_agent(cycles=5, outcome_evaluation_seconds=0, severity=0.85, count=250,
              seed=None):
    """
    Drive the loop against a degrading issuer.

    `seed` fixes the simulator's draw. Tests asserting on counts that come out
    small need it: the traffic is random and a test whose margin is one
    observation is a coin flip dressed as an assertion, failing a few percent
    of runs depending on what consumed the global RNG before it.
    """
    if seed is not None:
        random.seed(seed)

    agent = PaymentAgent(
        window_size_minutes=5,
        outcome_evaluation_seconds=outcome_evaluation_seconds,
    )
    simulator = PaymentSimulator(base_success_rate=0.96, control_plane=agent.state)
    simulator.inject_issuer_degradation('HDFC_BANK', severity=severity, duration_seconds=3600)

    results = []
    for _ in range(cycles):
        agent.process_batch(simulator.generate_stream(count=count, start_time=datetime.now()))
        results.append(agent.run_cycle())
        # An operator grants whatever the agent asked for, so the tests cover
        # the full path rather than only what the agent may do unattended.
        for request in agent.approvals.pending():
            agent.approve(request.request_id, 'ops@example.com')
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
    """
    Enough traffic for both experiment arms to clear the minimum sample size.

    Seeded deliberately. Unseeded this produced exactly one outcome, so
    "> 0" had a margin of one observation and failed about 8% of runs
    depending on what had consumed the global RNG first - a flake that would
    read as a real regression to whoever next changed the learn phase.
    """
    agent, _results = run_agent(
        cycles=12, count=500, outcome_evaluation_seconds=0, seed=20260812
    )

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
    When the top candidate is refused - already active, or queued for an
    operator - the agent should reach past it to the next viable option rather
    than doing nothing.
    """
    agent, results = run_agent(cycles=6)

    # The action history covers both routes: executed unattended, and executed
    # after an operator granted the queued request.
    executed = [a.action_type.value for a in agent.memory.action_history]
    assert len(executed) >= 2
    assert len(set(executed)) >= 2

    # The agent asked for what it could not do alone rather than staying silent
    assert agent.approvals.requests, "the agent should have requested approval"


# ── The REASON phase must not be abortable by one detector ───────────────────

def test_a_marginal_retry_storm_does_not_abort_pattern_detection():
    """
    Found by running the demo the docs tell a reader to run.

    The retry-storm detector computed its effect size as
    `retry_percentage - 0.2` while the shipped config triggers at 0.15, so any
    storm between 15% and 20% produced a negative effect size, reached
    math.sqrt, and raised ValueError. run_cycle caught it - which is worse than
    it sounds: the whole REASON phase aborted, so a simultaneous issuer
    degradation went undetected while a domain error nobody reads went to the
    log.
    """
    from src.agent.reasoner import PaymentReasoner
    from src.factory import build_agent, build_simulator

    agent = build_agent(window_size_minutes=60, advisor=None)
    agent.reasoner.thresholds['retry_storm'] = 0.15
    simulator = build_simulator(control_plane=agent.state)

    # 17% retries: past the trigger, inside the window that used to crash
    batch = simulator.generate_stream(count=200, start_time=datetime.now())
    for i, txn in enumerate(batch):
        txn.is_retry = i < 34
    agent.process_batch(batch)

    results = agent.run_cycle()

    assert 'error' not in results, results.get('error')

    # Whether it is *reported* is a separate question, and the right answer is
    # no: two points past the threshold is a weak effect, so confidence lands
    # under the reporting floor. Triggering evaluation and clearing the bar to
    # be shown are deliberately different bars.
    assert not any(p['type'] == 'retry_storm' for p in results['patterns_detected'])


def test_a_clear_retry_storm_is_still_detected():
    """The clamp must not have muted the detector it was protecting."""
    from src.factory import build_agent, build_simulator

    agent = build_agent(window_size_minutes=60, advisor=None)
    agent.reasoner.thresholds['retry_storm'] = 0.15
    simulator = build_simulator(control_plane=agent.state)

    batch = simulator.generate_stream(count=200, start_time=datetime.now())
    for i, txn in enumerate(batch):
        txn.is_retry = i < 90  # 45%
    agent.process_batch(batch)

    results = agent.run_cycle()

    assert 'error' not in results
    assert any(p['type'] == 'retry_storm' for p in results['patterns_detected'])


def test_confidence_survives_an_effect_pointing_the_wrong_way():
    """An effect in the wrong direction means no confidence, not a crash."""
    from src.agent.reasoner import PaymentReasoner

    reasoner = PaymentReasoner()

    assert reasoner._calculate_confidence(500, -0.5) == 0.0
    assert reasoner._calculate_confidence(500, 0.0) == 0.0
    assert 0.0 < reasoner._calculate_confidence(500, 0.15) <= 1.0
    assert reasoner._calculate_confidence(500, 10.0) <= 1.0


def test_every_detector_still_runs_when_one_finds_nothing():
    """
    The property the crash violated: detectors are independent, and one
    declining to fire - or failing - must not cost the others their cycle.
    """
    from src.factory import build_agent, build_simulator

    agent = build_agent(window_size_minutes=60, advisor=None)
    agent.reasoner.thresholds['retry_storm'] = 0.15
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    batch = simulator.generate_stream(count=400, start_time=datetime.now())
    for i, txn in enumerate(batch):
        txn.is_retry = i < 68  # 17%, the crashing band
    agent.process_batch(batch)

    results = agent.run_cycle()
    kinds = {p['type'] for p in results['patterns_detected']}

    assert 'error' not in results
    assert 'issuer_degradation' in kinds, (
        f"the degradation must be found alongside the retry storm; saw {kinds}"
    )
