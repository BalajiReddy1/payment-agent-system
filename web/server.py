"""
Console server.

Serves the operations console and the JSON it reads. Deliberately built on
http.server from the standard library: the agent core has no third-party
dependencies and neither should the thing you use to look at it, so this runs
with `python web/server.py` and nothing else.

For production the same endpoints exist on the FastAPI app in api/main.py.
This one exists so the console always has a way to run.
"""

import json
import mimetypes
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.control.plane import diff  # noqa: E402
from src.factory import build_system  # noqa: E402

WEB_ROOT = Path(__file__).resolve().parent


class AgentRunner:
    """
    Drives the agent on a background thread and exposes its state.

    The console is a viewer, not the owner: the agent keeps running whether or
    not a browser is attached, which is the whole point of it being a service
    rather than a page.
    """

    def __init__(self, cycle_seconds: float = 3.0, batch_size: int = 220):
        self.cycle_seconds = cycle_seconds
        self.batch_size = batch_size

        self.agent, self.simulator, self.settings = build_system(
            window_size_minutes=5,
            outcome_evaluation_seconds=20,
        )

        self.history = []
        self.events = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.agent.process_batch(
                    self.simulator.generate_stream(
                        count=self.batch_size, start_time=datetime.now()
                    )
                )
                self.simulator.cleanup_expired_scenarios()
                results = self.agent.run_cycle()
                self._record(results)
            except Exception as exc:  # a viewer must not be able to kill the agent
                self._emit('error', {'message': str(exc)})
            self._stop.wait(self.cycle_seconds)

    def _record(self, results):
        summary = results.get('observation_summary', {})
        with self._lock:
            self.history.append({
                'cycle': results['cycle'],
                'at': results['timestamp'],
                'success_rate': summary.get('overall_success_rate', 0),
                'latency_p95': summary.get('overall_latency', {}).get('p95', 0),
                'latency_mean': summary.get('overall_latency', {}).get('mean', 0),
                'transactions': summary.get('total_transactions', 0),
                'patterns': len(results.get('patterns_detected', [])),
                'actions': len(results.get('actions_taken', [])),
            })
            self.history = self.history[-120:]

        for incident_id in results.get('incidents_opened', []):
            self._emit('incident_opened', {'incident_id': incident_id})
        for action in results.get('actions_taken', []):
            self._emit('action', action)
        for action_id in results.get('rollbacks_executed', []):
            self._emit('rollback', {'action_id': action_id})

    def _emit(self, kind, payload):
        with self._lock:
            self.events.append({
                'seq': len(self.events) + 1,
                'kind': kind,
                'at': datetime.now().isoformat(),
                'payload': payload,
            })
            self.events = self.events[-300:]

    # ── Read models for the console ──────────────────────────────────────────

    def snapshot(self):
        agent = self.agent
        status = agent.get_status()
        summary = agent.observer.get_summary()
        plane = agent.state.control_plane

        with self._lock:
            history = list(self.history)
            events = list(self.events[-40:])

        return {
            'generated_at': datetime.now().isoformat(),
            'agent': {
                'active': status['is_active'],
                'cycle': status['cycle_count'],
                'phase': self._phase(),
                'window_minutes': summary.get('window_size_minutes'),
            },
            'metrics': {
                'success_rate': summary.get('overall_success_rate', 0),
                'latency': summary.get('overall_latency', {}),
                'transactions': summary.get('total_transactions', 0),
                'retry_efficiency': summary.get('retry_efficiency', 0),
            },
            'counters': status['performance'],
            'issuers': self._issuers(),
            'incidents': status.get('incidents', []),
            'approvals': status.get('approvals', []),
            'experiments': status.get('experiments', []),
            'interventions': status.get('active_interventions', []),
            'control_plane': {
                'revision': plane.revision,
                'policy': plane.current.to_dict(),
                'history': self._plane_history(plane),
            },
            'decisions': self._decisions(),
            'scenarios': [
                {'type': s['type'], 'expires_at': s['expires_at'].isoformat()}
                for s in self.simulator.get_active_scenarios()
            ],
            'history': history,
            'events': events,
            'traffic': {
                'rerouted': self.simulator.rerouted_count,
                'held_out': self.simulator.control_count,
                'method_switched': self.simulator.method_switch_count,
            },
        }

    def _phase(self):
        """A coarse state machine so the console can show what the agent is doing."""
        if self.agent.incident_tracker.active():
            return 'mitigating'
        if self.agent.executor.get_active_interventions():
            return 'monitoring'
        return 'observing'

    def _issuers(self):
        health = self.agent.observer.get_issuer_health()
        breakers = self.agent.state.active_circuit_breakers
        rows = []
        for issuer, stats in sorted(health.items()):
            rows.append({
                'issuer': issuer,
                'success_rate': stats['success_rate'],
                'volume': stats['volume'],
                'p95': stats['p95_latency'],
                'broken': issuer in breakers,
            })
        return sorted(rows, key=lambda r: r['success_rate'])

    def _plane_history(self, plane, limit=12):
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

    def _decisions(self, limit=12):
        log = self.agent.executor.get_execution_history(
            limit=limit, exclude_types=('alert_ops', 'no_action')
        )
        decisions = []
        for entry in reversed(log):
            decisions.append({
                'action_id': entry['action_id'],
                'type': entry['action_type'],
                'target': entry['target'],
                'at': entry['executed_at'],
                'success': entry['success'],
                'message': entry['message'],
                'parameters': entry['parameters'],
                'reasoning': entry.get('reasoning', ''),
                'baseline': entry.get('baseline_metrics', {}),
            })
        return decisions

    # ── Commands ─────────────────────────────────────────────────────────────

    def decide_approval(self, request_id, verdict, approver):
        """Grant or refuse a queued action on an operator's behalf."""
        if verdict == 'approve':
            ok, message = self.agent.approve(request_id, approver)
        else:
            ok, message = self.agent.deny(request_id, approver)
        self._emit('approval', {'request_id': request_id, 'verdict': verdict, 'ok': ok})
        return {'ok': ok, 'message': message}

    def inject(self, kind, params):
        sim = self.simulator
        if kind == 'issuer_degradation':
            sim.inject_issuer_degradation(
                params.get('issuer', 'HDFC_BANK'),
                severity=float(params.get('severity', 0.7)),
                duration_seconds=int(params.get('duration', 240)),
            )
        elif kind == 'retry_storm':
            sim.inject_retry_storm(duration_seconds=int(params.get('duration', 180)))
        elif kind == 'latency_spike':
            sim.inject_latency_spike(
                multiplier=float(params.get('multiplier', 3.0)),
                duration_seconds=int(params.get('duration', 150)),
            )
        elif kind == 'geographic_failure':
            sim.inject_geographic_failure(
                params.get('region', 'NORTH'),
                severity=float(params.get('severity', 0.5)),
                duration_seconds=int(params.get('duration', 200)),
            )
        elif kind == 'clear':
            sim.failure_scenarios.clear()
        else:
            raise ValueError(f'unknown scenario: {kind}')

        self._emit('scenario', {'kind': kind, **params})
        return {'ok': True, 'scenario': kind}


