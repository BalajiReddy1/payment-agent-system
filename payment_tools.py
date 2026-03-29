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
    RiskLevel,
    AuthorizationLevel,
)
from src.agent.executor import PaymentExecutor

logger = logging.getLogger(__name__)

# ── Shared singleton state ──────────────────────────────────────────────────
executor = PaymentExecutor()
agent_state = AgentState()


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
    return Action(
        action_id=str(uuid4()),
        action_type=action_type,
        target=target,
        parameters=parameters,
        risk_level=risk_level,
        authorization_level=AuthorizationLevel.AUTOMATIC,
        estimated_impact={"success_rate": 0.05},
        reasoning="Triggered automatically via Gemini Agent",
        confidence=0.9,
        created_at=datetime.now(),
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
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


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
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


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
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


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
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


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
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


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


# ── Convenience list for Gemini tool registration ───────────────────────────
ALL_TOOLS = [
    execute_circuit_breaker,
    adjust_retry_strategy,
    change_routing,
    suppress_payment_method,
    alert_ops_team,
    monitor_and_rollback,
    get_agent_state,
]
