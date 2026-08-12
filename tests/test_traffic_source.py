"""
Traffic sources.

The agent consumes one interface regardless of where transactions come from,
so swapping synthetic traffic for a recording - or later, a real gateway
sandbox - does not touch the agent loop.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.factory import build_system
from src.models.state import PaymentStatus
from src.store.journal import SQLiteJournal
from src.traffic import JournalReplaySource, SimulatedTrafficSource, TrafficSource


@pytest.fixture
def journal():
    path = Path(tempfile.mkdtemp()) / "journal.db"
    return SQLiteJournal(str(path), label="replay-test")


def record_incident(journal, cycles=4):
    agent, simulator, _ = build_system(
        journal=journal, window_size_minutes=5, outcome_evaluation_seconds=0
    )
    simulator.inject_issuer_degradation('HDFC_BANK', severity=0.85, duration_seconds=3600)
    for _ in range(cycles):
        agent.process_batch(simulator.generate_stream(count=200, start_time=datetime.now()))
        agent.run_cycle()
    return agent


def test_simulated_source_satisfies_the_protocol():
    _agent, simulator, _ = build_system()
    source = SimulatedTrafficSource(simulator)

    assert isinstance(source, TrafficSource)
    assert len(source.next_batch(25)) == 25
    assert 'simulated' in source.describe()


def test_replay_source_satisfies_the_protocol(journal):
    record_incident(journal, cycles=1)
    source = JournalReplaySource(journal)

    assert isinstance(source, TrafficSource)
    assert 'replay' in source.describe()


def test_replay_returns_the_recorded_transactions(journal):
    record_incident(journal, cycles=2)
    recorded = journal.transactions(limit=100000)

    source = JournalReplaySource(journal)
    replayed = []
    for batch in source.replay_all(batch_size=150):
        replayed.extend(batch)

    assert len(replayed) == len(recorded)
    assert {t.transaction_id for t in replayed} == {r['transaction_id'] for r in recorded}


def test_replay_preserves_outcomes_exactly(journal):
    """A replay that changed the data would measure nothing useful."""
    record_incident(journal, cycles=2)
    recorded = {r['transaction_id']: r for r in journal.transactions(limit=100000)}

    source = JournalReplaySource(journal)
    for batch in source.replay_all():
        for transaction in batch:
            original = recorded[transaction.transaction_id]
            assert transaction.status.value == original['status']
            assert transaction.issuer == original['issuer']
            assert transaction.error_code == original['error_code']
            assert transaction.latency_ms == original['latency_ms']


def test_replay_rebases_timestamps_into_the_window(journal):
    """
    The observer's window is relative to now, so replaying original timestamps
    would place every transaction outside it and the agent would see nothing.
    """
    record_incident(journal, cycles=1)

    source = JournalReplaySource(journal, rebase_time=True)
    batch = source.next_batch(50)

    age = datetime.now() - min(t.timestamp for t in batch)
    assert age < timedelta(minutes=5)


def test_replay_can_preserve_original_timestamps(journal):
    record_incident(journal, cycles=1)
    recorded = journal.transactions(limit=10)

    source = JournalReplaySource(journal, rebase_time=False)
    batch = source.next_batch(10)

    assert batch[0].timestamp == datetime.fromisoformat(recorded[0]['timestamp'])


def test_replay_tracks_progress(journal):
    record_incident(journal, cycles=1)
    total = len(journal.transactions(limit=100000))

    source = JournalReplaySource(journal)
    assert source.remaining == total
    assert not source.exhausted

    source.next_batch(total)
    assert source.exhausted
    assert source.remaining == 0
    assert source.next_batch(10) == []


def test_agent_can_be_driven_from_a_replay(journal):
    """
    The evaluation payoff: a recorded incident re-run against the agent
    produces the same detections, rather than a fresh random draw where any
    difference could be noise.
    """
    record_incident(journal, cycles=3)

    replay_agent, _simulator, _ = build_system(window_size_minutes=5)
    source = JournalReplaySource(journal)

    patterns = 0
    for batch in source.replay_all(batch_size=200):
        replay_agent.process_batch(batch)
        result = replay_agent.run_cycle()
        patterns += len(result['patterns_detected'])

    assert patterns > 0
    assert replay_agent.state.total_transactions > 0


def test_replay_is_deterministic(journal):
    """Two replays of one recording must agree, or evaluation is meaningless."""
    record_incident(journal, cycles=2)

    def detections():
        agent, _simulator, _ = build_system(window_size_minutes=5)
        source = JournalReplaySource(journal, rebase_time=False)
        found = []
        for batch in source.replay_all(batch_size=200):
            agent.process_batch(batch)
            result = agent.run_cycle()
            found.extend(sorted(p['type'] for p in result['patterns_detected']))
        return found

    assert detections() == detections()
