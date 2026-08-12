"""
Executor lifecycle.

Two distinctions this file pins down: an intervention that ran its planned
course is not a rollback, and a notification is not an intervention.
"""

from datetime import datetime, timedelta

from src.agent.executor import PaymentExecutor
from src.models.state import ActionType, AgentState, RiskLevel

from conftest import make_action
from test_authorization import StubObserver


def approved(action):
    action.approver = 'ops@example.com'
    return action


def test_expiry_is_not_counted_as_a_rollback():
    executor = PaymentExecutor()
    state = AgentState()
    observer = StubObserver()

    action = approved(make_action(parameters={'issuer': 'HDFC_BANK', 'duration_minutes': 10}))
    assert executor.execute(action, state, observer)[0]

    # Pretend the intervention has been running longer than planned
    action.executed_at = datetime.now() - timedelta(minutes=30)

    rolled_back = executor.monitor_and_rollback(state, observer)

    assert rolled_back == []
    assert state.rollbacks_last_hour == 0
    assert action.action_id in executor.expired_actions
    assert action.status == 'completed'
    assert 'HDFC_BANK' not in state.active_circuit_breakers


def test_harmful_action_is_rolled_back_and_counted():
    executor = PaymentExecutor()
    state = AgentState()
    observer = StubObserver()

    action = approved(make_action(parameters={'issuer': 'HDFC_BANK', 'duration_minutes': 60}))
    assert executor.execute(action, state, observer)[0]

    # Success rate collapses after the action
    class Degraded(StubObserver):
        def get_success_rate(self, dimension, condition):
            return 0.50

    rolled_back = executor.monitor_and_rollback(state, Degraded())

    assert rolled_back == [action.action_id]
    assert state.rollbacks_last_hour == 1
    assert action.status == 'rolled_back'
    assert 'HDFC_BANK' not in state.active_circuit_breakers


def test_alerts_do_not_occupy_an_intervention_slot():
    """
    An alert used to be registered as an active intervention, so the duplicate
    check then blocked every later action on the same target forever.
    """
    executor = PaymentExecutor()
    state = AgentState()
    observer = StubObserver()

    alert = make_action(
        action_type=ActionType.ALERT_OPS,
        target='ops_team:issuer_degradation:HDFC_BANK',
        parameters={'pattern_type': 'issuer_degradation', 'severity': 0.9},
        risk_level=RiskLevel.LOW,
    )

    assert executor.execute(alert, state, observer)[0]
    assert executor.active_interventions == {}

    # The same alert can be raised again on a later cycle
    repeat = make_action(
        action_type=ActionType.ALERT_OPS,
        target='ops_team:issuer_degradation:HDFC_BANK',
        parameters={'pattern_type': 'issuer_degradation', 'severity': 0.9},
        risk_level=RiskLevel.LOW,
    )
    assert executor.execute(repeat, state, observer)[0]


def test_duplicate_stateful_action_is_refused():
    executor = PaymentExecutor()
    state = AgentState()
    observer = StubObserver()

    assert executor.execute(approved(make_action()), state, observer)[0]
    success, message = executor.execute(approved(make_action()), state, observer)

    assert not success
    assert 'already active' in message


def test_rolling_back_one_intervention_leaves_another_running():
    """
    Two unrelated interventions are live; one turns harmful and is withdrawn.
    Deriving the undo from the revision it produced means the other survives -
    a snapshot-style revert to the previous revision would have clobbered it.
    """
    executor = PaymentExecutor()
    state = AgentState()
    observer = StubObserver()

    breaker = approved(make_action(parameters={'issuer': 'HDFC_BANK', 'duration_minutes': 60}))
    retry = make_action(
        action_type=ActionType.ADJUST_RETRY,
        target='global_retry_strategy',
        parameters={'max_retries': 1, 'duration_minutes': 60},
        risk_level=RiskLevel.LOW,
    )
    executor.execute(breaker, state, observer)
    executor.execute(retry, state, observer)

    # Only the breaker is expired; the retry adjustment keeps running
    breaker.executed_at = datetime.now() - timedelta(minutes=120)
    executor.monitor_and_rollback(state, observer)

    assert state.active_circuit_breakers == frozenset()
    assert state.retry_strategies['global_retry_strategy']['max_retries'] == 1
    assert retry.action_id in executor.active_interventions


def test_action_records_the_revision_it_produced():
    executor = PaymentExecutor()
    state = AgentState()
    observer = StubObserver()

    action = approved(make_action())
    executor.execute(action, state, observer)

    assert action.control_plane_revision == state.control_plane.revision
    revision = state.control_plane.get(action.control_plane_revision)
    assert revision.action_id == action.action_id
    assert revision.author.startswith('operator:')


def test_revert_restores_every_control_plane_field():
    executor = PaymentExecutor()
    state = AgentState()
    observer = StubObserver()

    breaker = approved(make_action(parameters={'issuer': 'HDFC_BANK', 'duration_minutes': 1}))
    retry = make_action(
        action_type=ActionType.ADJUST_RETRY,
        target='global_retry_strategy',
        parameters={'max_retries': 1, 'duration_minutes': 1},
        risk_level=RiskLevel.LOW,
    )
    executor.execute(breaker, state, observer)
    executor.execute(retry, state, observer)

    assert state.active_circuit_breakers == {'HDFC_BANK'}
    assert 'global_retry_strategy' in state.retry_strategies

    for action in (breaker, retry):
        action.executed_at = datetime.now() - timedelta(minutes=30)
    executor.monitor_and_rollback(state, observer)

    assert state.active_circuit_breakers == set()
    assert state.retry_strategies == {}
    assert executor.active_interventions == {}
