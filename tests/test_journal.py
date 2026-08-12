"""
Decision journal.

An ops agent that forgets its interventions on restart cannot roll back what
it no longer knows it did, and an agent whose decisions cannot be replayed
cannot be evaluated - only believed. These tests hold both properties.
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.factory import build_system
from src.store.journal import NullJournal, SQLiteJournal

from conftest import make_transaction


@pytest.fixture
def journal():
    path = Path(tempfile.mkdtemp()) / "journal.db"
    return SQLiteJournal(str(path), label="test")


def run_incident(journal, cycles=5, severity=0.85):
    agent, simulator, _ = build_system(
        journal=journal,
        window_size_minutes=5,
        outcome_evaluation_seconds=0,
    )
    simulator.inject_issuer_degradation(
        'HDFC_BANK', severity=severity, duration_seconds=3600
    )
    for _ in range(cycles):
        agent.process_batch(simulator.generate_stream(count=150, start_time=datetime.now()))
        agent.run_cycle()
    return agent


def test_null_journal_accepts_everything_silently():
    """The default must never be the reason something breaks."""
    journal = NullJournal()
    journal.record_transactions([make_transaction()])
    journal.record_cycle(1, {})
    journal.record_revision(object())
    journal.close()


def test_transactions_are_persisted(journal):
    run_incident(journal, cycles=2)
    assert len(journal.transactions(limit=100000)) == 300


def test_replaying_the_same_transaction_is_not_an_error(journal):
    transaction = make_transaction()
    journal.record_transactions([transaction])
    journal.record_transactions([transaction])

    assert len(journal.transactions(limit=10)) == 1


def test_cycles_patterns_and_actions_are_persisted(journal):
    run_incident(journal)

    assert len(journal.query("SELECT * FROM cycles")) == 5
    assert len(journal.query("SELECT * FROM patterns")) > 0
    assert len(journal.actions()) > 0


def test_control_plane_revisions_are_persisted(journal):
    run_incident(journal)

    revisions = journal.revisions()
    assert len(revisions) > 0
    # Every revision carries who made it and why
    for revision in revisions:
        assert revision['author']
        assert revision['reason']


def test_open_interventions_survive_a_restart(journal):
    """
    The restart-safety property: after a crash the agent can find what it left
    running instead of losing track of live changes to payment routing.
    """
    agent = run_incident(journal)
    assert agent.executor.get_active_interventions()

    open_rows = journal.open_interventions()

    assert open_rows
    live_targets = {
        (a.action_type.value, a.target)
        for a in agent.executor.get_active_interventions()
    }
    recorded = {(row['action_type'], row['target']) for row in open_rows}
    assert recorded == live_targets


def test_completed_interventions_are_not_reported_as_open(journal):
    from datetime import timedelta

    agent = run_incident(journal)
    active = agent.executor.get_active_interventions()
    assert active

    # Age every intervention past its planned duration, then retire them
    for action in active:
        action.executed_at = datetime.now() - timedelta(hours=2)
    agent.executor.monitor_and_rollback(agent.state, agent.observer)

    # Re-record the now-completed actions
    for action in agent.memory.action_history:
        journal.record_action(action)

    assert journal.open_interventions() == []


def test_outcomes_are_persisted_with_their_action(journal):
    run_incident(journal)

    outcomes = journal.query("SELECT * FROM outcomes")
    assert outcomes

    action_ids = {row['action_id'] for row in journal.actions()}
    for outcome in outcomes:
        assert outcome['action_id'] in action_ids


def test_effectiveness_query_groups_by_action_type(journal):
    run_incident(journal)

    rows = journal.effectiveness_by_action_type()
    assert rows
    for row in rows:
        assert row['samples'] >= 1


def test_journal_reopens_and_keeps_previous_runs(journal):
    run_incident(journal, cycles=2)
    path = journal.path
    first_run = journal.run_id
    journal.close()

    reopened = SQLiteJournal(str(path), label="second")
    try:
        run_ids = {row['run_id'] for row in reopened.runs()}
        assert first_run in run_ids
        assert reopened.run_id in run_ids
        # Data from the earlier run is still queryable
        assert len(reopened.transactions(run_id=first_run, limit=100000)) == 300
    finally:
        reopened.close()


def test_agent_works_without_a_journal():
    agent, simulator, _ = build_system(window_size_minutes=5)
    agent.process_batch(simulator.generate_stream(count=50, start_time=datetime.now()))
    result = agent.run_cycle()
    assert 'error' not in result
