"""
FastAPI REST API for Payment Agent System
Provides programmatic access to agent functionality.
"""

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src import views
from src.agent.core import PaymentAgent
from src.models.state import PaymentMethod, PaymentStatus, PaymentTransaction
from src.runtime import AgentRuntime
from src.utils.env import load_env_file

# Before anything reads os.environ. Provider keys stay on this service; the
# browser never sees them and the frontend proxies through us.
load_env_file(project_root / ".env")

runtime = AgentRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runtime.start()
    try:
        yield
    finally:
        runtime.stop()

# Initialize FastAPI app
app = FastAPI(
    title="Payment Agent API",
    description="REST API for payment recovery operations.",
    version="1.0.0",
    lifespan=lifespan,
)

def get_runtime() -> AgentRuntime:
    """Return the single live runtime, starting it for direct module callers."""
    if runtime.agent is None:
        runtime.start()
    return runtime


def get_agent() -> PaymentAgent:
    return get_runtime().agent


def get_simulator():
    return get_runtime().simulator


# Request/Response Models
class TransactionInput(BaseModel):
    """Input model for submitting a transaction."""
    transaction_id: str
    amount: float
    currency: str = "INR"
    payment_method: str
    issuer: str
    merchant_id: str
    status: str
    error_code: Optional[str] = None
    latency_ms: float
    region: str = "NORTH"


class ScenarioInput(BaseModel):
    """Input model for injecting a failure scenario."""
    type: str  # issuer_degradation, retry_storm, latency_spike, geographic_failure
    issuer: Optional[str] = None
    region: Optional[str] = None
    severity: float = 0.6
    duration_seconds: int = 120
    multiplier: float = 3.0


class ApprovalDecision(BaseModel):
    """An operator's verdict on a queued action."""
    approver: str
    note: str = ""


class RazorpayTestModeSettings(BaseModel):
    """Optional labels for credentials held only in the service environment."""
    merchant_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str


class StatusResponse(BaseModel):
    """Agent status response."""
    is_active: bool
    cycle_count: int
    success_rate: float
    avg_latency_ms: float
    total_transactions: int
    actions_executed: int
    active_scenarios: int


