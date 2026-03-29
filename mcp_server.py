import sys
import os
import json
from datetime import datetime
from uuid import uuid4
from mcp.server.fastmcp import FastMCP

# Ensure we can import from src directory
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.models.state import (
    Action, 
    ActionType, 
    AgentState, 
    RiskLevel, 
    AuthorizationLevel
)
from src.agent.executor import PaymentExecutor

# Initialize the FastMCP Server
mcp = FastMCP("PaymentAgentHands")

# Global instances to maintain state across tool calls
executor = PaymentExecutor()
agent_state = AgentState()

class MockObserver:
    """Mock observer to provide baseline metrics to the Executor."""
    def get_success_rate(self, dimension: str, condition: str) -> float:
        return 0.95
        
    def get_latency_stats(self, dimension: str) -> dict:
        return {'mean': 150.0}
        
    def get_transaction_volume(self, dimension: str, condition: str) -> int:
        return 1000

observer = MockObserver()

def _create_action(
    action_type: ActionType, 
    target: str, 
    parameters: dict, 
    risk_level: RiskLevel = RiskLevel.MEDIUM
) -> Action:
    """Helper function to construct an Action object."""
    return Action(
        action_id=str(uuid4()),
        action_type=action_type,
        target=target,
        parameters=parameters,
        risk_level=risk_level,
        authorization_level=AuthorizationLevel.AUTOMATIC,
        estimated_impact={"success_rate": 0.05},
        reasoning="Triggered automatically via MCP Tool",
        confidence=0.9,
        created_at=datetime.now()
    )


@mcp.tool()
def execute_circuit_breaker(issuer: str, duration_minutes: int = 10) -> str:
    """
    Execute a circuit breaker for a specific issuer.
    
    Args:
        issuer: The ID or name of the issuer to block.
        duration_minutes: How long to keep the circuit breaker active.
    """
    action = _create_action(
        action_type=ActionType.CIRCUIT_BREAKER, 
        target=issuer, 
        parameters={'issuer': issuer, 'duration_minutes': duration_minutes},
        risk_level=RiskLevel.HIGH
    )
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


@mcp.tool()
def adjust_retry_strategy(target: str, max_retries: int = 3, backoff_multiplier: float = 1.5, timeout_ms: int = 5000) -> str:
    """
    Adjust the retry strategy for a particular target (e.g., merchant or gateway).
    
    Args:
        target: The target identifier.
        max_retries: Maximum number of retries.
        backoff_multiplier: Multiplier for backoff algorithm.
        timeout_ms: Timeout in milliseconds.
    """
    parameters = {
        'max_retries': max_retries,
        'backoff_multiplier': backoff_multiplier,
        'timeout_ms': timeout_ms
    }
    action = _create_action(
        action_type=ActionType.ADJUST_RETRY,
        target=target,
        parameters=parameters,
        risk_level=RiskLevel.LOW
    )
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


@mcp.tool()
def change_routing(target: str, alternative_routing: bool, reduce_routing_pct: int) -> str:
    """
    Change routing rules to prefer alternative routes or reduce traffic percentage.
    
    Args:
        target: The target identifier.
        alternative_routing: Whether to enable alternative routing.
        reduce_routing_pct: Percentage to reduce routing by.
    """
    parameters = {
        'alternative_routing': alternative_routing,
        'reduce_routing_pct': reduce_routing_pct
    }
    action = _create_action(
        action_type=ActionType.ROUTE_CHANGE,
        target=target,
        parameters=parameters,
        risk_level=RiskLevel.MEDIUM
    )
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


@mcp.tool()
def suppress_payment_method(payment_method: str) -> str:
    """
    Temporarily suppress a payment method that is failing or high-risk.
    
    Args:
        payment_method: The specific payment method string (e.g., 'credit_card', 'upi').
    """
    parameters = {
        'payment_method': payment_method
    }
    action = _create_action(
        action_type=ActionType.METHOD_SUPPRESS,
        target=payment_method,
        parameters=parameters,
        risk_level=RiskLevel.HIGH
    )
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


@mcp.tool()
def alert_ops_team(pattern_type: str, severity: float, description: str) -> str:
    """
    Send an alert to the ops team regarding a detected pattern.
    
    Args:
        pattern_type: Type of the pattern.
        severity: Severity of the alert (0.0 to 1.0).
        description: Text description of the issue.
    """
    parameters = {
        'pattern_type': pattern_type,
        'severity': severity,
        'description': description
    }
    action = _create_action(
        action_type=ActionType.ALERT_OPS,
        target="ops_team",
        parameters=parameters,
        risk_level=RiskLevel.LOW
    )
    success, message = executor.execute(action, agent_state, observer)
    return f"Success: {success}\nMessage: {message}"


@mcp.tool()
def monitor_and_rollback() -> str:
    """
    Run the monitoring check to see if any active interventions need to be rolled back
    based on success rate or latency degradation, or if their duration expired.
    """
    rolled_back_ids = executor.monitor_and_rollback(agent_state, observer)
    if rolled_back_ids:
        return f"Rolled back interventions: {rolled_back_ids}"
    return "Checked interventions. No rollbacks triggered."


@mcp.tool()
def get_agent_state() -> str:
    """
    Retrieves the current agent state including performance metrics and active interventions.
    """
    active_interventions = executor.get_active_interventions()
    
    state_info = {
        "overall_success_rate": agent_state.overall_success_rate,
        "average_latency_ms": agent_state.average_latency_ms,
        "active_circuit_breakers": list(agent_state.active_circuit_breakers),
        "suppressed_methods": list(agent_state.suppressed_methods),
        "retry_strategies": agent_state.retry_strategies,
        "routing_overrides": agent_state.routing_overrides,
        "active_interventions_count": len(active_interventions)
    }
    return json.dumps(state_info, indent=2)


if __name__ == "__main__":
    # Start the FastMCP server via stdio by default
    mcp.run()
