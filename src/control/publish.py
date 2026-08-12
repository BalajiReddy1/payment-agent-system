"""
Publishing the control plane.

Everything in this system rests on one claim: the control plane is real, even
when the traffic is simulated. Inside this process that is true - the simulator
reads the policy and behaves differently because of it. Outside it, the claim
had nothing behind it, because there was no way for anything else to read the
policy at all.

This module is that way. The agent writes revisions to a location; a real
checkout service reads them and routes accordingly. That is the entire
integration surface, and it is deliberately the smallest one that works:

**A file, not a callback.** The agent does not call the payment service. A
push means the agent needs credentials for production routing, retries when
the service is down, and an ordering guarantee between two systems that fail
independently. A published document means the reader is in charge of when it
reads, an outage on either side degrades to "the last known policy stays in
force", and the failure mode of the whole integration is staleness rather than
inconsistency.

**Stale is visible, not silent.** A policy document with no freshness marker
cannot be distinguished from a live one by a reader, so a crashed agent would
look exactly like a quiet one and its last intervention would stay in force
forever. Every document carries the time it was written and the interval by
which the next one is due; `PolicyClient.stale` answers the question a caller
actually has.

**Writes are atomic.** A reader polling a file the writer is halfway through
gets a truncated document, and a truncated policy parses as an empty one -
which reads as "no interventions in force" and would silently undo every
mitigation at the worst possible moment. Write to a temporary file, then
rename.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class PolicyPublisher:
    """
    Writes the current control plane revision where other systems can read it.

    Publishing is idempotent and cheap, so the caller can publish every cycle
    without checking whether anything changed - but the revision number is
    checked anyway, because rewriting an unchanged document churns the file's
    mtime and makes "when did the policy last change" unanswerable.
    """

    def __init__(self, path, refresh_seconds: float = 30.0):
        self.path = Path(path)
        self.refresh_seconds = refresh_seconds
        self.last_published: Optional[int] = None
        self.writes = 0

    def publish(self, plane, force: bool = False) -> bool:
        """
        Write the current revision.

        Returns:
            True if a document was written, False if the revision was already
            published. A heartbeat is still written when the document would
            otherwise go stale, so a reader can tell a quiet agent from a dead
            one.
        """
        revision = plane.current

        unchanged = self.last_published == revision.revision
        if unchanged and not force and not self._due_for_heartbeat():
            return False

        document = self.render(plane)
        self._write_atomically(json.dumps(document, indent=2))

        self.last_published = revision.revision
        self.writes += 1
        return True

    def render(self, plane) -> Dict[str, Any]:
        """
        The published document.

        Kept separate from the write so the shape can be tested, and so a
        different transport - an object store, a config service - only has to
        replace the write.
        """
        revision = plane.current
        published_at = datetime.now()

        return {
            'schema_version': SCHEMA_VERSION,
            'revision': revision.revision,
            'published_at': published_at.isoformat(),
            # What a reader needs to decide whether to trust this document,
            # without knowing anything about the agent's cycle time.
            'expires_at': (
                published_at + timedelta(seconds=self.refresh_seconds * 3)
            ).isoformat(),
            'refresh_seconds': self.refresh_seconds,
            'author': revision.author,
            'reason': revision.reason,
            'policy': {
                'circuit_breakers': sorted(revision.circuit_breakers),
                'suppressed_methods': sorted(revision.suppressed_methods),
                'retry_strategies': dict(revision.retry_strategies),
                'routing_overrides': dict(revision.routing_overrides),
                'holdouts': dict(revision.holdouts),
            },
        }

    def _due_for_heartbeat(self) -> bool:
        """
        Whether the published document is close enough to expiry to rewrite.

        Without this, a policy that has not changed in an hour expires and
        every reader falls back to no interventions - undoing live mitigations
        because nothing happened.
        """
        if not self.path.exists():
            return True
        age = datetime.now().timestamp() - self.path.stat().st_mtime
        return age >= self.refresh_seconds

    def _write_atomically(self, content: str):
        """
        Write via a temporary file and rename.

        A reader polling a file mid-write gets a truncated document, and a
        truncated policy parses as an empty one - which reads as "nothing is
        wrong" and would undo every live mitigation. rename(2) is atomic
        within a filesystem, so a reader sees either the old document or the
        new one.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        handle, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix='.policy-', suffix='.tmp'
        )
        try:
            with os.fdopen(handle, 'w') as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