# Endpoints
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    report = get_runtime().health()
    return HealthResponse(
        status="healthy" if report["loop_running"] else "degraded",
        timestamp=datetime.now().isoformat()
    )


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get current agent status and metrics."""
    agent = get_agent()
    simulator = get_simulator()
    status = agent.get_status()
    
    return StatusResponse(
        is_active=status['is_active'],
        cycle_count=status['cycle_count'],
        success_rate=status['state']['success_rate'],
        avg_latency_ms=status['state']['avg_latency_ms'],
        total_transactions=status['state']['total_transactions'],
        actions_executed=status['performance']['actions_executed'],
        active_scenarios=len(simulator.get_active_scenarios())
    )


@app.post("/cycle")
async def run_cycle():
    """Trigger an agent analysis cycle."""
    results = get_runtime().run_once()
    
    return {
        "cycle": results['cycle'],
        "success_rate": results['observation_summary']['overall_success_rate'],
        "patterns_detected": len(results['patterns_detected']),
        "actions_taken": len(results['actions_taken']),
        "patterns": [
            {
                "type": p['type'],
                "severity": p['severity'],
                "description": p['description']
            }
            for p in results['patterns_detected']
        ],
        "actions": [
            {
                "type": a['type'],
                "target": a['target'],
                "risk_level": a.get('risk_level', 'low')
            }
            for a in results['actions_taken']
        ]
    }


@app.post("/transactions")
async def submit_transactions(transactions: List[TransactionInput]):
    """Submit transactions to the agent for processing."""
    agent = get_agent()
    
    # Convert to PaymentTransaction objects
    payment_transactions = []
    for txn in transactions:
        try:
            pt = PaymentTransaction(
                transaction_id=txn.transaction_id,
                timestamp=datetime.now(),
                amount=txn.amount,
                currency=txn.currency,
                payment_method=PaymentMethod(txn.payment_method),
                issuer=txn.issuer,
                merchant_id=txn.merchant_id,
                status=PaymentStatus(txn.status),
                error_code=txn.error_code,
                error_message=None,
                latency_ms=txn.latency_ms,
                retry_count=0,
                is_retry=False,
                original_transaction_id=None,
                region=txn.region,
                processor="api"
            )
            payment_transactions.append(pt)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid transaction: {e}")
    
    agent.process_batch(payment_transactions)
    
    return {
        "processed": len(payment_transactions),
        "message": f"Successfully processed {len(payment_transactions)} transactions"
    }


@app.post("/scenarios/inject")
async def inject_scenario(scenario: ScenarioInput):
    """Inject a failure scenario."""
    simulator = get_simulator()
    
    if scenario.type == "issuer_degradation":
        if not scenario.issuer:
            raise HTTPException(status_code=400, detail="Issuer required for issuer_degradation")
        simulator.inject_issuer_degradation(
            issuer=scenario.issuer,
            severity=scenario.severity,
            duration_seconds=scenario.duration_seconds
        )
        return {"message": f"Injected issuer degradation for {scenario.issuer}"}
    
    elif scenario.type == "retry_storm":
        simulator.inject_retry_storm(duration_seconds=scenario.duration_seconds)
        return {"message": "Injected retry storm"}
    
    elif scenario.type == "latency_spike":
        simulator.inject_latency_spike(
            multiplier=scenario.multiplier,
            duration_seconds=scenario.duration_seconds
        )
        return {"message": f"Injected latency spike ({scenario.multiplier}x)"}
    
    elif scenario.type == "geographic_failure":
        if not scenario.region:
            raise HTTPException(status_code=400, detail="Region required for geographic_failure")
        simulator.inject_geographic_failure(
            region=scenario.region,
            severity=scenario.severity,
            duration_seconds=scenario.duration_seconds
        )
        return {"message": f"Injected geographic failure for {scenario.region}"}
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown scenario type: {scenario.type}")


@app.post("/demo/run")
async def run_judge_demo():
    """Reset the runtime into the repeatable ICICI recovery demonstration."""
    snapshot = get_runtime().start_demo()
    return {
        "message": "Judge demo ready: ICICI degradation detected, route change measured, circuit breaker awaiting approval.",
        "snapshot": snapshot,
    }


@app.post("/sources/razorpay/test-mode")
async def connect_razorpay_test_mode(settings: RazorpayTestModeSettings):
    """Read Razorpay test-mode payments without exposing credentials to clients."""
    key_id = os.environ.get("RAZORPAY_TEST_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_TEST_KEY_SECRET")
    if not key_id or not key_secret:
        raise HTTPException(
            status_code=409,
            detail=(
                "Set RAZORPAY_TEST_KEY_ID and RAZORPAY_TEST_KEY_SECRET on the API service. "
                "The browser never sends or stores Razorpay credentials."
            ),
        )

    snapshot = get_runtime().connect_razorpay_test_mode(
        key_id=key_id,
        key_secret=key_secret,
        merchant_id=settings.merchant_id or os.environ.get("RAZORPAY_MERCHANT_ID", "razorpay-test-merchant"),
        base_url=os.environ.get("RAZORPAY_API_BASE_URL", "https://api.razorpay.com"),
    )
    return {
        "message": "Razorpay test-mode intake is active. Payments are read-only; recovery policies remain gated and published for an external router.",
        "snapshot": snapshot,
    }


@app.delete("/scenarios/clear")
async def clear_scenarios():
    """Clear all active failure scenarios."""
    simulator = get_simulator()
    count = len(simulator.failure_scenarios)
    simulator.failure_scenarios.clear()
    return {"message": f"Cleared {count} active scenarios"}


@app.get("/scenarios")
async def list_scenarios():
    """List all active failure scenarios."""
    simulator = get_simulator()
    scenarios = simulator.get_active_scenarios()
    return {
        "count": len(scenarios),
        "scenarios": [
            {
                "type": s['type'],
                "expires_at": s['expires_at'].isoformat()
            }
            for s in scenarios
        ]
    }


# ── Parity with the console ──────────────────────────────────────────────────
#
# These read the same functions in src/views.py that the console serves, so the
# two surfaces cannot answer differently. Everything below was previously
# available only by looking at the console, which made the API a strictly worse
# view of the same agent.


@app.get("/snapshot")
async def snapshot():
    """
    Everything needed to render the agent's state, as one consistent document.

    Assembling this from several endpoints lets the parts disagree - metrics
    from one cycle, control plane from the next - with no way for a reader to
    tell.
    """
    return get_runtime().snapshot()


@app.get("/incidents")
async def list_incidents():
    """Open and recently closed incidents, with the advisor's assessment."""
    agent = get_agent()
    return {"incidents": [i.summary() for i in agent.incident_tracker.all()]}


@app.get("/experiments")
async def list_experiments():
    """
    Holdout experiments and what they measured.

    This is how an intervention's effect is known rather than assumed: a
    concurrent untreated control group, not a before/after comparison against
    a moving baseline.
    """
    return {"experiments": get_agent().get_status().get('experiments', [])}


@app.get("/control-plane")
async def get_control_plane():
    """The current policy and the revision history that produced it."""
    return views.control_plane(get_agent().state.control_plane)


@app.get("/approvals")
async def list_approvals():
    """Actions the agent proposed but is not authorized to take alone."""
    agent = get_agent()
    return {"approvals": [r.summary() for r in agent.approvals.pending()]}


@app.post("/approvals/{request_id}/approve")
async def approve(request_id: str, decision: ApprovalDecision):
    """
    Authorize a queued action.

    The approver is required, not defaulted: an approval with nobody's name
    against it is an audit trail that records that permission was granted and
    not who granted it.
    """
    ok, message = get_agent().approve(request_id, decision.approver)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"ok": True, "message": message}


@app.post("/approvals/{request_id}/deny")
async def deny(request_id: str, decision: ApprovalDecision):
    """Refuse a queued action."""
    ok, message = get_agent().deny(request_id, decision.approver, note=decision.note)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"ok": True, "message": message}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
