"""
The closed loop.

The agent writes to a control plane; the traffic source reads it. If that link
is broken, an intervention changes nothing about what the agent subsequently
observes, and rollback, outcome scoring and learning are all measuring noise.
These tests assert the link exists.
"""

from datetime import datetime

from src.agent.core import PaymentAgent
from src.models.state import AgentState, PaymentMethod, PaymentStatus
from src.simulation.payment_simulator import PaymentSimulator


def success_rate(transactions):
    if not transactions:
        return 0.0
    ok = sum(1 for t in transactions if t.status == PaymentStatus.SUCCESS)
    return ok / len(transactions)


def test_circuit_breaker_diverts_traffic_away_from_issuer():
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)

    state.control_plane.trip_breaker('HDFC_BANK', author='test', reason='outage')
    batch = simulator.generate_stream(count=400, start_time=datetime.now())

    assert not any(t.issuer == 'HDFC_BANK' for t in batch)
    assert simulator.rerouted_count > 0


def test_circuit_breaker_restores_success_rate_during_outage():
    state = AgentState()
    simulator = PaymentSimulator(base_success_rate=0.96, control_plane=state)
    simulator.inject_issuer_degradation('HDFC_BANK', severity=0.9, duration_seconds=3600)

    degraded = success_rate(simulator.generate_stream(count=600, start_time=datetime.now()))

    state.control_plane.trip_breaker('HDFC_BANK', author='test', reason='outage')
    mitigated = success_rate(simulator.generate_stream(count=600, start_time=datetime.now()))

    assert mitigated > degraded + 0.05


def test_suppressed_method_stops_being_offered():
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)

    state.control_plane.suppress_method(
        PaymentMethod.UPI.value, author='test', reason='fatigue'
    )
    batch = simulator.generate_stream(count=300, start_time=datetime.now())

    assert not any(t.payment_method == PaymentMethod.UPI for t in batch)


def test_retry_limit_reduces_retry_volume():
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)

    before = simulator.generate_stream(count=2000, start_time=datetime.now())
    baseline_retries = sum(1 for t in before if t.is_retry)

    state.control_plane.set_retry_strategy(
        'global_retry_strategy', {'max_retries': 1}, author='test', reason='retry storm'
    )
    after = simulator.generate_stream(count=2000, start_time=datetime.now())
    limited_retries = sum(1 for t in after if t.is_retry)

    assert limited_retries < baseline_retries


def test_tightened_timeout_truncates_latency():
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)
    simulator.inject_latency_spike(multiplier=6.0, duration_seconds=3600)

    state.control_plane.set_retry_strategy(
        'timeout_settings', {'timeout_ms': 400}, author='test', reason='latency spike'
    )
    batch = simulator.generate_stream(count=300, start_time=datetime.now())

    assert all(t.latency_ms <= 400 for t in batch)
    assert any(t.error_code == 'TIMEOUT' for t in batch)


def test_routing_override_reduces_issuer_share():
    state = AgentState()
    simulator = PaymentSimulator(control_plane=state)

    before = simulator.generate_stream(count=1500, start_time=datetime.now())
    baseline_share = sum(1 for t in before if t.issuer == 'HDFC_BANK')

    state.control_plane.set_routing_override(
        'HDFC_BANK', {'reduce_routing_pct': 80}, author='test', reason='degradation'
    )
    after = simulator.generate_stream(count=1500, start_time=datetime.now())
    reduced_share = sum(1 for t in after if t.issuer == 'HDFC_BANK')

    assert reduced_share < baseline_share


def test_simulator_without_control_plane_still_works():
    """The control plane is optional; nothing should require it."""
    simulator = PaymentSimulator()
    batch = simulator.generate_stream(count=50, start_time=datetime.now())
    assert len(batch) == 50


def test_agent_recovers_success_rate_end_to_end():
    """
    The whole point, in one test: inject an outage, let the agent run, and the
    measured success rate should climb because of what the agent did.
    """
    agent = PaymentAgent(window_size_minutes=5)
    simulator = PaymentSimulator(base_success_rate=0.96, control_plane=agent.state)
    simulator.inject_issuer_degradation('HDFC_BANK', severity=0.85, duration_seconds=3600)

    rates = []
    for _ in range(6):
        batch = simulator.generate_stream(count=250, start_time=datetime.now())
        rates.append(success_rate(batch))
        agent.process_batch(batch)
        agent.run_cycle()

    assert agent.state.actions_executed > 0
    assert max(rates[3:]) > rates[0] + 0.05


def test_expired_scenario_stops_affecting_traffic_without_explicit_cleanup():
    simulator = PaymentSimulator(base_success_rate=0.96)
    simulator.inject_issuer_degradation('HDFC_BANK', severity=0.9, duration_seconds=0)

    batch = simulator.generate_stream(count=400, start_time=datetime.now())
    hdfc = [t for t in batch if t.issuer == 'HDFC_BANK']

    assert success_rate(hdfc) > 0.8
