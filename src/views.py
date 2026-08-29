"""
Read models.

The shapes the REST API serves. They live outside the HTTP layer so a runtime
cycle and an API response cannot develop separate versions of the same state.

Everything here is a pure function of an agent (and optionally a simulator).
No HTTP, no threads, no formatting - so the shape a client depends on can be
tested directly, without standing up either server.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.control.plane import diff


def health(agent, loop_running: bool = True) -> Dict[str, Any]:
    """
    Liveness for container orchestrators.

    Serving a page is not the same as running the agent: an HTTP thread
    outlives a dead cycle loop perfectly well. Callers answer 503 when
    loop_running is false, so a process that still serves pages but has
    stopped thinking cannot pass its own health check.
    """
    return {
        'status': 'ok' if loop_running else 'degraded',
        'loop_running': loop_running,
        'cycles': agent.cycle_count,
        'advisor': agent.advisor is not None,
    }


def snapshot(
    agent,
    simulator=None,
    history: Optional[List[Dict]] = None,
    events: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Everything a client needs to render the agent's current state.

    One document rather than a dozen endpoints: the parts have to agree with
    each other. Assembling a view from separate calls means the metrics can be
    from one cycle and the control plane from the next, and a reader cannot
    tell.
    """
    status = agent.get_status()
    summary = agent.observer.get_summary()
    plane = agent.state.control_plane

    view = {
        'generated_at': datetime.now().isoformat(),
        'agent': {
            'active': status['is_active'],
            'cycle': status['cycle_count'],
            'phase': phase(agent),
            'window_minutes': summary.get('window_size_minutes'),
        },
        'metrics': {
            'success_rate': summary.get('overall_success_rate', 0),
            'latency': summary.get('overall_latency', {}),
            'transactions': summary.get('total_transactions', 0),
            'retry_efficiency': summary.get('retry_efficiency', 0),
        },
        'counters': status['performance'],
        'issuers': issuers(agent),
        'incidents': status.get('incidents', []),
        'approvals': status.get('approvals', []),
        'experiments': status.get('experiments', []),
        'interventions': status.get('active_interventions', []),
        'recovered': recovered(agent),
        'control_plane': control_plane(plane),
        'decisions': decisions(agent),
        'history': list(history or []),
        'events': list(events or []),
    }
    view.update(traffic(simulator))
    return view


def recovered(agent) -> List[Dict[str, Any]]:
    """
    Interventions this agent inherited from a previous run rather than chose.

    Worth its own place in the view. An adopted circuit breaker has no incident
    behind it and no decision trace to open - it is a live change to payment
    routing that nothing on the page would otherwise explain, which is exactly
    the state that let one survive a restart unnoticed in the first place.
    """
    return [
        {
            'action_id': row.get('action_id'),
            'type': row.get('action_type'),
            'target': row.get('target'),
            'executed_at': row.get('executed_at'),
            'approver': row.get('approver'),
        }
        for row in getattr(agent, 'recovered', [])
    ]


def phase(agent) -> str:
    """A coarse state machine, so a client can show what the agent is doing."""
    if agent.incident_tracker.active():
        return 'mitigating'
    if agent.executor.get_active_interventions():
        return 'monitoring'
    return 'observing'


def issuers(agent) -> List[Dict[str, Any]]:
    """Per-issuer health, worst first - the order an operator reads in."""
    health_by_issuer = agent.observer.get_issuer_health()
    breakers = agent.state.active_circuit_breakers

    rows = [
        {
            'issuer': issuer,
            'success_rate': stats['success_rate'],
            'volume': stats['volume'],
            'p95': stats['p95_latency'],
            'broken': issuer in breakers,
        }
        for issuer, stats in sorted(health_by_issuer.items())
    ]
    return sorted(rows, key=lambda r: r['success_rate'])


def control_plane(plane, limit: int = 12) -> Dict[str, Any]:
    """The current policy plus how it got that way."""
    return {
        'revision': plane.revision,
        'policy': plane.current.to_dict(),
        'history': plane_history(plane, limit=limit),
    }


def plane_history(plane, limit: int = 12) -> List[Dict[str, Any]]:
    """
    Revision log, each entry carrying what actually changed.

    The diff against the parent is the point: a revision number tells a reader
    that something changed, not what.
    """
    entries = []
    for revision in plane.history(limit=limit):
        parent = plane.get(revision.parent_revision)
        entries.append({
            'revision': revision.revision,
            'at': revision.created_at.isoformat(),
            'author': revision.author,
            'reason': revision.reason,
            'changes': diff(parent, revision) if parent else ['initial policy'],
        })
    return entries


def decisions(agent, limit: int = 12) -> List[Dict[str, Any]]:
    """
    Recent interventions, newest first.

    Alerts are excluded and the exclusion is applied before the limit. Alerts
    outnumber interventions by roughly fifty to one on a busy incident, so
    taking the last N entries and filtering afterwards left every real decision
    off the view.
    """
    log = agent.executor.get_execution_history(
        limit=limit, exclude_types=('alert_ops', 'no_action')
    )
    return [
        {
            'action_id': entry['action_id'],
            'type': entry['action_type'],
            'target': entry['target'],
            'at': entry['executed_at'],
            'success': entry['success'],
            'message': entry['message'],
            'parameters': jsonable(entry['parameters']),
            'reasoning': entry.get('reasoning', ''),
            'baseline': jsonable(entry.get('baseline_metrics', {})),
        }
        for entry in reversed(log)
    ]


def jsonable(value: Any) -> Any:
    """
    Convert datetimes to ISO strings, recursively.

    Baseline metrics carry the timestamp they were captured at. The console
    hid that behind `json.dumps(default=str)`, so the datetime only surfaced
    on a strict serialiser - a 500 from the REST API for a payload the console
    served fine. Normalising in the read model means both surfaces emit the
    same document.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def traffic(simulator) -> Dict[str, Any]:
    """
    What the control plane did to the traffic, and what is being simulated.

    Empty when there is no simulator, because against a real payment processor
    these counters do not exist - the keys stay present so a client does not
    have to branch on which world it is looking at.
    """
    if simulator is None:
        return {'scenarios': [], 'traffic': {}}

    return {
        'scenarios': [
            {'type': s['type'], 'expires_at': s['expires_at'].isoformat()}
            for s in simulator.get_active_scenarios()
        ],
        'traffic': {
            'rerouted': simulator.rerouted_count,
            'held_out': simulator.control_count,
            'method_switched': simulator.method_switch_count,
        },
    }
