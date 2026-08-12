"""
Authorization tiers.

The documented safety model says method suppression needs a human. That has to
be true on every path that can create an action - the autonomous loop and the
LLM tool layer alike - or it is not a guardrail, just a label.
"""

import pytest

from src.agent.executor import PaymentExecutor
from src.models.state import (
    ActionType,
    AgentState,
    AuthorizationLevel,
    RiskLevel,
    required_authorization,
)
from src.safety.approvals import ApprovalQueue
from src.safety.guardrails import SafetyGuardrails, SafetyLimits

from conftest import make_action


class StubObserver:
    def get_success_rate(self, dimension, condition):
        return 0.95

    def get_latency_stats(self, dimension, key=None):
        return {'mean': 150.0}

    def get_transaction_volume(self, dimension, condition):
        return 1000


@pytest.fixture
def observer():
    return StubObserver()


def test_documented_tiers():
    assert required_authorization(ActionType.ADJUST_RETRY) == AuthorizationLevel.AUTOMATIC
    assert required_authorization(ActionType.ALERT_OPS) == AuthorizationLevel.AUTOMATIC
    assert required_authorization(ActionType.CIRCUIT_BREAKER) == AuthorizationLevel.SEMI_AUTOMATIC
    assert required_authorization(ActionType.ROUTE_CHANGE) == AuthorizationLevel.SEMI_AUTOMATIC
    assert required_authorization(ActionType.METHOD_SUPPRESS) == AuthorizationLevel.MANUAL


def test_unknown_action_defaults_to_manual():
    assert required_authorization("something_new") == AuthorizationLevel.MANUAL


def test_executor_refuses_unapproved_manual_action(observer):
    executor = PaymentExecutor()
    state = AgentState()
    action = make_action(
        action_type=ActionType.METHOD_SUPPRESS,
        target='upi',
        parameters={'payment_method': 'upi'},
        risk_level=RiskLevel.HIGH,
    )

    success, message = executor.execute(action, state, observer)

    assert not success
    assert 'authorization' in message.lower()
    assert 'upi' not in state.suppressed_methods


def test_executor_allows_manual_action_once_approved(observer):
    executor = PaymentExecutor()
    state = AgentState()
    action = make_action(
        action_type=ActionType.METHOD_SUPPRESS,
        target='upi',
        parameters={'payment_method': 'upi'},
        risk_level=RiskLevel.HIGH,
    )
    action.approver = 'ops@example.com'

    success, _ = executor.execute(action, state, observer)

    assert success
    assert 'upi' in state.suppressed_methods


def test_llm_tools_cannot_bypass_the_tier():
    """The regression: tool calls hardcoded AUTOMATIC for every action."""
    import payment_tools

    payment_tools.executor = PaymentExecutor()
    payment_tools.agent_state = AgentState()
    payment_tools.approvals = ApprovalQueue()

    result = payment_tools.suppress_payment_method('upi')

    assert 'Success: False' in result
    assert 'manual' in result
    assert payment_tools.agent_state.suppressed_methods == set()
    assert len(payment_tools.approvals.pending()) == 1


def test_llm_tool_automatic_tier_still_executes():
    import payment_tools

    payment_tools.executor = PaymentExecutor()
    payment_tools.agent_state = AgentState()
    payment_tools.approvals = ApprovalQueue()

    result = payment_tools.adjust_retry_strategy('global_retry_strategy', max_retries=2)

    assert 'Success: True' in result
    assert payment_tools.agent_state.retry_strategies['global_retry_strategy']['max_retries'] == 2


def test_human_approval_releases_a_queued_action():
    import payment_tools

    payment_tools.executor = PaymentExecutor()
    payment_tools.agent_state = AgentState()
    payment_tools.approvals = ApprovalQueue()

    payment_tools.suppress_payment_method('upi')
    approval_id = payment_tools.approvals.pending()[0].request_id

    result = payment_tools.approve_pending_action(approval_id, 'ops@example.com')

    assert 'Success: True' in result
    assert 'upi' in payment_tools.agent_state.suppressed_methods
    assert not payment_tools.approvals.pending()


def test_approval_requires_an_approver_identity():
    import payment_tools

    payment_tools.executor = PaymentExecutor()
    payment_tools.agent_state = AgentState()
    payment_tools.approvals = ApprovalQueue()

    payment_tools.suppress_payment_method('upi')
    approval_id = payment_tools.approvals.pending()[0].request_id

    result = payment_tools.approve_pending_action(approval_id, '   ')

    assert 'Success: False' in result
    # The action stays queued rather than being silently dropped
    assert approval_id in {r.request_id for r in payment_tools.approvals.pending()}


def test_model_is_not_given_the_approval_tool():
    """Letting the agent approve its own proposals would void the tiers."""
    import payment_tools

    tool_names = {tool.__name__ for tool in payment_tools.ALL_TOOLS}
    assert 'approve_pending_action' not in tool_names


def test_guardrails_block_oversized_blast_radius():
    guardrails = SafetyGuardrails(SafetyLimits(max_traffic_impact_percent=15.0))
    action = make_action(estimated_impact={
        'success_rate_delta': 0.15,
        'latency_delta_ms': -100.0,
        'cost_delta_per_txn': 0.01,
        'affected_traffic_pct': 0.40,
    })

    allowed, _, reason = guardrails.check_action_allowed(action, AgentState(), 0)

    assert not allowed
    assert 'Blast radius' in reason


def test_guardrails_block_low_confidence():
    guardrails = SafetyGuardrails(SafetyLimits(min_confidence_for_action=0.6))
    allowed, _, reason = guardrails.check_action_allowed(
        make_action(confidence=0.2), AgentState(), 0
    )

    assert not allowed
    assert 'Confidence too low' in reason


def test_large_impact_escalates_authorization():
    guardrails = SafetyGuardrails(SafetyLimits())
    action = make_action(
        action_type=ActionType.ADJUST_RETRY,
        estimated_impact={'affected_traffic_pct': 0.30},
    )
    assert guardrails.required_authorization(action) == AuthorizationLevel.MANUAL
