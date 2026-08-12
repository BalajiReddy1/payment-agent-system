"""
Traffic sources.

Where the agent's transactions come from. The agent consumes this interface
and nothing else, so the question "is this traffic simulated or real?" is
answered in exactly one place instead of being baked into the agent loop.

Three implementations are useful:

- PaymentSimulator (src/simulation) - parameterised synthetic traffic that
  obeys the control plane. The default.
- JournalReplaySource - replays transactions recorded by a previous run, so a
  past incident can be re-run against changed agent code. This is what turns
  "the agent handled it well" from an assertion into a measurement.
- PaymentGatewaySource (src/traffic/gateway.py) - a real PSP, Razorpay or
  Stripe, producing genuine decline codes and issuer attribution.

This docstring used to say a gateway adapter "fits this interface without the
agent changing", as an untested claim. Building it found the one place that was
false: every real gateway reports UTC-aware timestamps and the observer's
window is naive local time, so the first real transaction raised TypeError deep
inside window eviction. The fix is in PaymentObserver.ingest_transaction, and
the lesson is in `signals()` below.

A note on honesty: synthetic traffic is not a weakness of this design as long
as the *control plane* is real. What makes the loop meaningful is that the
agent's decisions change what happens next, not where the bytes came from - and
src/control/publish.py is what lets a system outside this process read those
decisions and act on them.

A second note, on what a source cannot do. Sources differ in which signals they
can supply: the simulator has every field, a gateway's list-payments API has no
latency at all. A source reports this through `signals()` rather than filling
the gap with a plausible number, because a fabricated latency is
indistinguishable from a real one downstream - the agent would detect, act on,
and then measure improvements in noise it generated itself.
"""

from datetime import datetime
from typing import Iterator, List, Optional, Protocol, runtime_checkable

from src.models.state import PaymentStatus, PaymentTransaction


@runtime_checkable
class TrafficSource(Protocol):
    """A source of payment transactions for the agent to observe."""

    def next_batch(self, count: int) -> List[PaymentTransaction]:
        """Produce (or fetch) the next `count` transactions."""
        ...

    def describe(self) -> str:
        """Human-readable identification, for logs and the dashboard."""
        ...


class SimulatedTrafficSource:
    """
    Adapts PaymentSimulator to the TrafficSource interface.

    Kept as a thin wrapper rather than changing the simulator's own API, so
    existing callers and tests continue to work.
    """

    def __init__(self, simulator):
        self.simulator = simulator

    def next_batch(self, count: int) -> List[PaymentTransaction]:
        self.simulator.cleanup_expired_scenarios()
        return self.simulator.generate_stream(count=count, start_time=datetime.now())

    def describe(self) -> str:
        active = len(self.simulator.active_scenarios())
        return f"simulated traffic ({active} scenario(s) active)"


class JournalReplaySource:
    """
    Replays transactions recorded by an earlier run.

    The point is evaluation. Re-running a recorded incident against modified
    detection thresholds or a changed decision policy shows whether the change
    actually helps, instead of relying on a fresh random draw where any
    difference could be noise.

    Timestamps are rebased onto the present by default: the observer works on a
    sliding window relative to now, so replaying original timestamps would put
    every transaction outside the window and the agent would see nothing.
    """

    def __init__(self, journal, run_id: Optional[str] = None, rebase_time: bool = True):
        self.journal = journal
        self.run_id = run_id
        self.rebase_time = rebase_time

        self._rows = list(journal.transactions(run_id=run_id, limit=10_000_000))
        self._position = 0
        self._offset = None

        if self._rows and rebase_time:
            first = datetime.fromisoformat(self._rows[0]['timestamp'])
            self._offset = datetime.now() - first

    @property
    def exhausted(self) -> bool:
        return self._position >= len(self._rows)

    @property
    def remaining(self) -> int:
        return max(0, len(self._rows) - self._position)

    def next_batch(self, count: int) -> List[PaymentTransaction]:
        rows = self._rows[self._position:self._position + count]
        self._position += len(rows)
        return [self._to_transaction(row) for row in rows]

    def replay_all(self, batch_size: int = 250) -> Iterator[List[PaymentTransaction]]:
        """Yield the whole recording in batches."""
        while not self.exhausted:
            yield self.next_batch(batch_size)

    def describe(self) -> str:
        return (
            f"journal replay ({len(self._rows)} transactions"
            f"{f', run {self.run_id[:8]}' if self.run_id else ''})"
        )

    def _to_transaction(self, row) -> PaymentTransaction:
        from src.models.state import PaymentMethod

        timestamp = datetime.fromisoformat(row['timestamp'])
        if self._offset is not None:
            timestamp = timestamp + self._offset

        return PaymentTransaction(
            transaction_id=row['transaction_id'],
            timestamp=timestamp,
            amount=row['amount'],
            currency=row['currency'],
            payment_method=PaymentMethod(row['payment_method']),
            issuer=row['issuer'],
            merchant_id=row['merchant_id'],
            status=PaymentStatus(row['status']),
            error_code=row['error_code'],
            error_message=None,
            latency_ms=row['latency_ms'],
            retry_count=row['retry_count'],
            is_retry=bool(row['is_retry']),
            original_transaction_id=None,
            region=row['region'],
            processor=row['processor'],
        )
