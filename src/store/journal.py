"""
Decision journal.

An append-only record of everything the agent saw, concluded and did:
transactions, detected patterns, actions, their measured outcomes, and every
control plane revision.

Two reasons this exists rather than keeping it all in memory. An ops agent
that forgets its interventions on restart is dangerous - it cannot roll back
what it no longer knows it did. And an agent whose decisions cannot be
replayed after the fact cannot be evaluated, only believed.

The interface is deliberately narrow so the storage engine is swappable. The
SQLite implementation depends on nothing outside the standard library, so it
runs anywhere with no setup; a Postgres/Timescale implementation satisfying
the same interface is a drop-in for real deployments.
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    label       TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    amount          REAL,
    currency        TEXT,
    payment_method  TEXT,
    issuer          TEXT,
    merchant_id     TEXT,
    status          TEXT,
    error_code      TEXT,
    latency_ms      REAL,
    retry_count     INTEGER,
    is_retry        INTEGER,
    region          TEXT,
    processor       TEXT
);
CREATE INDEX IF NOT EXISTS idx_txn_time ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_txn_run ON transactions(run_id);

CREATE TABLE IF NOT EXISTS cycles (
    run_id          TEXT NOT NULL,
    cycle           INTEGER NOT NULL,
    timestamp       TEXT NOT NULL,
    duration_s      REAL,
    success_rate    REAL,
    avg_latency_ms  REAL,
    transactions    INTEGER,
    patterns        INTEGER,
    actions         INTEGER,
    alerts          INTEGER,
    PRIMARY KEY (run_id, cycle)
);

CREATE TABLE IF NOT EXISTS patterns (
    pattern_id      TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    cycle           INTEGER,
    detected_at     TEXT NOT NULL,
    pattern_type    TEXT,
    description     TEXT,
    severity        REAL,
    confidence      REAL,
    dimension       TEXT,
    affected_value  TEXT,
    metrics         TEXT
);
CREATE INDEX IF NOT EXISTS idx_pattern_type ON patterns(pattern_type);

CREATE TABLE IF NOT EXISTS actions (
    action_id               TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL,
    cycle                   INTEGER,
    created_at              TEXT,
    executed_at             TEXT,
    completed_at            TEXT,
    action_type             TEXT,
    target                  TEXT,
    risk_level              TEXT,
    authorization_level     TEXT,
    approver                TEXT,
    status                  TEXT,
    confidence              REAL,
    parameters              TEXT,
    estimated_impact        TEXT,
    reasoning               TEXT,
    control_plane_revision  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_action_type ON actions(action_type);

CREATE TABLE IF NOT EXISTS outcomes (
    action_id         TEXT NOT NULL,
    recorded_at       TEXT NOT NULL,
    baseline_metrics  TEXT,
    actual_metrics    TEXT,
    actual_impact     TEXT,
    prediction_error  REAL,
    PRIMARY KEY (action_id, recorded_at)
);

CREATE TABLE IF NOT EXISTS revisions (
    run_id           TEXT NOT NULL,
    revision         INTEGER NOT NULL,
    parent_revision  INTEGER,
    created_at       TEXT NOT NULL,
    author           TEXT,
    reason           TEXT,
    action_id        TEXT,
    policy           TEXT,
    PRIMARY KEY (run_id, revision)
);
"""


class NullJournal:
    """
    Journal that records nothing.

    The default, so persistence stays opt-in and nothing in the agent has to
    branch on whether a journal exists.
    """

    run_id = None

    def record_transactions(self, transactions): pass
    def record_cycle(self, cycle, results): pass
    def record_pattern(self, pattern, cycle=None): pass
    def record_action(self, action, cycle=None, score=None): pass
    def record_outcome(self, action, baseline, actual, prediction_error=None): pass
    def record_revision(self, revision): pass
    def close(self): pass

    # Recovery reads. A journal that recorded nothing has nothing to recover,
    # so these answer "no prior state" rather than making the caller check
    # which kind of journal it holds.
    def open_interventions(self, run_id=None): return []
    def last_revision(self): return None


