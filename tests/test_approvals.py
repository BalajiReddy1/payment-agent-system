"""
Approval queue.

An authorization tier only means something if there is somewhere for the
request to go. The loop used to refuse an action it was not permitted to take
and move on, which meant the agent concluded a circuit breaker was needed and
then told nobody.
"""

from datetime import datetime, timedelta

import pytest

from src.agent.executor import PaymentExecutor
from src.factory import build_agent, build_simulator
from src.models.state import (
    ActionType,
    AgentState,
    AuthorizationLevel,
    RiskLevel,
    required_authorization,
)
from src.safety.approvals import ApprovalQueue, needs_human

from conftest import make_action


def queued_action(action_type=ActionType.CIRCUIT_BREAKER, risk=RiskLevel.MEDIUM):
    return make_action(
        action_type=action_type,
        risk_level=risk,
        authorization_level=required_authorization(action_type),
    )


# ── The regression this exists for ───────────────────────────────────────────

def test_generated_actions_use_the_shared_tier_map():
    """
    The decision maker hardcoded AuthorizationLevel.AUTOMATIC on every action
    it produced - the same bypass that was fixed on the LLM tool path, still
    live on the primary one. A circuit breaker executed unattended while the
    docs and the shared map both said it needed an operator.
    """
    from src.agent.decision_maker import PaymentDecisionMaker
    from src.models.state import DecisionContext, Pattern

    pattern = Pattern(
        pattern_id='', pattern_type='issuer_degradation', description='',
        severity=1.0, confidence=0.95, affected_dimension='issuer',
        affected_value='HDFC_BANK',
        metrics={'degradation': 0.5, 'volume': 200, 'avg_latency': 600},
        detected_at=datetime.now(),
    )
    context = DecisionContext(
        pattern=pattern, hypotheses=[], available_actions=[],
        current_state=AgentState(), historical_outcomes={}, constraints={},
    )

    for action, _score, _ in PaymentDecisionMaker().rank_actions(context):
        assert action.authorization_level == required_authorization(action.action_type), (
            f"{action.action_type.value} declared "
            f"{action.authorization_level.value} but the map says "
            f"{required_authorization(action.action_type).value}"
        )


def test_agent_queues_what_it_may_not_do_alone():
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.85, duration_seconds=3600)

    for _ in range(6):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    pending = agent.approvals.pending()
    assert pending, "a medium-risk breaker should have been queued, not skipped"
    assert any(r.action.action_type == ActionType.CIRCUIT_BREAKER for r in pending)

    # Nothing above the automatic tier ran without a named approver
    for action in agent.memory.action_history:
        if action.authorization_level != AuthorizationLevel.AUTOMATIC:
            assert action.approver, f"{action.action_type.value} ran unapproved"


def test_agent_still_mitigates_with_what_it_may_do():
    """Asking for permission must not mean standing still."""
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.85, duration_seconds=3600)

    for _ in range(6):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    assert agent.state.actions_executed > 0
    assert not agent.state.control_plane.current.is_empty()


# ── Queue behaviour ──────────────────────────────────────────────────────────

def test_needs_human_matches_the_documented_model():
    assert not needs_human(queued_action(ActionType.ADJUST_RETRY, RiskLevel.LOW))
    assert needs_human(queued_action(ActionType.CIRCUIT_BREAKER, RiskLevel.MEDIUM))
    assert needs_human(queued_action(ActionType.METHOD_SUPPRESS, RiskLevel.HIGH))

    # Low-risk semi-automatic is the documented auto-approval case
    assert not needs_human(queued_action(ActionType.ROUTE_CHANGE, RiskLevel.LOW))
    assert needs_human(
        queued_action(ActionType.ROUTE_CHANGE, RiskLevel.LOW),
        auto_approve_low_risk=False,
    )


def test_an_already_approved_action_does_not_need_asking_again():
    action = queued_action()
    action.approver = 'ops@example.com'
    assert not needs_human(action)


def test_submit_and_approve():
    queue = ApprovalQueue()
    request = queue.submit(queued_action(), reason='issuer down')

    assert request.pending
    assert queue.pending() == [request]

    ok, message, action = queue.approve(request.request_id, 'ops@example.com')

    assert ok
    assert action.approver == 'ops@example.com'
    assert not queue.pending()
    assert 'ops@example.com' in message


def test_denial_is_recorded():
    queue = ApprovalQueue()
    request = queue.submit(queued_action())

    ok, _ = queue.deny(request.request_id, 'ops@example.com', note='too risky')

    assert ok
    assert request.status == 'denied'
    assert request.note == 'too risky'
    assert not queue.pending()


def test_a_decision_cannot_be_made_twice():
    queue = ApprovalQueue()
    request = queue.submit(queued_action())
    queue.approve(request.request_id, 'first@example.com')

    ok, message, action = queue.approve(request.request_id, 'second@example.com')

    assert not ok
    assert action is None
    assert 'already' in message


