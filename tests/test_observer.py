"""
Observer windowing.

Every counter the observer exposes has to describe the current window. A
counter that only increments turns into a permanent false positive as soon as
the window moves past the events that caused it.
"""

from src.agent.observer import PaymentObserver
from src.models.state import PaymentStatus

from conftest import make_transaction


def test_counters_match_window_after_eviction():
    observer = PaymentObserver(window_size_minutes=1)

    # 50 old failures that should all age out, then one fresh failure
    for _ in range(50):
        observer.ingest_transaction(
            make_transaction(
                status=PaymentStatus.FAILED,
                error_code="ISSUER_DOWN",
                age_seconds=1800,
            )
        )
    observer.ingest_transaction(
        make_transaction(status=PaymentStatus.FAILED, error_code="ISSUER_DOWN")
    )

    assert len(observer.transactions_window) == 1
    assert observer.stats['overall']['current']['total'] == 1
    assert observer.stats['by_issuer']['HDFC_BANK']['total'] == 1
    # The regression: this used to report 51
    assert sum(observer.error_codes.values()) == 1


def test_retry_stats_are_windowed():
    observer = PaymentObserver(window_size_minutes=1)

    for i in range(20):
        observer.ingest_transaction(
            make_transaction(is_retry=True, age_seconds=1800, transaction_id=f"old-{i}")
        )
    observer.ingest_transaction(make_transaction(is_retry=True))

    assert len(observer.transactions_window) == 1
    total_attempts = sum(s['attempted'] for s in observer.retry_stats.values())
    assert total_attempts == 1


def test_error_cluster_rate_cannot_exceed_one():
    """
    The leak produced error rates like 16100% because a lifetime error count
    was divided by a windowed transaction volume.
    """
    observer = PaymentObserver(window_size_minutes=1)

    for _ in range(100):
        observer.ingest_transaction(
            make_transaction(
                status=PaymentStatus.FAILED, error_code="TIMEOUT", age_seconds=1800
            )
        )
    for _ in range(10):
        observer.ingest_transaction(make_transaction(status=PaymentStatus.SUCCESS))

    volume = observer.get_transaction_volume('overall', 'current')
    for _code, count in observer.get_top_errors():
        assert count <= volume


def test_latency_stats_track_the_window():
    observer = PaymentObserver(window_size_minutes=1)

    for _ in range(10):
        observer.ingest_transaction(make_transaction(latency_ms=5000.0, age_seconds=1800))
    for _ in range(5):
        observer.ingest_transaction(make_transaction(latency_ms=100.0))

    stats = observer.get_latency_stats('overall')
    # Evicted 5000ms samples must not drag the current window's mean up
    assert stats['mean'] == 100.0
    assert stats['max'] == 100.0


def test_success_rate_reflects_only_current_window():
    observer = PaymentObserver(window_size_minutes=1)

    for _ in range(20):
        observer.ingest_transaction(
            make_transaction(status=PaymentStatus.FAILED, age_seconds=1800)
        )
    for _ in range(4):
        observer.ingest_transaction(make_transaction(status=PaymentStatus.SUCCESS))

    assert observer.get_success_rate('overall', 'current') == 1.0


# ── Timezone-aware sources ───────────────────────────────────────────────────
#
# The window is arithmetic against datetime.now(), which is naive local time.
# Every real payment gateway reports UTC-aware timestamps, so the first
# transaction from one used to raise TypeError several frames deep in window
# eviction - which meant "a real PSP adapter fits this interface without the
# agent changing" was not true until it was tested.

def test_an_aware_timestamp_does_not_break_window_eviction():
    from datetime import datetime, timezone

    observer = PaymentObserver(window_size_minutes=10)
    transaction = make_transaction()
    transaction.timestamp = datetime.now(timezone.utc)

    observer.ingest_transaction(transaction)  # used to raise TypeError

    assert observer.get_summary()['total_transactions'] == 1


def test_aware_and_naive_transactions_can_share_a_window():
    """Mixed sources are the realistic case: a gateway alongside a replay."""
    from datetime import datetime, timezone

    observer = PaymentObserver(window_size_minutes=10)

    aware = make_transaction()
    aware.timestamp = datetime.now(timezone.utc)
    observer.ingest_transaction(aware)
    observer.ingest_transaction(make_transaction())

    assert observer.get_summary()['total_transactions'] == 2


def test_an_aware_timestamp_is_converted_rather_than_stripped():
    """
    Dropping the offset would be worse than the crash it replaces: the
    transaction would be filed hours out of place and the window would quietly
    hold the wrong rows instead of raising.
    """
    from datetime import datetime, timedelta, timezone

    from src.agent.observer import to_local_naive

    instant = datetime.now(timezone.utc)
    india = instant.astimezone(timezone(timedelta(hours=5, minutes=30)))
    utc = instant.astimezone(timezone.utc)

    # Same instant, two offsets - both must land on the same local time
    assert to_local_naive(india) == to_local_naive(utc)
    assert abs((to_local_naive(utc) - datetime.now()).total_seconds()) < 5


def test_a_naive_timestamp_is_left_alone():
    from datetime import datetime

    from src.agent.observer import to_local_naive

    naive = datetime(2026, 6, 1, 12, 0)
    assert to_local_naive(naive) is naive
