"""
Control plane semantics.

The agent's only output is a versioned policy document. These tests pin down
the properties the rest of the system relies on: revisions are immutable and
append-only, every change is attributed, and undoing one intervention does not
disturb another that happens to be running at the same time.
"""

import pytest

from src.control.plane import ControlPlane, diff


def test_starts_at_an_empty_revision_zero():
    cp = ControlPlane()
    assert cp.revision == 0
    assert cp.current.is_empty()


def test_each_change_appends_a_revision():
    cp = ControlPlane()

    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')
    cp.suppress_method('upi', author='operator:alice', reason='fraud spike')

    assert cp.revision == 2
    assert cp.current.circuit_breakers == frozenset({'HDFC_BANK'})
    assert cp.current.suppressed_methods == frozenset({'upi'})


def test_revisions_are_immutable():
    cp = ControlPlane()
    first = cp.current
    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')

    # The earlier revision is unchanged by the later one
    assert first.circuit_breakers == frozenset()
    with pytest.raises(Exception):
        first.circuit_breakers = frozenset({'X'})


def test_change_records_attribution():
    cp = ControlPlane()
    revision = cp.trip_breaker(
        'HDFC_BANK', author='operator:alice', reason='manual override', action_id='act-1'
    )

    assert revision.author == 'operator:alice'
    assert revision.reason == 'manual override'
    assert revision.action_id == 'act-1'
    assert revision.parent_revision == 0


def test_noop_change_does_not_create_a_revision():
    """Otherwise the log fills with noise and diffs stop being useful."""
    cp = ControlPlane()
    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')
    before = cp.revision

    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded again')

    assert cp.revision == before


def test_undo_removes_only_that_revisions_effect():
    """
    The property that makes derived undo worth having: two interventions are
    in force, one is withdrawn, and the other is untouched.
    """
    cp = ControlPlane()
    breaker = cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')
    cp.suppress_method('upi', author='operator:alice', reason='fraud spike')

    cp.undo_revision(breaker.revision, author='agent', reason='recovered')

    assert cp.current.circuit_breakers == frozenset()
    assert cp.current.suppressed_methods == frozenset({'upi'})


def test_undo_restores_a_previous_value_rather_than_deleting():
    cp = ControlPlane()
    cp.set_retry_strategy(
        'global_retry_strategy', {'max_retries': 3}, author='config', reason='baseline'
    )
    tightened = cp.set_retry_strategy(
        'global_retry_strategy', {'max_retries': 1}, author='agent', reason='retry storm'
    )

    cp.undo_revision(tightened.revision, author='agent', reason='storm over')

    # Back to the baseline policy, not to no policy at all
    assert cp.current.retry_strategies['global_retry_strategy']['max_retries'] == 3


def test_undo_of_a_map_change_leaves_other_targets_alone():
    cp = ControlPlane()
    hdfc = cp.set_routing_override(
        'HDFC_BANK', {'reduce_routing_pct': 50}, author='agent', reason='degraded'
    )
    cp.set_routing_override(
        'SBI', {'reduce_routing_pct': 20}, author='agent', reason='slow'
    )

    cp.undo_revision(hdfc.revision, author='agent', reason='recovered')

    assert 'HDFC_BANK' not in cp.current.routing_overrides
    assert cp.current.routing_overrides['SBI']['reduce_routing_pct'] == 20


def test_revert_to_appends_rather_than_rewriting_history():
    cp = ControlPlane()
    clean = cp.revision
    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')
    cp.suppress_method('upi', author='agent', reason='fatigue')

    reverted = cp.revert_to(clean, author='operator:alice', reason='panic button')

    assert cp.current.is_empty()
    # History is preserved: revision 0 (empty), 1 (breaker), 2 (suppress),
    # 3 (the revert). The interventions stay on record.
    assert reverted.revision == 3
    assert len(cp.history()) == 4
    assert cp.get(1).circuit_breakers == frozenset({'HDFC_BANK'})
    assert cp.get(2).suppressed_methods == frozenset({'upi'})


def test_revert_to_unknown_revision_raises():
    cp = ControlPlane()
    with pytest.raises(KeyError):
        cp.revert_to(99, author='agent', reason='nope')


def test_journal_receives_every_revision():
    recorded = []

    class Journal:
        def record_revision(self, revision):
            recorded.append(revision)

    cp = ControlPlane(journal=Journal())
    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')
    cp.clear_breaker('HDFC_BANK', author='agent', reason='recovered')

    assert [r.revision for r in recorded] == [1, 2]


def test_subscribers_are_notified():
    seen = []
    cp = ControlPlane()
    cp.subscribe(seen.append)

    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')

    assert len(seen) == 1


def test_diff_describes_the_change_in_words():
    cp = ControlPlane()
    before = cp.current
    cp.trip_breaker('HDFC_BANK', author='agent', reason='degraded')
    cp.set_routing_override(
        'SBI', {'reduce_routing_pct': 50}, author='agent', reason='slow'
    )

    lines = diff(before, cp.current)

    assert '+ circuit breaker: HDFC_BANK' in lines
    assert any('routing override: SBI' in line for line in lines)


def test_diff_reports_modifications():
    cp = ControlPlane()
    first = cp.set_retry_strategy(
        'global_retry_strategy', {'max_retries': 3}, author='config', reason='baseline'
    )
    second = cp.set_retry_strategy(
        'global_retry_strategy', {'max_retries': 1}, author='agent', reason='storm'
    )

    lines = diff(first, second)
    assert any(line.startswith('~ retry strategy') for line in lines)


def test_stored_revision_is_not_aliased_to_caller_data():
    cp = ControlPlane()
    override = {'reduce_routing_pct': 50}
    cp.set_routing_override('HDFC_BANK', override, author='agent', reason='degraded')

    override['reduce_routing_pct'] = 100

    assert cp.current.routing_overrides['HDFC_BANK']['reduce_routing_pct'] == 50
