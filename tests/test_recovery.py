"""
Restart safety.

The journal has carried a method called `open_interventions` for several
releases, documented as "what makes restart safe". Nothing called it, and its
default scoped the query to the *current* run - which at startup is empty by
definition, so it would have found nothing even if something had.

The consequence is the worst kind of quiet failure. A circuit breaker the agent
opened is still being obeyed by whatever routes payments, but the restarted
agent has never heard of it, so nothing will ever expire it or roll it back.
The issuer recovers and the breaker stays shut, indefinitely, with no incident
open and nothing on the console to explain why that bank gets no traffic.
"""

import tempfile
from datetime import datetime
from pathlib import Path

from src.control.plane import ControlPlane, ControlPlaneRevision
from src.factory import build_agent, build_simulator
from src.store.journal import NullJournal, SQLiteJournal


def journal_path():
    return str(Path(tempfile.mkdtemp()) / 'journal.db')


def run_until_breaker(path, label='before'):
    """Drive an agent until an operator has approved a circuit breaker."""
    journal = SQLiteJournal(path, label=label)
    agent = build_agent(window_size_minutes=5, advisor=None, journal=journal)
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(
            simulator.generate_stream(count=300, start_time=datetime.now())
        )
        agent.run_cycle()

    agent.approve(agent.approvals.pending()[0].request_id, 'ops@example.com')
    return agent, journal


# ── The regression ───────────────────────────────────────────────────────────

def test_a_breaker_survives_the_process_that_opened_it():
    """
    The bug in one line: before this, `breakers` below was an empty set while
    SBI was still being refused traffic by the published policy.
    """
    path = journal_path()
    before, journal = run_until_breaker(path)
    assert 'SBI' in before.state.active_circuit_breakers
    journal.close()

    after = build_agent(
        window_size_minutes=5, advisor=None,
        journal=SQLiteJournal(path, label='after'),
    )

    assert 'SBI' in after.state.active_circuit_breakers, (
        'the restarted agent must know about the breaker it is responsible for'
    )


def test_the_restarted_agent_can_end_what_it_inherited():
    """
    Knowing about it is only half. The whole point of recovering the policy is
    that this agent can now lift it - otherwise the breaker is visible and
    still permanent.
    """
    path = journal_path()
    _before, journal = run_until_breaker(path)
    journal.close()

    after = build_agent(
        window_size_minutes=5, advisor=None,
        journal=SQLiteJournal(path, label='after'),
    )
    after.state.control_plane.clear_breaker(
        'SBI', author='operator:ops@example.com', reason='issuer recovered'
    )

    assert 'SBI' not in after.state.active_circuit_breakers


def test_open_interventions_are_reported_to_the_new_agent():
    path = journal_path()
    _before, journal = run_until_breaker(path)
    journal.close()

    after = build_agent(
        window_size_minutes=5, advisor=None,
        journal=SQLiteJournal(path, label='after'),
    )

    assert after.recovered, 'interventions left running must be surfaced'
    assert all('action_type' in row for row in after.recovered)


def test_open_interventions_span_runs_rather_than_the_current_one():
    """
    The specific defect behind the silence: the query defaulted to the current
    run, which at startup has no history at all.
    """
    path = journal_path()
    _before, journal = run_until_breaker(path)
    journal.close()

    fresh = SQLiteJournal(path, label='after')
    try:
        assert fresh.open_interventions(), 'must look beyond the run just started'
        assert fresh.open_interventions(run_id=fresh.run_id) == [], (
            'an explicit run id still scopes to that run'
        )
    finally:
        fresh.close()


# ── Attribution ──────────────────────────────────────────────────────────────

def test_an_adopted_policy_is_recorded_as_adopted_not_decided():
    """
    The restarted agent did not decide to break SBI; it inherited the decision.
    Filing it as this agent's own would attribute a choice to something that
    never made it.
    """
    path = journal_path()
    _before, journal = run_until_breaker(path)
    journal.close()

    after = build_agent(
        window_size_minutes=5, advisor=None,
        journal=SQLiteJournal(path, label='after'),
    )
    revision = after.state.control_plane.current

    assert revision.author == 'system:recovery'
    assert 'recovered after restart' in revision.reason
    assert 'operator:ops@example.com' in revision.reason, (
        'the original decision-maker must survive the handover'
    )


