"""
Read models.

The API serves these pure functions through the shared runtime. The model is
tested without an HTTP server so a presentation change cannot silently alter
the payment-recovery data contract.
"""

from datetime import datetime

from src import views
from src.factory import build_agent, build_simulator


def running_agent(cycles=4, degrade='SBI'):
    agent = build_agent(window_size_minutes=5, advisor=None)
    simulator = build_simulator(control_plane=agent.state)
    if degrade:
        simulator.inject_issuer_degradation(degrade, severity=0.85, duration_seconds=3600)

    for _ in range(cycles):
        agent.process_batch(
            simulator.generate_stream(count=300, start_time=datetime.now())
        )
        agent.run_cycle()

    return agent, simulator


# ── The document ─────────────────────────────────────────────────────────────

def test_snapshot_carries_every_section_a_client_renders():
    agent, simulator = running_agent()

    snapshot = views.snapshot(agent, simulator)

    for section in (
        'agent', 'metrics', 'counters', 'issuers', 'incidents', 'approvals',
        'experiments', 'interventions', 'control_plane', 'decisions',
        'scenarios', 'history', 'events', 'traffic', 'recovered',
    ):
        assert section in snapshot, f'missing {section}'


def test_snapshot_is_json_serialisable():
    """It is served over HTTP; a datetime that escapes is a 500 at runtime."""
    import json

    agent, simulator = running_agent()

    json.dumps(views.snapshot(agent, simulator))  # no default= fallback


def test_snapshot_keeps_its_shape_without_a_simulator():
    """
    Against a real processor there is no simulator and no injected scenarios.
    The keys stay present so a client never has to branch on which world it is
    looking at.
    """
    agent, _ = running_agent()

    snapshot = views.snapshot(agent)

    assert snapshot['scenarios'] == []
    assert snapshot['traffic'] == {}


# ── Individual read models ───────────────────────────────────────────────────

def test_issuers_are_ordered_worst_first():
    agent, _ = running_agent()

    rows = views.issuers(agent)

    assert rows
    assert rows == sorted(rows, key=lambda r: r['success_rate'])


def test_a_broken_issuer_is_marked_as_broken():
    agent, _ = running_agent()
    agent.state.control_plane.trip_breaker('SBI', author='test', reason='test')

    rows = {r['issuer']: r for r in views.issuers(agent)}

    assert rows['SBI']['broken']
    assert not rows['HDFC_BANK']['broken']


def test_plane_history_says_what_changed_not_just_that_something_did():
    """
    Every revision in the audit trail has to explain itself. A holdout used to
    produce an empty diff - the one change that most needs explaining, since it
    knowingly leaves real payments unprotected, arriving in the log as a blank.
    """
    agent, _ = running_agent()

    entries = views.plane_history(agent.state.control_plane)

    assert entries
    assert all(e['changes'] for e in entries), (
        'a revision with no diff is unreadable: '
        + str([e['reason'] for e in entries if not e['changes']])
    )
    assert all(e['author'] for e in entries)


def test_a_holdout_is_visible_in_the_audit_trail():
    from src.control.plane import ControlPlane, diff

    plane = ControlPlane()
    before = plane.current
    after = plane.set_holdout('SBI', 0.10, author='agent', reason='measure the fix')

    changes = diff(before, after)

    assert changes, 'a holdout must not enter the audit trail as a blank'
    assert '10%' in changes[0]
    assert 'SBI' in changes[0]


def test_removing_and_resizing_a_holdout_are_both_reported():
    from src.control.plane import ControlPlane, diff

    plane = ControlPlane()
    plane.set_holdout('SBI', 0.10, author='agent', reason='start')

    resized = plane.set_holdout('SBI', 0.25, author='agent', reason='widen')
    assert diff(plane.get(resized.parent_revision), resized) == [
        '~ holdout: SBI = 10% -> 25%'
    ]

    cleared = plane.clear_holdout('SBI', author='agent', reason='experiment settled')
    assert diff(plane.get(cleared.parent_revision), cleared) == ['- holdout: SBI']


def test_decisions_exclude_alerts_before_applying_the_limit():
    """
    Alerts outnumber interventions roughly fifty to one on a busy incident.
    Taking the last N entries and filtering afterwards left the view empty.
    """
    agent, _ = running_agent()
    for i in range(300):
        agent.executor.execution_log.append({
            'action_id': str(i), 'action_type': 'alert_ops', 'target': 'X',
            'executed_at': 't', 'success': True, 'message': '',
            'parameters': {}, 'reasoning': '',
        })

    rows = views.decisions(agent, limit=10)

    assert rows, 'interventions must survive a flood of alerts'
    assert all(r['type'] != 'alert_ops' for r in rows)


def test_decisions_are_newest_first():
    agent, _ = running_agent(cycles=6)

    rows = views.decisions(agent)
    if len(rows) < 2:
        return  # nothing to order

    raw = agent.executor.get_execution_history(
        limit=12, exclude_types=('alert_ops', 'no_action')
    )
    assert rows[0]['action_id'] == raw[-1]['action_id']


def test_phase_reports_what_the_agent_is_doing():
    quiet, _ = running_agent(cycles=1, degrade=None)
    assert views.phase(quiet) == 'observing'

    busy, _ = running_agent()
    assert views.phase(busy) in ('mitigating', 'monitoring')


# ── Health ───────────────────────────────────────────────────────────────────

def test_health_reports_degraded_when_the_loop_has_stopped():
    """
    Serving a page is not the same as running the agent. A container whose
    cycle thread has died must not keep passing its own health check.
    """
    agent, _ = running_agent(cycles=1, degrade=None)

    assert views.health(agent, loop_running=True)['status'] == 'ok'
    assert views.health(agent, loop_running=False)['status'] == 'degraded'


def test_health_reports_whether_the_advisor_is_wired():
    agent, _ = running_agent(cycles=1, degrade=None)

    assert views.health(agent)['advisor'] is False

    agent.advisor = lambda _ctx: 'noted'
    assert views.health(agent)['advisor'] is True


# ── Runtime boundary ─────────────────────────────────────────────────────────

def test_runtime_uses_the_shared_read_model():
    import inspect

    from src.runtime import AgentRuntime

    source = inspect.getsource(AgentRuntime.snapshot)
    assert 'views.snapshot' in source


# ── Inherited interventions ──────────────────────────────────────────────────

def test_the_snapshot_surfaces_what_the_agent_inherited():
    """
    An adopted circuit breaker has no incident behind it and nothing in the
    decision trace. Without its own place in the view it is a live change to
    payment routing that the page cannot explain - which is how one survived a
    restart unnoticed.
    """
    agent, _ = running_agent(cycles=1, degrade=None)
    agent.recovered = [{
        'action_id': 'act-1', 'action_type': 'circuit_breaker', 'target': 'SBI',
        'executed_at': '2026-08-12T05:00:00', 'approver': 'ops@example.com',
    }]

    rows = views.snapshot(agent)['recovered']

    assert rows == [{
        'action_id': 'act-1', 'type': 'circuit_breaker', 'target': 'SBI',
        'executed_at': '2026-08-12T05:00:00', 'approver': 'ops@example.com',
    }]


def test_a_clean_start_shows_nothing_inherited():
    agent, _ = running_agent(cycles=1, degrade=None)

    assert views.snapshot(agent)['recovered'] == []
