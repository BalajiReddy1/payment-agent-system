"""Long-running simulated payment-agent runtime shared by API clients."""

from __future__ import annotations

import threading
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from src import views
from src.factory import build_publisher, build_system
from src.traffic.gateway import HttpTransport, PaymentGatewaySource
from src.traffic.source import SimulatedTrafficSource


class AgentRuntime:
    """Own the simulation loop and expose a consistent read model.

    The API is the only product-facing transport. Keeping the loop here avoids
    a second, UI-specific server with its own lifecycle and state.
    """

    def __init__(self, cycle_seconds: float = 3.0, batch_size: int = 220):
        self.cycle_seconds = cycle_seconds
        self.batch_size = batch_size
        self.agent = None
        self.simulator = None
        self.settings = None
        self.publisher = None
        self.traffic_source = None
        self.source: Dict[str, Any] = {
            "kind": "simulated",
            "label": "Synthetic payment traffic",
            "read_only": False,
        }
        self.history: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.demo: Dict[str, Any] = {
            "active": False,
            "seed": None,
            "stage": "idle",
        }
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.is_running:
            return

        with self._lock:
            if self.agent is None or self.simulator is None:
                self._initialize()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.cycle_seconds + 1)
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_once(self) -> Dict[str, Any]:
        if self.agent is None or self.simulator is None:
            self.start()
        with self._lock:
            return self._run_once_locked()

    def start_demo(self) -> Dict[str, Any]:
        """Load the repeatable judge-facing recovery story.

        This is deliberately a seeded batch rather than a UI mock. It drives
        the exact agent, control plane and experiment registry used by the
        live runtime: healthy baseline, severe issuer degradation, an
        automatic low-risk route change, and a separate higher-risk request
        waiting for an operator. The final batches provide enough concurrent
        control traffic to make the displayed recovery figure defensible.
        """
        self.stop()

        with self._lock:
            random.seed(2026)
            self._initialize(outcome_evaluation_seconds=0)
            self.simulator.set_deterministic_ids("judge-demo-2026")
            self.demo = {
                "active": True,
                "seed": 2026,
                "stage": "preparing",
                "scenario": "ICICI Bank issuer degradation",
                "message": "A seeded ICICI Bank outage is being evaluated against a concurrent control group.",
            }

            # Establish the same normal operating baseline on every run.
            for _ in range(3):
                self._run_once_locked(batch_size=500)

            self.simulator.inject_issuer_degradation(
                issuer="ICICI_BANK",
                severity=0.95,
                duration_seconds=3600,
            )

            # This opens the incident, applies the safe route change and
            # queues the circuit breaker for explicit human approval.
            for _ in range(2):
                self._run_once_locked(batch_size=500)

            # 10% is deliberately withheld as control. With a single issuer
            # representing part of traffic, these batches yield at least 30
            # observations in both arms without fabricating an outcome.
            for _ in range(24):
                self._run_once_locked(batch_size=500)

            self.demo["stage"] = "approval_required" if self.agent.approvals.pending() else "measured"
            self.demo["message"] = (
                "The route change has a measured result. The circuit breaker remains gated for operator approval."
                if self.agent.approvals.pending()
                else "The seeded recovery run has completed."
            )

        self.start()
        return self.snapshot()

    def connect_razorpay_test_mode(
        self,
        key_id: str,
        key_secret: str,
        merchant_id: str,
        base_url: str = "https://api.razorpay.com",
    ) -> Dict[str, Any]:
        """Start a fresh, read-only runtime backed by Razorpay test payments.

        The source fetches payment records and maps them into the same
        observation/reasoning loop as simulated traffic. It does not create,
        modify or retry a Razorpay payment. Policy output remains a published
        document for an external routing service to consume, which keeps the
        gateway credential outside the action path.
        """
        self.stop()

        with self._lock:
            self._initialize()
            transport = HttpTransport(
                base_url=base_url,
                api_key=key_id,
                api_secret=key_secret,
            )
            self.traffic_source = PaymentGatewaySource(
                transport=transport,
                provider="razorpay",
                merchant_id=merchant_id,
            )
            self.source = {
                "kind": "razorpay_test_mode",
                "label": self.traffic_source.describe(),
                "read_only": True,
                "signals": sorted(self.traffic_source.signals()),
                "measurement_note": "Razorpay list-payments records do not carry treatment/control attribution; recovery measurement stays in the governed simulator until a routing service returns those tags.",
            }

        self.start()
        return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        if self.agent is None:
            self.start()
        with self._lock:
            read_model = views.snapshot(
                self.agent,
                self.simulator,
                history=list(self.history),
                events=list(self.events[-40:]),
            )
            read_model['demo'] = dict(self.demo)
            read_model['source'] = dict(self.source)
            return read_model

    def health(self) -> Dict[str, Any]:
        if self.agent is None:
            return {"status": "starting", "loop_running": False, "cycles": 0, "advisor": False}
        with self._lock:
            return views.health(self.agent, loop_running=self.is_running)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # The service remains observable after a failed cycle.
                self._emit("error", {"message": str(exc)})
            self._stop.wait(self.cycle_seconds)

    def _initialize(self, outcome_evaluation_seconds: int = 20) -> None:
        """Create a fresh agent/runtime pair while the caller holds the lock."""
        self.agent, self.simulator, self.settings = build_system(
            window_size_minutes=5,
            outcome_evaluation_seconds=outcome_evaluation_seconds,
        )
        self.publisher = build_publisher(self.settings)
        self.traffic_source = SimulatedTrafficSource(self.simulator)
        self.source = {
            "kind": "simulated",
            "label": "Synthetic payment traffic",
            "read_only": False,
        }
        self.history = []
        self.events = []

    def _run_once_locked(self, batch_size: Optional[int] = None) -> Dict[str, Any]:
        """Run one cycle. The caller must hold ``self._lock``."""
        transactions = self.traffic_source.next_batch(batch_size or self.batch_size)
        self.agent.process_batch(transactions)
        results = self.agent.run_cycle()
        self._record(results)
        self._publish()
        return results

    def _record(self, results: Dict[str, Any]) -> None:
        summary = results.get("observation_summary", {})
        self.history.append({
            "cycle": results["cycle"],
            "at": results["timestamp"],
            "success_rate": summary.get("overall_success_rate", 0),
            "latency_p95": summary.get("overall_latency", {}).get("p95", 0),
            "transactions": summary.get("total_transactions", 0),
        })
        self.history = self.history[-120:]

        for incident_id in results.get("incidents_opened", []):
            self._emit("incident_opened", {"incident_id": incident_id})
        for action in results.get("actions_taken", []):
            self._emit("action", action)

    def _publish(self) -> None:
        if self.publisher is None:
            return
        try:
            if self.publisher.publish(self.agent.state.control_plane):
                self._emit("published", {"revision": self.agent.state.control_plane.revision})
        except OSError as exc:
            self._emit("error", {"message": f"policy publish failed: {exc}"})

    def _emit(self, kind: str, payload: Dict[str, Any]) -> None:
        self.events.append({
            "seq": len(self.events) + 1,
            "kind": kind,
            "at": datetime.now().isoformat(),
            "payload": payload,
        })
        self.events = self.events[-300:]
