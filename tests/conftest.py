"""Shared test fixtures."""

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.state import (
    Action,
    ActionType,
    AgentState,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
    RiskLevel,
    required_authorization,
)


@pytest.fixture(autouse=True)
def deterministic_random():
    """Every test starts from the same seed so failures are reproducible."""
    random.seed(1234)


@pytest.fixture
def state():
    return AgentState()


def make_transaction(
    status=PaymentStatus.SUCCESS,
    issuer="HDFC_BANK",
    method=PaymentMethod.CREDIT_CARD,
    region="NORTH",
    latency_ms=200.0,
    error_code=None,
    is_retry=False,
    age_seconds=0,
    transaction_id=None,
):
    """Build a transaction with sensible defaults for the field under test."""
    return PaymentTransaction(
        transaction_id=transaction_id or f"txn-{random.random()}",
        timestamp=datetime.now() - timedelta(seconds=age_seconds),
        amount=1000.0,
        currency="INR",
        payment_method=method,
        issuer=issuer,
        merchant_id="MERCHANT_0001",
        status=status,
        error_code=error_code,
        error_message=f"{error_code}: declined" if error_code else None,
        latency_ms=latency_ms,
        retry_count=1 if is_retry else 0,
        is_retry=is_retry,
        original_transaction_id="orig-1" if is_retry else None,
        region=region,
    )


def make_action(
    action_type=ActionType.CIRCUIT_BREAKER,
    target="HDFC_BANK",
    parameters=None,
    risk_level=RiskLevel.MEDIUM,
    confidence=0.9,
    estimated_impact=None,
    authorization_level=None,
):
    """Build an Action whose authorization tier defaults to the real policy."""
    return Action(
        action_id="",
        action_type=action_type,
        target=target,
        parameters=parameters if parameters is not None else {"issuer": target},
        risk_level=risk_level,
        authorization_level=authorization_level or required_authorization(action_type),
        estimated_impact=estimated_impact or {
            "success_rate_delta": 0.15,
            "latency_delta_ms": -100.0,
            "cost_delta_per_txn": 0.01,
            "affected_traffic_pct": 0.05,
        },
        reasoning="test",
        confidence=confidence,
        created_at=datetime.now(),
    )