class SQLiteJournal:
    """
    Append-only journal backed by SQLite.

    Writes are batched per cycle rather than per transaction; at a few thousand
    transactions a second, a commit per row would dominate the cycle time.
    """

    def __init__(self, path: str = "data/journal.db", label: Optional[str] = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.run_id = str(uuid.uuid4())
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row

        # WAL keeps readers (a dashboard, a replay) from blocking the writer.
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.executescript(SCHEMA)

        with self._write() as cursor:
            cursor.execute(
                "INSERT INTO runs (run_id, started_at, label) VALUES (?, ?, ?)",
                (self.run_id, datetime.now().isoformat(), label),
            )

        logger.info("Journal open at %s (run %s)", self.path, self.run_id[:8])

    @contextmanager
    def _write(self):
        cursor = self._connection.cursor()
        try:
            yield cursor
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            cursor.close()

    # ── Recording ────────────────────────────────────────────────────────────

    def record_transactions(self, transactions: Iterable):
        rows = [
            (
                t.transaction_id, self.run_id, t.timestamp.isoformat(), t.amount,
                t.currency, t.payment_method.value, t.issuer, t.merchant_id,
                t.status.value, t.error_code, t.latency_ms, t.retry_count,
                int(t.is_retry), t.region, t.processor,
            )
            for t in transactions
        ]
        if not rows:
            return

        with self._write() as cursor:
            # Replay of an already-recorded transaction is not an error
            cursor.executemany(
                "INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )

    def record_cycle(self, cycle: int, results: Dict[str, Any]):
        summary = results.get('observation_summary', {})
        latency = summary.get('overall_latency', {})

        with self._write() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id, cycle, results.get('timestamp'),
                    results.get('cycle_duration_seconds'),
                    summary.get('overall_success_rate'),
                    latency.get('mean'),
                    summary.get('total_transactions'),
                    len(results.get('patterns_detected', [])),
                    len(results.get('actions_taken', [])),
                    len(results.get('alerts_raised', [])),
                ),
            )

    def record_pattern(self, pattern, cycle: Optional[int] = None):
        with self._write() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO patterns VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pattern.pattern_id, self.run_id, cycle,
                    pattern.detected_at.isoformat(), pattern.pattern_type,
                    pattern.description, pattern.severity, pattern.confidence,
                    pattern.affected_dimension, pattern.affected_value,
                    json.dumps(pattern.metrics),
                ),
            )

    def record_action(self, action, cycle: Optional[int] = None, score: Optional[float] = None):
        with self._write() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    action.action_id, self.run_id, cycle,
                    _iso(action.created_at), _iso(action.executed_at),
                    _iso(action.completed_at), action.action_type.value,
                    action.target, action.risk_level.value,
                    action.authorization_level.value, action.approver,
                    action.status, action.confidence,
                    json.dumps(action.parameters, default=str),
                    json.dumps(action.estimated_impact, default=str),
                    action.reasoning, action.control_plane_revision,
                ),
            )

    def record_outcome(self, action, baseline: Dict, actual: Dict, prediction_error=None):
        with self._write() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?)",
                (
                    action.action_id, datetime.now().isoformat(),
                    json.dumps(baseline, default=str),
                    json.dumps(actual, default=str),
                    json.dumps(action.actual_impact, default=str),
                    prediction_error,
                ),
            )

    def record_revision(self, revision):
        with self._write() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                (
                    self.run_id, revision.revision, revision.parent_revision,
                    revision.created_at.isoformat(), revision.author,
                    revision.reason, revision.action_id,
                    json.dumps(revision.to_dict()),
                ),
            )

    # ── Reading ──────────────────────────────────────────────────────────────

    def query(self, sql: str, params: Sequence = ()) -> List[sqlite3.Row]:
        cursor = self._connection.cursor()
        try:
            return cursor.execute(sql, params).fetchall()
        finally:
            cursor.close()

    def runs(self) -> List[sqlite3.Row]:
        return self.query("SELECT * FROM runs ORDER BY started_at DESC")

    def transactions(self, run_id: Optional[str] = None, limit: int = 1000):
        return self.query(
            "SELECT * FROM transactions WHERE run_id = ? ORDER BY timestamp LIMIT ?",
            (run_id or self.run_id, limit),
        )

    def actions(self, run_id: Optional[str] = None):
        return self.query(
            "SELECT * FROM actions WHERE run_id = ? ORDER BY created_at",
            (run_id or self.run_id,),
        )

    def revisions(self, run_id: Optional[str] = None):
        return self.query(
            "SELECT * FROM revisions WHERE run_id = ? ORDER BY revision",
            (run_id or self.run_id,),
        )

    def open_interventions(self, run_id: Optional[str] = None):
        """
        Interventions recorded as executed but never completed.

        This is what makes restart safe: on startup the agent can find what it
        left running rather than losing track of live changes to payment
        routing.

        Note the default. It used to be the *current* run, which at startup is
        empty by definition - the interventions that survived the restart
        belong to the run that died. So the query with no argument now spans
        every run, and callers that want one pass it explicitly.
        """
        if run_id is not None:
            return self.query(
                "SELECT * FROM actions WHERE run_id = ? AND executed_at IS NOT NULL "
                "AND completed_at IS NULL ORDER BY executed_at",
                (run_id,),
            )
        return self.query(
            "SELECT * FROM actions WHERE executed_at IS NOT NULL "
            "AND completed_at IS NULL ORDER BY executed_at"
        )

    def last_revision(self) -> Optional[dict]:
        """
        The most recently recorded control plane revision, across all runs.

        Ordered by when it was written rather than by revision number: numbers
        restart at zero with each run, so the highest number is not the latest
        policy - it is whichever run happened to live longest.
        """
        rows = self.query(
            "SELECT r.policy FROM revisions r "
            "JOIN runs ON runs.run_id = r.run_id "
            "ORDER BY runs.started_at DESC, r.revision DESC LIMIT 1"
        )
        return json.loads(rows[0]['policy']) if rows else None

    def effectiveness_by_action_type(self) -> List[sqlite3.Row]:
        """Measured outcomes grouped by action type, across all runs."""
        return self.query(
            """
            SELECT a.action_type,
                   COUNT(*) AS samples,
                   AVG(o.prediction_error) AS avg_prediction_error
            FROM outcomes o
            JOIN actions a ON a.action_id = o.action_id
            GROUP BY a.action_type
            ORDER BY samples DESC
            """
        )

    def close(self):
        self._connection.close()


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
