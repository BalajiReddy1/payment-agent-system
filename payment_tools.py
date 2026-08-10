"""
Payment Tools Module
Extracted tool functions that can be called directly by Gemini's native function-calling,
OR served via MCP. This module has ZERO dependency on MCP or asyncio.
"""

import sys
import os
import json
import logging
from datetime import datetime
from uuid import uuid4

# Ensure we can import from src directory
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.models.state import (
    Action,
    ActionType,
    AgentState,
    AuthorizationLevel,
    RiskLevel,
    required_authorization,
)
from src.agent.executor import PaymentExecutor

logger = logging.getLogger(__name__)

# ── Shared singleton state ──────────────────────────────────────────────────
executor = PaymentExecutor()
agent_state = AgentState()

# Actions the model proposed that need a human before they can run.
pending_approvals: dict = {}


class MockObserver:
    """Provides baseline metrics to the Executor (swap for real observer in prod)."""
    def get_success_rate(self, dimension: str, condition: str) -> float:
        return 0.95

    def get_latency_stats(self, dimension: str) -> dict:
        return {"mean": 150.0}

    def get_transaction_volume(self, dimension: str, condition: str) -> int:
        return 1000


observer = MockObserver()


def _create_action(
    action_type: ActionType,
    target: str,
    parameters: dict,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
) -> Action:
    """
    Build an Action for a model-invoked tool.

    The authorization level comes from the shared action->tier map, never from
    the caller. Hardcoding AUTOMATIC here is what previously let the model
    suppress a payment method with no approver, straight past the safety model
    the docs advertise.
    """
    return Action(
        action_id=str(uuid4()),
        action_type=action_type,
        target=target,
        parameters=parameters,
        risk_level=risk_level,
        authorization_level=required_authorization(action_type),
        estimated_impact={"success_rate_delta": 0.05},
        reasoning="Triggered via LLM agent tool call",
        confidence=0.9,
        created_at=datetime.now(),
    )


def _dispatch(action: Action) -> str:
    """
    Run an action if its tier permits, otherwise queue it for a human.

    Returns a message written for the model, so it understands the difference
    between "done" and "waiting on a person" and can say so to the operator.
    """
    if action.authorization_level == AuthorizationLevel.AUTOMATIC:
        success, message = executor.execute(action, agent_state, observer)
        return f"Success: {success}\nMessage: {message}"

    pending_approvals[action.action_id] = action
    tier = action.authorization_level.value
    logger.info(
        "Action %s (%s) queued for approval [%s]",
        action.action_id, action.action_type.value, tier
    )
    return (
        f"Success: False\n"
        f"Message: {action.action_type.value} on '{action.target}' requires "
        f"{tier} authorization and was NOT executed. It is queued as "
        f"approval id {action.action_id}. A human operator must approve it via "
        f"approve_pending_action before it takes effect."
    )


# ── Public tool functions (passed directly to Gemini) ───────────────────────

def execute_circuit_breaker(issuer: str, duration_minutes: int = 10) -> str:
    """Activate a circuit breaker for a specific payment issuer.

    Args:
        issuer: The ID or name of the issuer to block (e.g. 'HDFC_Bank').
        duration_minutes: How long to keep the circuit breaker active.

    Returns:
        A status string indicating success or failure.
    """
    action = _create_action(
        action_type=ActionType.CIRCUIT_BREAKER,
        target=issuer,
        parameters={"issuer": issuer, "duration_minutes": duration_minutes},
        risk_level=RiskLevel.HIGH,
    )
    return _dispatch(action)


def adjust_retry_strategy(
    target: str,
    max_retries: int = 3,
    backoff_multiplier: float = 1.5,
    timeout_ms: int = 5000,
) -> str:
    """Adjust the retry strategy for a target gateway or merchant.

    Args:
        target: The target identifier (gateway / merchant).
        max_retries: Maximum number of retries allowed.
        backoff_multiplier: Multiplier for exponential backoff.
        timeout_ms: Timeout per attempt in milliseconds.

    Returns:
        A status string indicating success or failure.
    """
    parameters = {
        "max_retries": max_retries,
        "backoff_multiplier": backoff_multiplier,
        "timeout_ms": timeout_ms,
    }
    action = _create_action(
        action_type=ActionType.ADJUST_RETRY,
        target=target,
        parameters=parameters,
        risk_level=RiskLevel.LOW,
    )
    return _dispatch(action)


