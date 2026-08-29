"""
Publishing the control plane.

The system's central claim is that the control plane is real even when the
traffic is simulated. Inside one process that was true; outside it there was no
way for anything to read the policy, so the claim had nothing behind it.

These tests are about the failure modes, because that is the only part that
matters. A policy document that reads correctly when everything works and
returns an empty policy when it does not would drop every live circuit breaker
at the exact moment the system was already in trouble.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.control.plane import ControlPlane
from src.control.publish import SCHEMA_VERSION, PolicyClient, PolicyPublisher


def workspace():
    return Path(tempfile.mkdtemp()) / 'policy.json'


def loaded_plane():
    plane = ControlPlane()
    plane.trip_breaker('SBI', author='agent', reason='issuer down')
    plane.suppress_method('upi', author='agent', reason='method fatigue')
    plane.set_routing_override(
        'HDFC_BANK', {'reduce_routing_pct': 50}, author='agent', reason='degraded'
    )
    plane.set_retry_strategy(
        'HDFC_BANK', {'max_retries': 1, 'backoff_seconds': 30},
        author='agent', reason='retry storm',
    )
    plane.set_holdout('SBI', 0.10, author='agent', reason='measure the fix')
    return plane


def published(path=None):
    path = path or workspace()
    publisher = PolicyPublisher(path)
    publisher.publish(loaded_plane())
    return path, publisher


# ── The document ─────────────────────────────────────────────────────────────

def test_the_document_carries_the_whole_policy():
    path, _ = published()
    document = json.loads(path.read_text())

    policy = document['policy']
    assert policy['circuit_breakers'] == ['SBI']
    assert policy['suppressed_methods'] == ['upi']
    assert policy['routing_overrides']['HDFC_BANK']['reduce_routing_pct'] == 50
    assert policy['retry_strategies']['HDFC_BANK']['max_retries'] == 1
    assert policy['holdouts']['SBI'] == 0.10


def test_the_document_is_attributed_and_versioned():
    path, _ = published()
    document = json.loads(path.read_text())

    assert document['schema_version'] == SCHEMA_VERSION
    assert document['revision'] > 0
    assert document['author']
    assert document['reason']


def test_the_document_says_when_it_goes_stale():
    """
    Without this a reader cannot tell a live policy from one written by an
    agent that died an hour ago, so a crashed agent's last intervention stays
    in force forever with nothing to alert on.
    """
    path, _ = published()
    document = json.loads(path.read_text())

    published_at = datetime.fromisoformat(document['published_at'])
    expires_at = datetime.fromisoformat(document['expires_at'])

    assert expires_at > published_at
    assert document['refresh_seconds'] > 0


# ── Writing ──────────────────────────────────────────────────────────────────

def test_an_unchanged_revision_is_not_rewritten():
    """
    Churning the file's mtime on every cycle makes "when did the policy last
    change" unanswerable.
    """
    path = workspace()
    plane = loaded_plane()
    publisher = PolicyPublisher(path, refresh_seconds=3600)

    assert publisher.publish(plane)
    assert not publisher.publish(plane)
    assert publisher.writes == 1


def test_a_new_revision_is_published():
    path = workspace()
    plane = loaded_plane()
    publisher = PolicyPublisher(path, refresh_seconds=3600)
    publisher.publish(plane)

    plane.trip_breaker('HDFC_BANK', author='agent', reason='second issuer')

    assert publisher.publish(plane)
    assert json.loads(path.read_text())['policy']['circuit_breakers'] == [
        'HDFC_BANK', 'SBI'
    ]


def test_a_quiet_agent_still_refreshes_before_the_document_expires():
    """
    Otherwise a policy that has not changed in an hour expires and every
    reader falls back to no interventions - undoing live mitigations because
    nothing happened.
    """
    path = workspace()
    plane = loaded_plane()
    publisher = PolicyPublisher(path, refresh_seconds=1)
    publisher.publish(plane)

    # Age the file past the refresh interval
    old = datetime.now().timestamp() - 10
    os.utime(path, (old, old))

    assert publisher.publish(plane), 'a heartbeat was due'


def test_a_reader_never_sees_a_half_written_document():
    """
    A truncated policy parses as an empty one, which reads as "nothing is
    wrong" and would undo every live mitigation at the worst possible moment.
    """
    path = workspace()
    plane = loaded_plane()
    publisher = PolicyPublisher(path)
    publisher.publish(plane)

    failures = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            # Windows can briefly deny a newly opened raw reader handle while
            # an atomic replacement completes. PolicyClient preserves its last
            # valid document in that case; this direct-reader check mirrors
            # that contract instead of mistaking a lock collision for a
            # malformed policy.
            for attempt in range(5):
                try:
                    document = json.loads(path.read_text())
                    if not document.get('policy'):
                        failures.append('empty policy observed')
                    break
                except OSError as exc:
                    if attempt == 4:
                        failures.append(f'unreadable: {exc}')
                    else:
                        time.sleep(0.002 * (attempt + 1))
                except ValueError as exc:
                    failures.append(f'unreadable: {exc}')
                    break

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        for i in range(200):
            plane.trip_breaker(f'BANK_{i}', author='agent', reason='churn')
            publisher.publish(plane)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert not failures, failures[:3]


def test_a_failed_write_leaves_no_debris():
    path = workspace()
    publisher = PolicyPublisher(path)

    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError('boom')

    try:
        publisher.publish(Exploding())
    except (RuntimeError, AttributeError):
        pass

    leftovers = list(path.parent.glob('.policy-*.tmp')) if path.parent.exists() else []
    assert not leftovers


# ── Reading ──────────────────────────────────────────────────────────────────

def test_a_checkout_service_can_ask_the_questions_it_has():
    path, _ = published()
    client = PolicyClient(path)
    client.refresh()

    assert client.is_broken('SBI')
    assert not client.is_broken('ICICI_BANK')
    assert client.is_suppressed('upi')
    assert client.routing_override('HDFC_BANK') == {'reduce_routing_pct': 50}
    assert client.retry_strategy('HDFC_BANK')['max_retries'] == 1
    assert client.holdout_fraction('SBI') == 0.10
    assert client.holdout_fraction('ICICI_BANK') == 0.0


def test_refresh_reports_whether_the_revision_moved():
    path = workspace()
    plane = loaded_plane()
    publisher = PolicyPublisher(path)
    publisher.publish(plane)

    client = PolicyClient(path)
    assert client.refresh(), 'the first read is a new revision'
    assert not client.refresh(), 'nothing changed'

    plane.clear_breaker('SBI', author='operator:ops@example.com', reason='recovered')
    publisher.publish(plane)

    assert client.refresh()
    assert not client.is_broken('SBI')


# ── Failure modes: the part that matters ─────────────────────────────────────

def test_a_missing_policy_is_stale_rather_than_permissive():
    client = PolicyClient(workspace())

    assert not client.refresh()
    assert client.stale
    assert client.read_errors == 1


def test_a_corrupt_document_does_not_drop_the_live_policy():
    """
    The failure that matters most. A parse error is not evidence that no
    interventions are in force, and treating it as one would resume routing to
    a dead issuer.
    """
    path, _ = published()
    client = PolicyClient(path)
    client.refresh()

    path.write_text('{"schema_version": 1, "policy": {trunca')
    os.utime(path, (datetime.now().timestamp() + 5,) * 2)

    client.refresh()

    assert client.is_broken('SBI'), 'the last good policy must stay in force'
    assert client.read_errors == 1


def test_a_policy_from_a_future_schema_is_refused_not_guessed_at():
    path, _ = published()
    client = PolicyClient(path)
    client.refresh()

    document = json.loads(path.read_text())
    document['schema_version'] = SCHEMA_VERSION + 1
    document['policy']['circuit_breakers'] = []
    path.write_text(json.dumps(document))
    os.utime(path, (datetime.now().timestamp() + 5,) * 2)

    client.refresh()

    assert client.is_broken('SBI'), 'an unreadable schema must not clear breakers'
    assert client.read_errors == 1


def test_an_expired_policy_is_flagged_but_still_applied():
    """
    Both halves matter. Applying it is right - the interventions were real and
    nothing has said otherwise. Flagging it is what gives an operator something
    to alert on when the agent has died.
    """
    path = workspace()
    publisher = PolicyPublisher(path, refresh_seconds=1)
    publisher.publish(loaded_plane())

    future = datetime.now() + timedelta(hours=1)
    client = PolicyClient(path, clock=lambda: future)
    client.refresh()

    assert client.stale
    assert client.is_broken('SBI')
    assert 'STALE' in client.describe()


def test_a_fresh_policy_is_not_flagged():
    path, _ = published()
    client = PolicyClient(path)
    client.refresh()

    assert not client.stale
    assert 'STALE' not in client.describe()


# ── End to end ───────────────────────────────────────────────────────────────

def test_an_agents_intervention_reaches_an_external_reader():
    """
    The whole point: the agent decides, and a separate process routing real
    payments behaves differently as a result.
    """
    from datetime import datetime as dt

    from src.factory import build_agent, build_simulator

    path = workspace()
    agent = build_agent(window_size_minutes=5, advisor=None)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    publisher = PolicyPublisher(path)
    client = PolicyClient(path)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=dt.now()))
        agent.run_cycle()
        publisher.publish(agent.state.control_plane)
        client.refresh()

    assert client.loaded_revision == agent.state.control_plane.revision
    assert client.routing_override('SBI') or client.is_broken('SBI'), (
        'the agent intervened on SBI; an external reader must see it'
    )
    assert not client.stale


def test_an_operator_approval_reaches_the_reader_too():
    from datetime import datetime as dt

    from src.factory import build_agent, build_simulator

    path = workspace()
    agent = build_agent(window_size_minutes=5, advisor=None)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=dt.now()))
        agent.run_cycle()

    request = agent.approvals.pending()[0]
    agent.approve(request.request_id, 'ops@example.com')

    publisher = PolicyPublisher(path)
    publisher.publish(agent.state.control_plane)

    client = PolicyClient(path)
    client.refresh()

    assert client.is_broken('SBI')
    assert client.document['author'] == 'operator:ops@example.com'
