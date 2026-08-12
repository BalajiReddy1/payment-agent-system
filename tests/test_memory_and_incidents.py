"""
Incident memory and the two-lane brain.

Memory is where a measured experiment result stops being a fact about the past
and becomes a prior for the next decision. The incident tracker is the boundary
between the deterministic fast lane and the expensive slow lane, and its job is
to make sure the slow lane fires once per real event rather than once per cycle.
"""

from datetime import datetime, timedelta

from src.agent.incidents import IncidentTracker
from src.analysis.memory import IncidentMemory, IncidentRecord
from src.factory import build_agent, build_simulator
from src.models.state import (
    Action,
    ActionType,
    AuthorizationLevel,
    Pattern,
    RiskLevel,
)


def make_pattern(pattern_type='issuer_degradation', target='HDFC_BANK', severity=0.9):
    return Pattern(
        pattern_id='',
        pattern_type=pattern_type,
        description='test',
        severity=severity,
        confidence=0.9,
        affected_dimension='issuer',
        affected_value=target,
        metrics={'degradation': 0.4, 'volume': 100},
        detected_at=datetime.now(),
    )


def make_action(action_type=ActionType.CIRCUIT_BREAKER):
    return Action(
        action_id='a1',
        action_type=action_type,
        target='HDFC_BANK',
        parameters={},
        risk_level=RiskLevel.MEDIUM,
        authorization_level=AuthorizationLevel.SEMI_AUTOMATIC,
        estimated_impact={},
        reasoning='',
        confidence=0.9,
        created_at=datetime.now(),
    )


def measured(lift, significant=True):
    return {
        'success_rate_delta': lift,
        'significant': significant,
        'attribution': 'holdout' if significant else 'before_after',
    }


# ── Memory ───────────────────────────────────────────────────────────────────

def test_similarity_separates_pattern_types():
    memory = IncidentMemory()
    memory.remember_pattern(make_pattern(), make_action(), measured(0.2))

    same = memory.similarity(make_pattern(), memory.incidents[0])
    different = memory.similarity(
        make_pattern(pattern_type='retry_storm', target='overall'),
        memory.incidents[0],
    )

    assert same > 0.9
    # Pattern type gates similarity outright, so an unrelated incident can
    # never contribute advice however well its other features happen to match.
    assert different == 0.0
    assert memory.recall(make_pattern(pattern_type='retry_storm')) == []


def test_recall_returns_most_similar_first():
    memory = IncidentMemory()
    memory.remember_pattern(
        make_pattern(target='SBI'), make_action(), measured(0.1)
    )
    memory.remember_pattern(
        make_pattern(target='HDFC_BANK'), make_action(), measured(0.2)
    )

    recalled = memory.recall(make_pattern(target='HDFC_BANK'))

    assert recalled[0][0].target == 'HDFC_BANK'
    assert recalled[0][1] > recalled[-1][1]


def test_only_measured_outcomes_become_advice():
    """
    An unverified before/after result may be recalled for context but must
    never turn into a recommendation - that is how the agent would learn from
    the outage ending rather than from what it did.
    """
    memory = IncidentMemory()
    for _ in range(3):
        memory.remember_pattern(
            make_pattern(),
            make_action(ActionType.ROUTE_CHANGE),
            measured(0.90, significant=False),
        )

    live = make_pattern()

    assert memory.recall(live), "it should still be recalled"
    assert memory.recommend(live) == {}, "but never recommended"


def test_recommendation_needs_repeated_evidence():
    memory = IncidentMemory()
    memory.remember_pattern(make_pattern(), make_action(), measured(0.2))

    assert memory.recommend(make_pattern()) == {}

    memory.remember_pattern(make_pattern(), make_action(), measured(0.25))
    recommendation = memory.recommend(make_pattern())

    assert 'circuit_breaker' in recommendation
    assert abs(recommendation['circuit_breaker']['expected_lift'] - 0.225) < 1e-6
    assert recommendation['circuit_breaker']['samples'] == 2


def test_memory_is_bounded():
    memory = IncidentMemory(capacity=10)
    for _ in range(50):
        memory.remember_pattern(make_pattern(), make_action(), measured(0.1))
    assert len(memory.incidents) == 10


def test_measured_history_overrides_the_hardcoded_estimate():
    """
    Every action ships with somebody's guess at its impact. Once measured,
    the measurement should win - that is the difference between an agent that
    believes its priors and one that learns.
    """
    from src.agent.decision_maker import PaymentDecisionMaker
    from src.models.state import AgentState, DecisionContext

    decision_maker = PaymentDecisionMaker()
    action = make_action()
    action.estimated_impact = {'success_rate_delta': 0.15}

    context = DecisionContext(
        pattern=make_pattern(),
        hypotheses=[],
        available_actions=[],
        current_state=AgentState(),
        historical_outcomes={},
        constraints={},
        recommendations={
            'circuit_breaker': {'expected_lift': 0.45, 'samples': 5, 'similarity': 0.9}
        },
    )

    impact = decision_maker._effective_impact(action, context)

    assert abs(impact['success_rate_delta'] - 0.45) < 1e-9
    assert impact['measured_samples'] == 5