class PolicyClient:
    """
    Reads a published control plane. What a real checkout service would use.

    The design point is what happens when things go wrong, because that is
    when this matters. A missing file, a malformed document, or an agent that
    stopped writing all resolve to "the last policy I successfully read stays
    in force, and `stale` is True" - never to an empty policy. Failing open
    would drop every circuit breaker the moment the agent restarted.
    """

    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.clock = clock or datetime.now

        self.document: Optional[Dict[str, Any]] = None
        self.loaded_revision: Optional[int] = None
        self.read_errors = 0
        self._mtime: Optional[float] = None

    def refresh(self) -> bool:
        """
        Re-read the document if it has changed on disk.

        Returns:
            True if a new revision was loaded.
        """
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self.read_errors += 1
            return False

        if self._mtime is not None and mtime == self._mtime:
            return False

        try:
            document = json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            # Keep serving the last good policy. A parse failure is not
            # evidence that no interventions are in force.
            self.read_errors += 1
            logger.warning("Could not read policy at %s: %s", self.path, exc)
            return False

        if document.get('schema_version') != SCHEMA_VERSION:
            self.read_errors += 1
            logger.warning(
                "Ignoring policy with schema_version=%r; this client speaks %d",
                document.get('schema_version'), SCHEMA_VERSION,
            )
            return False

        self._mtime = mtime
        changed = document.get('revision') != self.loaded_revision
        self.document = document
        self.loaded_revision = document.get('revision')
        return changed

    @property
    def stale(self) -> bool:
        """
        Whether the policy is past the freshness the publisher promised.

        A stale policy is still applied - the interventions in it were real
        and nothing has said otherwise - but a caller that wants to alert on a
        dead agent has something to alert on.
        """
        if self.document is None:
            return True
        expires = self.document.get('expires_at')
        if not expires:
            return True
        try:
            return self.clock() > datetime.fromisoformat(expires)
        except ValueError:
            return True

    # ── The questions a checkout service actually asks ───────────────────────

    def is_broken(self, issuer: str) -> bool:
        """Whether to stop routing to this issuer."""
        return issuer in self._policy().get('circuit_breakers', [])

    def is_suppressed(self, method: str) -> bool:
        """Whether to stop offering this payment method."""
        return method in self._policy().get('suppressed_methods', [])

    def routing_override(self, issuer: str) -> Optional[Dict[str, Any]]:
        """Any routing change in force for this issuer."""
        return self._policy().get('routing_overrides', {}).get(issuer)

    def retry_strategy(self, target: str) -> Optional[Dict[str, Any]]:
        """The retry policy in force for this target, if any."""
        return self._policy().get('retry_strategies', {}).get(target)

    def holdout_fraction(self, target: str) -> float:
        """
        The share of this target's traffic to leave untreated.

        A checkout service honouring this is what makes the agent's
        measurement real rather than self-reported: the control group has to
        exist in the system actually routing payments, not in a simulator.
        """
        return float(self._policy().get('holdouts', {}).get(target, 0.0))

    def _policy(self) -> Dict[str, Any]:
        return (self.document or {}).get('policy', {})

    def describe(self) -> str:
        if self.document is None:
            return f"no policy readable at {self.path}"
        return (
            f"policy r{self.loaded_revision} by {self.document.get('author')}"
            f"{' (STALE)' if self.stale else ''}"
        )