def change_routing(
    target: str, alternative_routing: bool, reduce_routing_pct: int
) -> str:
    """Change routing rules for a target to prefer alternative routes or reduce traffic.

    Args:
        target: The target identifier.
        alternative_routing: Whether to enable alternative routing.
        reduce_routing_pct: Percentage to reduce routing by (0-100).

    Returns:
        A status string indicating success or failure.
    """
    parameters = {
        "alternative_routing": alternative_routing,
        "reduce_routing_pct": reduce_routing_pct,
    }
    action = _create_action(
        action_type=ActionType.ROUTE_CHANGE,
        target=target,
        parameters=parameters,
        risk_level=RiskLevel.MEDIUM,
    )
    return _dispatch(action)


def suppress_payment_method(payment_method: str) -> str:
    """Temporarily suppress a payment method that is failing or high-risk.

    Args:
        payment_method: The payment method to suppress (e.g. 'credit_card', 'upi').

    Returns:
        A status string indicating success or failure.
    """
    parameters = {"payment_method": payment_method}
    action = _create_action(
        action_type=ActionType.METHOD_SUPPRESS,
        target=payment_method,
        parameters=parameters,
        risk_level=RiskLevel.HIGH,
    )
    return _dispatch(action)


def alert_ops_team(pattern_type: str, severity: float, description: str) -> str:
    """Send an alert to the operations team about a detected anomaly.

    Args:
        pattern_type: Category of the detected pattern.
        severity: Severity score from 0.0 to 1.0.
        description: Human-readable description of the issue.

    Returns:
        A status string indicating success or failure.
    """
    parameters = {
        "pattern_type": pattern_type,
        "severity": severity,
        "description": description,
    }
    action = _create_action(
        action_type=ActionType.ALERT_OPS,
        target="ops_team",
        parameters=parameters,
        risk_level=RiskLevel.LOW,
    )
    return _dispatch(action)


def monitor_and_rollback() -> str:
    """Check all active interventions and roll back any that are degrading performance.

    Returns:
        A summary of which interventions were rolled back, if any.
    """
    rolled_back_ids = executor.monitor_and_rollback(agent_state, observer)
    if rolled_back_ids:
        return f"Rolled back interventions: {rolled_back_ids}"
    return "Checked interventions. No rollbacks triggered."


def get_agent_state() -> str:
    """Retrieve the current agent state including active circuit breakers and metrics.

    Returns:
        A JSON string of the current agent state.
    """
    active_interventions = executor.get_active_interventions()
    state_info = {
        "overall_success_rate": agent_state.overall_success_rate,
        "average_latency_ms": agent_state.average_latency_ms,
        "active_circuit_breakers": list(agent_state.active_circuit_breakers),
        "suppressed_methods": list(agent_state.suppressed_methods),
        "retry_strategies": agent_state.retry_strategies,
        "routing_overrides": agent_state.routing_overrides,
        "active_interventions_count": len(active_interventions),
    }
    return json.dumps(state_info, default=str, indent=2)


def list_pending_approvals() -> str:
    """List actions that were proposed but are waiting on human authorization.

    Returns:
        A JSON string describing each pending action and why it is held.
    """
    if not pending_approvals:
        return "No actions are awaiting approval."

    return json.dumps([
        {
            "approval_id": action.action_id,
            "action": action.action_type.value,
            "target": action.target,
            "required_authorization": action.authorization_level.value,
            "risk_level": action.risk_level.value,
            "parameters": action.parameters,
            "proposed_at": action.created_at.isoformat(),
        }
        for action in pending_approvals.values()
    ], indent=2)


def approve_pending_action(approval_id: str, approver: str) -> str:
    """Approve and execute an action that was held for human authorization.

    This represents a human operator signing off. The agent should surface the
    pending action to a person rather than calling this on its own behalf.

    Args:
        approval_id: The approval id returned when the action was queued.
        approver: Identity of the human approving the action.

    Returns:
        A status string indicating whether the action executed.
    """
    action = pending_approvals.pop(approval_id, None)
    if action is None:
        return f"Success: False\nMessage: No pending action with id {approval_id}"

    if not approver or not approver.strip():
        pending_approvals[approval_id] = action
        return "Success: False\nMessage: An approver identity is required"

    action.approver = approver
    success, message = executor.execute(action, agent_state, observer)
    if not success:
        pending_approvals[approval_id] = action
    return f"Success: {success}\nMessage: {message} (approved by {approver})"


# ── Convenience list for LLM tool registration ──────────────────────────────
# approve_pending_action is deliberately excluded: authorising an action is a
# human's job, and handing the model that tool would let it approve its own
# proposals, which defeats the entire purpose of the tier.
ALL_TOOLS = [
    execute_circuit_breaker,
    adjust_retry_strategy,
    change_routing,
    suppress_payment_method,
    alert_ops_team,
    monitor_and_rollback,
    get_agent_state,
    list_pending_approvals,
]