def test_recovery_publishes_a_new_revision_rather_than_rewinding():
    """
    The log is append-only. Restoring the counter to r3 would claim this agent
    published revisions it never saw, and leave the adopted revision with no
    parent to diff a rollback against.
    """
    path = journal_path()
    _before, journal = run_until_breaker(path)
    journal.close()

    after = build_agent(
        window_size_minutes=5, advisor=None,
        journal=SQLiteJournal(path, label='after'),
    )

    history = after.state.control_plane.history()
    assert len(history) == 2, 'an initial empty policy, then the adoption'
    assert after.state.control_plane.current.parent_revision == 0


# ── Not overreaching ─────────────────────────────────────────────────────────

def test_a_clean_start_recovers_nothing():
    agent = build_agent(
        window_size_minutes=5, advisor=None, journal=SQLiteJournal(journal_path())
    )

    assert agent.recovered == []
    assert agent.state.control_plane.current.is_empty()
    assert agent.state.control_plane.revision == 0


def test_an_agent_without_a_journal_does_not_try_to_recover():
    """
    The default. Recovery is a property of a deployment with durable state,
    not of what a PaymentAgent is.
    """
    agent = build_agent(window_size_minutes=5, advisor=None)

    assert isinstance(agent.journal, NullJournal)
    assert agent.recovered == []
    assert agent.state.control_plane.revision == 0


def test_recovering_an_empty_policy_publishes_nothing():
    """A previous run that never intervened leaves nothing to adopt."""
    path = journal_path()
    first = SQLiteJournal(path, label='quiet')
    build_agent(window_size_minutes=5, advisor=None, journal=first)
    first.close()

    after = build_agent(
        window_size_minutes=5, advisor=None, journal=SQLiteJournal(path, label='after')
    )

    assert after.state.control_plane.revision == 0


def test_recovery_is_idempotent():
    path = journal_path()
    _before, journal = run_until_breaker(path)
    journal.close()

    after = build_agent(
        window_size_minutes=5, advisor=None,
        journal=SQLiteJournal(path, label='after'),
    )
    revision = after.state.control_plane.revision

    after.recover()

    assert after.state.control_plane.revision == revision, (
        'adopting an identical policy must not churn the log'
    )


# ── Serialisation round-trip ─────────────────────────────────────────────────

def test_a_revision_survives_a_round_trip():
    """
    An agent that cannot read back what it published has no way to learn what
    it left in force.
    """
    plane = ControlPlane()
    plane.trip_breaker('SBI', author='agent', reason='down')
    plane.suppress_method('upi', author='agent', reason='fatigue')
    plane.set_routing_override(
        'HDFC_BANK', {'reduce_routing_pct': 50}, author='agent', reason='degraded'
    )
    plane.set_retry_strategy(
        'HDFC_BANK', {'max_retries': 1}, author='agent', reason='storm'
    )
    original = plane.set_holdout('SBI', 0.1, author='agent', reason='measure')

    restored = ControlPlaneRevision.from_dict(original.to_dict())

    assert restored.circuit_breakers == original.circuit_breakers
    assert restored.suppressed_methods == original.suppressed_methods
    assert restored.routing_overrides == original.routing_overrides
    assert restored.retry_strategies == original.retry_strategies
    assert restored.holdouts == original.holdouts
    assert restored.author == original.author
    assert restored.revision == original.revision


def test_last_revision_is_the_latest_run_not_the_highest_number():
    """
    Revision numbers restart at zero with each run, so the highest number is
    whichever run lived longest - not the policy currently in force.
    """
    path = journal_path()

    long_run = SQLiteJournal(path, label='long')
    plane = ControlPlane(journal=long_run)
    for i in range(5):
        plane.trip_breaker(f'BANK_{i}', author='agent', reason='churn')
    long_run.close()

    short_run = SQLiteJournal(path, label='short')
    later = ControlPlane(journal=short_run)
    later.trip_breaker('ONLY_THIS_ONE', author='agent', reason='the current policy')

    recorded = short_run.last_revision()
    short_run.close()

    assert recorded['circuit_breakers'] == ['ONLY_THIS_ONE'], recorded


def test_a_null_journal_answers_recovery_reads():
    """So nothing in the agent has to branch on which journal it holds."""
    journal = NullJournal()

    assert journal.open_interventions() == []
    assert journal.last_revision() is None