class ConsoleHandler(BaseHTTPRequestHandler):
    runner: AgentRunner = None

    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):  # quiet by default
        pass

    def do_GET(self):
        route = urlparse(self.path)
        path = route.path

        if path in ('/', '/index.html'):
            return self._send_file(WEB_ROOT / 'index.html')
        if path == '/api/snapshot':
            return self._send_json(self.runner.snapshot())
        if path == '/api/stream':
            return self._stream()

        candidate = (WEB_ROOT / path.lstrip('/')).resolve()
        if candidate.is_file() and WEB_ROOT in candidate.parents:
            return self._send_file(candidate)

        self.send_error(404)

    def do_POST(self):
        route = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length) or b'{}')

        if route.path == '/api/approval':
            return self._send_json(self.runner.decide_approval(
                body.get('request_id', ''),
                body.get('verdict', 'approve'),
                body.get('approver', 'console-operator'),
            ))

        if route.path == '/api/scenario':
            try:
                result = self.runner.inject(body.pop('type', ''), body)
            except ValueError as exc:
                return self._send_json({'error': str(exc)}, status=400)
            return self._send_json(result)

        self.send_error(404)

    # ── Transport helpers ────────────────────────────────────────────────────

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            return self.send_error(404)
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        """Server-sent events: the console is pushed to, not polling."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        try:
            while True:
                payload = json.dumps(self.runner.snapshot(), default=str)
                self.wfile.write(f'data: {payload}\n\n'.encode('utf-8'))
                self.wfile.flush()
                time.sleep(2.0)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main(port: int = 8080):
    runner = AgentRunner()
    runner.start()
    ConsoleHandler.runner = runner

    server = ThreadingHTTPServer(('0.0.0.0', port), ConsoleHandler)
    print(f'Payment operations console → http://localhost:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()
        server.server_close()


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8080)