def test_thin_evidence_only_partly_shifts_the_estimate():
    from src.agent.decision_maker import PaymentDecisionMaker
    from src.models.state import AgentState, DecisionContext

    decision_maker = PaymentDecisionMaker()
    action = make_action()
    action.estimated_impact = {'success_rate_delta': 0.10}

    context = DecisionContext(
        pattern=make_pattern(),
        hypotheses=[],
        available_actions=[],
        current_state=AgentState(),
        historical_outcomes={},
        constraints={},
        recommendations={
            'circuit_breaker': {'expected_lift': 0.50, 'samples': 2, 'similarity': 0.9}
        },
    )

    impact = decision_maker._effective_impact(action, context)

    # Between the prior and the measurement, nearer neither extreme
    assert 0.10 < impact['success_rate_delta'] < 0.50


# ── Incident tracking / two-lane brain ───────────────────────────────────────

def test_repeated_detections_form_one_incident():
    tracker = IncidentTracker()

    first, is_new = tracker.observe(make_pattern())
    assert is_new

    for _ in range(9):
        incident, is_new = tracker.observe(make_pattern())
        assert not is_new
        assert incident is first

    assert first.detections == 10
    assert len(tracker.active()) == 1


def test_different_targets_are_different_incidents():
    tracker = IncidentTracker()
    tracker.observe(make_pattern(target='HDFC_BANK'))
    tracker.observe(make_pattern(target='SBI'))
    assert len(tracker.active()) == 2


def test_incident_closes_after_detections_stop():
    tracker = IncidentTracker(close_after_seconds=60)
    incident, _ = tracker.observe(make_pattern())

    assert tracker.close_stale() == []

    incident.last_seen_at = datetime.now() - timedelta(seconds=120)
    closed = tracker.close_stale()

    assert closed == [incident]
    assert not incident.active
    assert tracker.active() == []


def test_a_gap_does_not_split_an_ongoing_incident():
    """
    Detection is statistical, so an ongoing outage will occasionally miss a
    cycle. Closing immediately would produce flapping incidents.
    """
    tracker = IncidentTracker(close_after_seconds=120)
    incident, _ = tracker.observe(make_pattern())

    incident.last_seen_at = datetime.now() - timedelta(seconds=30)
    assert tracker.close_stale() == []

    _same, is_new = tracker.observe(make_pattern())
    assert not is_new


def test_peak_severity_is_retained():
    tracker = IncidentTracker()
    tracker.observe(make_pattern(severity=0.4))
    tracker.observe(make_pattern(severity=0.95))
    incident, _ = tracker.observe(make_pattern(severity=0.5))

    assert incident.peak_severity == 0.95
    assert incident.latest_severity == 0.5


def test_slow_lane_runs_once_per_incident_not_once_per_cycle():
    """The whole point of splitting the brain in two."""
    calls = []

    agent = build_agent(
        window_size_minutes=5,
        outcome_evaluation_seconds=0,
        advisor=lambda ctx: calls.append(ctx['incident_id']) or 'noted',
    )
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation(
        'KOTAK_BANK', severity=0.85, duration_seconds=7200
    )

    for _ in range(10):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    assert agent.state.patterns_detected >= 5, "the pattern should recur"
    assert len(calls) < agent.state.patterns_detected
    assert len(set(calls)) == len(calls), "no incident consulted twice"


def test_advisor_receives_memory_as_context():
    captured = {}

    def advisor(context):
        captured.update(context)
        return 'ok'

    agent = build_agent(window_size_minutes=5, advisor=advisor)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    for _ in range(3):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    assert 'evidence' in captured
    assert 'hypotheses' in captured
    assert 'similar_incidents' in captured
    assert 'what_worked_before' in captured


def test_a_failing_advisor_does_not_stop_the_agent():
    """
    The deterministic lane has already decided what to do. A model outage
    should degrade the narrative, not the mitigation.
    """
    def broken_advisor(_context):
        raise RuntimeError("model unavailable")

    agent = build_agent(window_size_minutes=5, advisor=broken_advisor)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        result = agent.run_cycle()
        assert 'error' not in result

    assert agent.state.actions_executed > 0


def test_agent_runs_with_no_advisor_at_all():
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)

    agent.process_batch(simulator.generate_stream(count=200, start_time=datetime.now()))
    result = agent.run_cycle()

    assert 'error' not in result
    assert agent.advisor is None