def test_approval_requires_a_named_approver():
    queue = ApprovalQueue()
    request = queue.submit(queued_action())

    ok, _message, _action = queue.approve(request.request_id, '  ')

    assert not ok
    assert request.pending, "the request stays queued rather than vanishing"


def test_repeat_proposals_do_not_pile_up():
    """
    The agent re-proposes every cycle while an incident continues; an operator
    should see one decision, not forty copies of it.
    """
    queue = ApprovalQueue()
    first = queue.submit(queued_action())
    for _ in range(20):
        queue.submit(queued_action())

    assert len(queue.pending()) == 1
    assert queue.pending()[0] is first


def test_unanswered_requests_lapse_rather_than_being_granted():
    """A tier that eventually approves itself is a delay, not a control."""
    queue = ApprovalQueue(ttl_seconds=60)
    request = queue.submit(queued_action())

    assert queue.expire_stale() == []

    request.expires_at = datetime.now() - timedelta(seconds=1)
    lapsed = queue.expire_stale()

    assert lapsed == [request]
    assert request.status == 'lapsed'
    assert not queue.pending()


def test_lapsed_request_cannot_then_be_approved():
    queue = ApprovalQueue(ttl_seconds=60)
    request = queue.submit(queued_action())
    request.expires_at = datetime.now() - timedelta(seconds=1)
    queue.expire_stale()

    ok, _message, action = queue.approve(request.request_id, 'ops@example.com')

    assert not ok
    assert action is None


def test_summary_carries_what_an_operator_needs():
    queue = ApprovalQueue()
    request = queue.submit(queued_action(), reason='SBI degraded')
    summary = request.summary()

    for key in (
        'request_id', 'action_type', 'target', 'risk_level',
        'authorization', 'reason', 'status', 'blast_radius', 'seconds_remaining',
    ):
        assert key in summary


# ── End to end through the agent ─────────────────────────────────────────────

def test_operator_approval_executes_the_action():
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.85, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    pending = agent.approvals.pending()
    assert pending

    request = pending[0]
    ok, message = agent.approve(request.request_id, 'ops@example.com')

    assert ok, message
    assert 'SBI' in agent.state.active_circuit_breakers
    # The control plane records who authorised it, not just that it happened
    revision = agent.state.control_plane.current
    assert revision.author == 'operator:ops@example.com'


def test_operator_denial_leaves_the_system_untouched():
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.85, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    request = agent.approvals.pending()[0]
    before = agent.state.control_plane.revision

    agent.deny(request.request_id, 'ops@example.com', note='prefer to wait')

    assert 'SBI' not in agent.state.active_circuit_breakers
    assert agent.state.control_plane.revision == before


def test_status_exposes_pending_approvals():
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.85, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    approvals = agent.get_status()['approvals']
    assert approvals
    assert any(a['status'] == 'pending' for a in approvals)


# ── Audit trail accuracy ─────────────────────────────────────────────────────

def test_auto_approval_is_not_attributed_to_an_operator():
    """
    The agent granting its own low-risk action is still the agent. Labelling
    that revision "operator:..." would put a person's name against a decision
    no person made.
    """
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.85, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    authors = {r.author for r in agent.state.control_plane.history()}
    assert not any(a.startswith('operator:agent') for a in authors), authors
    assert any(a.startswith('agent') for a in authors)


def test_operator_approval_is_attributed_to_the_operator():
    agent = build_agent(window_size_minutes=5)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.85, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    request = agent.approvals.pending()[0]
    agent.approve(request.request_id, 'ops@example.com')

    assert agent.state.control_plane.current.author == 'operator:ops@example.com'


def test_interventions_are_not_buried_by_alerts_in_the_log():
    """
    Alerts vastly outnumber interventions on a busy incident. Filtering after
    applying a limit meant the last N entries were all alerts and every real
    decision vanished from the view.
    """
    executor = PaymentExecutor()
    for i in range(300):
        executor.execution_log.append({
            'action_id': str(i),
            'action_type': 'alert_ops' if i % 50 else 'circuit_breaker',
            'target': 'X', 'executed_at': 't', 'success': True,
            'message': '', 'parameters': {}, 'reasoning': '',
        })

    visible = executor.get_execution_history(limit=10, exclude_types=('alert_ops',))

    assert visible, "interventions must survive a flood of alerts"
    assert {e['action_type'] for e in visible} == {'circuit_breaker'}


def test_execution_log_is_bounded():
    executor = PaymentExecutor()
    executor.max_log_entries = 50
    action = queued_action(ActionType.ALERT_OPS, RiskLevel.LOW)
    for _ in range(200):
        executor._log_execution(action, {}, True, 'ok')

    assert len(executor.execution_log) <= 50
