"""
Incidents.

Patterns are detected every cycle; incidents are what a human would call a
thing that happened. The distinction matters because it decides how often the
expensive part of the brain runs.

The agent has two lanes:

- The fast lane is deterministic and runs on every cycle: streaming
  aggregates, Bayesian rate estimation, sequential changepoint detection. It
  costs microseconds and it is what decides whether anything is wrong.

- The slow lane is the LLM. It is consulted once when an incident *opens*,
  not once per cycle. Calling a model on every cycle of a live payment stream
  is untenable on both latency and cost, and it would produce a fresh opinion
  every few seconds about a situation that has not changed.

This module is the boundary between them: it collapses a stream of repeated
detections into a single incident with a lifecycle, so the slow lane fires
once per real event.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional


@dataclass
class Incident:
    """A continuing problem, assembled from repeated detections."""

    incident_id: str
    pattern_type: str
    target: str
    opened_at: datetime
    last_seen_at: datetime
    closed_at: Optional[datetime] = None

    detections: int = 1
    peak_severity: float = 0.0
    latest_severity: float = 0.0
    latest_confidence: float = 0.0

    actions_taken: List[str] = field(default_factory=list)
    advice: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.closed_at is None

    @property
    def duration_seconds(self) -> float:
        end = self.closed_at or datetime.now()
        return (end - self.opened_at).total_seconds()

    def summary(self) -> Dict:
        return {
            'incident_id': self.incident_id,
            'pattern_type': self.pattern_type,
            'target': self.target,
            'opened_at': self.opened_at.isoformat(),
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'active': self.active,
            'detections': self.detections,
            'peak_severity': self.peak_severity,
            'latest_severity': self.latest_severity,
            'latest_confidence': self.latest_confidence,
            'duration_seconds': round(self.duration_seconds, 1),
            'actions_taken': list(self.actions_taken),
            'advice': self.advice,
        }


class IncidentTracker:
    """
    Collapses repeated detections into incidents with a lifecycle.

    An incident stays open while its pattern keeps being detected, and closes
    after `close_after` seconds without a detection. That grace period matters:
    detection is statistical, so a genuinely ongoing outage will occasionally
    fail to trip on a single cycle, and closing immediately would produce a
    flapping series of incidents rather than one.
    """

    def __init__(self, close_after_seconds: float = 120.0):
        self.close_after = timedelta(seconds=close_after_seconds)
        self.incidents: Dict[str, Incident] = {}
        self._sequence = 0

    @staticmethod
    def key_for(pattern) -> str:
        return f"{pattern.pattern_type}:{pattern.affected_value}"

    def observe(self, pattern) -> tuple:
        """
        Record a detection.

        Returns:
            Tuple of (incident, is_new). `is_new` is the signal the slow lane
            watches: it is True exactly once per incident.
        """
        key = self.key_for(pattern)
        now = datetime.now()
        incident = self.incidents.get(key)

        if incident is not None and incident.active:
            incident.last_seen_at = now
            incident.detections += 1
            incident.latest_severity = pattern.severity
            incident.latest_confidence = pattern.confidence
            incident.peak_severity = max(incident.peak_severity, pattern.severity)
            return incident, False

        self._sequence += 1
        incident = Incident(
            incident_id=f"inc-{self._sequence:04d}",
            pattern_type=pattern.pattern_type,
            target=pattern.affected_value,
            opened_at=now,
            last_seen_at=now,
            peak_severity=pattern.severity,
            latest_severity=pattern.severity,
            latest_confidence=pattern.confidence,
        )
        self.incidents[key] = incident
        return incident, True

    def close_stale(self) -> List[Incident]:
        """Close incidents whose pattern has stopped being detected."""
        now = datetime.now()
        closed = []
        for incident in self.incidents.values():
            if incident.active and now - incident.last_seen_at > self.close_after:
                incident.closed_at = now
                closed.append(incident)
        return closed

    def active(self) -> List[Incident]:
        return [i for i in self.incidents.values() if i.active]

    def all(self) -> List[Incident]:
        return sorted(
            self.incidents.values(), key=lambda i: i.opened_at, reverse=True
        )
