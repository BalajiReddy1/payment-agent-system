"""
FastAPI REST API for Payment Agent System
Provides programmatic access to agent functionality.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agent.core import PaymentAgent
from src.models.state import PaymentMethod, PaymentStatus, PaymentTransaction
from src.simulation.payment_simulator import PaymentSimulator

# Initialize FastAPI app
app = FastAPI(
    title="Payment Agent API",
    description="REST API for the Agentic AI Payment Operations System",
    version="1.0.0"
)

# Global agent and simulator instances
agent: Optional[PaymentAgent] = None
simulator: Optional[PaymentSimulator] = None


def get_agent() -> PaymentAgent:
    """Get or create agent instance."""
    global agent
    if agent is None:
        agent = PaymentAgent(
            window_size_minutes=10,
            analysis_interval_seconds=30,
            auto_approve_low_risk=True
        )
    return agent


def get_simulator() -> PaymentSimulator:
    """Get or create simulator instance."""
    global simulator
    if simulator is None:
        simulator = PaymentSimulator(base_success_rate=0.95)
    return simulator


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
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat()
    )


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get current agent status and metrics."""
    agent = get_agent()
    simulator = get_simulator()
    status = agent.get_status()
    
    return StatusResponse(
        is_active=status['state']['is_active'],
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
    agent = get_agent()
    simulator = get_simulator()
    
    # Generate some transactions first
    transactions = simulator.generate_stream(count=25, start_time=datetime.now())
    agent.process_batch(transactions)
    
    # Run cycle
    results = agent.run_cycle()
    
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
