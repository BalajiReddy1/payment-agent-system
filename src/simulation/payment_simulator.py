"""
Payment Simulator
Generates realistic payment transaction streams with various failure scenarios.
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List
from uuid import uuid4

from src.models.state import PaymentMethod, PaymentStatus, PaymentTransaction


DEFAULT_MAX_RETRIES = 3
BASE_RETRY_RATE = 0.05

# What it costs, in success probability and latency, to move a transaction off
# its natural issuer. Rerouting helps when the original issuer is failing, but
# it is not free - otherwise the agent would learn to reroute everything.
REROUTE_SUCCESS_PENALTY = 0.03
REROUTE_LATENCY_PENALTY_MS = 40.0


class PaymentSimulator:
    """
    Simulates realistic payment transaction streams.

    Features:
    - Normal healthy operation
    - Issuer degradation scenarios
    - Retry storms
    - Payment method fatigue
    - Geographic failures
    - Latency spikes

    Crucially, the simulator *obeys the agent's control plane*. Circuit
    breakers reroute traffic, suppressed methods stop being offered, retry
    limits reduce retry volume and timeouts truncate latency. Without this the
    agent's actions would have no effect on the metrics it subsequently
    observes, and every downstream mechanism that depends on measuring an
    action's outcome - rollback, learning, effectiveness scoring - would be
    reading nothing but noise.
    """

    def __init__(self, base_success_rate: float = 0.95, control_plane=None):
        self.base_success_rate = base_success_rate

        # Anything exposing active_circuit_breakers, suppressed_methods,
        # retry_strategies and routing_overrides. AgentState satisfies this.
        self.control_plane = control_plane

        # Counters so a demo can show the control plane is actually biting
        self.rerouted_count = 0
        self.method_switch_count = 0
        self.retries_suppressed_count = 0

        # Available issuers
        self.issuers = [
            'HDFC_BANK', 'ICICI_BANK', 'SBI', 'AXIS_BANK',
            'KOTAK_BANK', 'YES_BANK', 'PAYTM_BANK', 'RAZORPAY'
        ]
        
        # Payment methods with weights
        self.payment_methods = [
            (PaymentMethod.CREDIT_CARD, 0.35),
            (PaymentMethod.DEBIT_CARD, 0.30),
            (PaymentMethod.UPI, 0.25),
            (PaymentMethod.NET_BANKING, 0.07),
            (PaymentMethod.WALLET, 0.03)
        ]
        
        # Regions
        self.regions = ['NORTH', 'SOUTH', 'EAST', 'WEST', 'CENTRAL']
        
        # Merchants
        self.merchants = [f'MERCHANT_{i:04d}' for i in range(1, 51)]
        
        # Error codes
        self.error_codes = [
            'INSUFFICIENT_FUNDS',
            'INVALID_CARD',
            'TIMEOUT',
            'ISSUER_DOWN',
            'NETWORK_ERROR',
            'DECLINED',
            'EXPIRED_CARD',
            'FRAUD_SUSPECTED'
        ]
        
        # Active failure scenarios
        self.failure_scenarios = {}
        
        # Transaction counter
        self.transaction_count = 0
    
    def generate_transaction(
        self,
        timestamp: datetime = None,
        force_retry: bool = False
    ) -> PaymentTransaction:
        """Generate a single payment transaction"""
        if timestamp is None:
            timestamp = datetime.now()
        
        self.transaction_count += 1

        # Select payment method (weighted random), honouring suppressions
        methods, weights = zip(*self.payment_methods)
        payment_method = random.choices(methods, weights=weights)[0]
        payment_method = self._apply_method_suppression(payment_method)

        # Select other attributes
        region = random.choice(self.regions)
        merchant = random.choice(self.merchants)

        # Select issuer, honouring circuit breakers and routing overrides
        issuer = random.choice(self.issuers)
        issuer, rerouted = self._apply_routing(issuer)

        # Determine if this is a retry, honouring retry-strategy limits
        is_retry = force_retry or self._should_retry(payment_method)
        retry_count = random.randint(1, self._max_retries(payment_method)) if is_retry else 0

        # Calculate success/failure based on scenarios
        status, error_code, error_message = self._determine_outcome(
            issuer, payment_method, region, is_retry, rerouted
        )

        # Generate latency
        latency_ms = self._generate_latency(status, issuer, region, rerouted)

        # A tightened timeout truncates latency and fails whatever ran over it
        status, error_code, error_message, latency_ms = self._apply_timeout(
            status, error_code, error_message, latency_ms
        )

        # Generate amount
        amount = round(random.lognormvariate(6, 1.5), 2)  # Log-normal distribution
        
        return PaymentTransaction(
            transaction_id=str(uuid4()),
            timestamp=timestamp,
            amount=amount,
            currency='INR',
            payment_method=payment_method,
            issuer=issuer,
            merchant_id=merchant,
            status=status,
            error_code=error_code,
            error_message=error_message,
            latency_ms=latency_ms,
            retry_count=retry_count,
            is_retry=is_retry,
            original_transaction_id=str(uuid4()) if is_retry else None,
            region=region,
            processor='rerouted' if rerouted else 'default'
        )
    
    def generate_stream(
        self,
        count: int,
        start_time: datetime = None
    ) -> List[PaymentTransaction]:
        """Generate a stream of transactions"""
        if start_time is None:
            start_time = datetime.now()
        
        transactions = []
        for i in range(count):
            # Spread transactions over time (one per second on average)
            timestamp = start_time + timedelta(seconds=i + random.uniform(-0.5, 0.5))
            transaction = self.generate_transaction(timestamp)
            transactions.append(transaction)
        
        return transactions
    
    # ── Control plane ────────────────────────────────────────────────────────

    def set_control_plane(self, control_plane):
        """Attach the state object whose interventions this traffic obeys."""
        self.control_plane = control_plane

    def _cp(self, attribute: str, default):
        """Read a control-plane field, tolerating no control plane at all."""
        if self.control_plane is None:
            return default
        return getattr(self.control_plane, attribute, default)

    def _apply_routing(self, issuer: str) -> tuple:
        """
        Apply circuit breakers and routing overrides to an issuer choice.

        Returns:
            Tuple of (issuer to actually use, whether it was rerouted)
        """
        breakers = self._cp('active_circuit_breakers', set())
        overrides = self._cp('routing_overrides', {})

        divert = issuer in breakers

        if not divert:
            # A routing override diverts a percentage of the issuer's traffic
            override = overrides.get(issuer) or overrides.get(f'issuer_{issuer}')
            if isinstance(override, dict):
                reduce_pct = override.get('reduce_routing_pct', 0) or 0
                if reduce_pct and random.random() < reduce_pct / 100.0:
                    divert = True

        if not divert:
            return issuer, False

        alternatives = [i for i in self.issuers if i != issuer and i not in breakers]
        if not alternatives:
            # Nowhere healthy to send it; the breaker cannot help here
            return issuer, False

        self.rerouted_count += 1
        return random.choice(alternatives), True

    def _apply_method_suppression(self, method: PaymentMethod) -> PaymentMethod:
        """Swap a suppressed payment method for one that is still offered."""
        suppressed = self._cp('suppressed_methods', set())
        if not suppressed or method.value not in suppressed:
            return method

        alternatives = [
            m for m, _ in self.payment_methods
            if m.value not in suppressed
        ]
        if not alternatives:
            return method

        self.method_switch_count += 1
        return random.choice(alternatives)

    def _retry_strategy_for(self, method: PaymentMethod) -> Dict:
        """Merge the global and per-method retry strategies in force."""
        strategies = self._cp('retry_strategies', {})
        merged: Dict = {}
        for key in ('global_retry_strategy', f'method_{method.value}', 'timeout_settings'):
            value = strategies.get(key)
            if isinstance(value, dict):
                merged.update(value)
        return merged

    def _max_retries(self, method: PaymentMethod) -> int:
        """Effective retry ceiling for a method under current policy."""
        configured = self._retry_strategy_for(method).get('max_retries')
        if configured is None:
            return DEFAULT_MAX_RETRIES
        return max(1, int(configured))

    def _should_retry(self, method: PaymentMethod) -> bool:
        """
        Decide whether this transaction is a retry.

        Tightening max_retries proportionally reduces how much retry traffic
        the system generates - which is exactly the lever the agent pulls when
        it detects a retry storm.
        """
        allowed = self._max_retries(method)
        rate = BASE_RETRY_RATE * (allowed / DEFAULT_MAX_RETRIES)

        is_retry = random.random() < rate
        if allowed < DEFAULT_MAX_RETRIES and not is_retry:
            if random.random() < BASE_RETRY_RATE - rate:
                self.retries_suppressed_count += 1
        return is_retry

    def _apply_timeout(
        self,
        status: PaymentStatus,
        error_code,
        error_message,
        latency_ms: float
    ) -> tuple:
        """Truncate latency at the configured timeout, failing what overruns."""
        strategies = self._cp('retry_strategies', {})
        timeout_settings = strategies.get('timeout_settings')
        if not isinstance(timeout_settings, dict):
            return status, error_code, error_message, latency_ms

        timeout_ms = timeout_settings.get('timeout_ms')
        if not timeout_ms or latency_ms <= timeout_ms:
            return status, error_code, error_message, latency_ms

        return (
            PaymentStatus.FAILED,
            'TIMEOUT',
            'TIMEOUT: Transaction exceeded configured timeout',
            float(timeout_ms)
        )

    # ── Outcome generation ───────────────────────────────────────────────────

    def _determine_outcome(
        self,
        issuer: str,
        payment_method: PaymentMethod,
        region: str,
        is_retry: bool,
        rerouted: bool = False
    ) -> tuple:
        """Determine if transaction succeeds or fails"""
        
        # Base success rate
        success_prob = self.base_success_rate
        
        # Apply failure scenarios
        for scenario in self.active_scenarios():
            if scenario['type'] == 'issuer_degradation':
                if issuer == scenario['issuer']:
                    success_prob *= (1 - scenario['severity'])
            
            elif scenario['type'] == 'method_fatigue':
                if payment_method == scenario['method'] and is_retry:
                    success_prob *= (1 - scenario['severity'])
            
            elif scenario['type'] == 'geographic_failure':
                if region == scenario['region']:
                    success_prob *= (1 - scenario['severity'])
            
            elif scenario['type'] == 'retry_storm':
                if is_retry:
                    success_prob *= 0.5  # Retries much less likely to succeed
        
        # Retries have lower success rate in general
        if is_retry:
            success_prob *= 0.7

        # Rerouting away from an issuer costs a little success probability
        if rerouted:
            success_prob -= REROUTE_SUCCESS_PENALTY

        # Determine outcome
        if random.random() < success_prob:
            return PaymentStatus.SUCCESS, None, None
        else:
            # Failed - pick error code
            error_code = random.choice(self.error_codes)
            
            # Special error codes for scenarios
            for scenario in self.active_scenarios():
                if scenario['type'] == 'issuer_degradation':
                    if issuer == scenario['issuer'] and random.random() < 0.7:
                        error_code = 'ISSUER_DOWN'
            
            error_message = f"{error_code}: Transaction declined"
            return PaymentStatus.FAILED, error_code, error_message
    
    def _generate_latency(
        self,
        status: PaymentStatus,
        issuer: str,
        region: str,
        rerouted: bool = False
    ) -> float:
        """Generate realistic latency"""
        
        # Base latency
        base_latency = 200  # 200ms base
        
        # Add randomness
        latency = base_latency + random.gauss(0, 50)
        
        # Failed transactions are often faster (immediate reject)
        if status == PaymentStatus.FAILED:
            if random.random() < 0.5:
                latency *= 0.5
        
        # Apply latency spike scenarios
        for scenario in self.active_scenarios():
            if scenario['type'] == 'latency_spike':
                latency *= scenario['multiplier']
            
            elif scenario['type'] == 'geographic_failure':
                if region == scenario['region']:
                    latency *= 2.0

        # An alternative route is a little further away
        if rerouted:
            latency += REROUTE_LATENCY_PENALTY_MS

        return max(10, latency)  # Minimum 10ms
    
    # Scenario injection methods
    
    def inject_issuer_degradation(
        self,
        issuer: str,
        severity: float = 0.6,
        duration_seconds: int = 300
    ):
        """
        Inject issuer degradation scenario.
        
        Args:
            issuer: Which issuer to affect
            severity: How bad (0.0-1.0, where 1.0 = complete failure)
            duration_seconds: How long the degradation lasts
        """
        scenario_id = f'issuer_deg_{issuer}_{datetime.now().timestamp()}'
        self.failure_scenarios[scenario_id] = {
            'type': 'issuer_degradation',
            'issuer': issuer,
            'severity': severity,
            'injected_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=duration_seconds)
        }
        print(f"🔥 Injected issuer degradation: {issuer} at {severity:.0%} severity for {duration_seconds}s")
    
    def inject_retry_storm(self, duration_seconds: int = 180):
        """Inject retry storm scenario"""
        scenario_id = f'retry_storm_{datetime.now().timestamp()}'
        self.failure_scenarios[scenario_id] = {
            'type': 'retry_storm',
            'injected_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=duration_seconds)
        }
        print(f"🔥 Injected retry storm for {duration_seconds}s")
    
    def inject_method_fatigue(
        self,
        method: PaymentMethod,
        severity: float = 0.4,
        duration_seconds: int = 240
    ):
        """Inject payment method fatigue"""
        scenario_id = f'method_fatigue_{method.value}_{datetime.now().timestamp()}'
        self.failure_scenarios[scenario_id] = {
            'type': 'method_fatigue',
            'method': method,
            'severity': severity,
            'injected_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=duration_seconds)
        }
        print(f"🔥 Injected method fatigue: {method.value} at {severity:.0%} severity for {duration_seconds}s")
    
    def inject_geographic_failure(
        self,
        region: str,
        severity: float = 0.5,
        duration_seconds: int = 200
    ):
        """Inject geographic failure"""
        scenario_id = f'geo_failure_{region}_{datetime.now().timestamp()}'
        self.failure_scenarios[scenario_id] = {
            'type': 'geographic_failure',
            'region': region,
            'severity': severity,
            'injected_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=duration_seconds)
        }
        print(f"🔥 Injected geographic failure: {region} at {severity:.0%} severity for {duration_seconds}s")
    
    def inject_latency_spike(
        self,
        multiplier: float = 3.0,
        duration_seconds: int = 150
    ):
        """Inject latency spike"""
        scenario_id = f'latency_spike_{datetime.now().timestamp()}'
        self.failure_scenarios[scenario_id] = {
            'type': 'latency_spike',
            'multiplier': multiplier,
            'injected_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=duration_seconds)
        }
        print(f"🔥 Injected latency spike: {multiplier}x for {duration_seconds}s")
    
    def active_scenarios(self) -> List[Dict]:
        """
        Scenarios currently in force.

        Expiry is enforced here rather than relying on cleanup_expired_scenarios
        having been called, so a caller that forgets to sweep cannot leave a
        failure injected forever.
        """
        now = datetime.now()
        return [
            scenario
            for scenario in self.failure_scenarios.values()
            if scenario['expires_at'] > now
        ]

    def cleanup_expired_scenarios(self):
        """Drop expired failure scenarios from the registry"""
        now = datetime.now()
        expired = [
            scenario_id
            for scenario_id, scenario in self.failure_scenarios.items()
            if scenario['expires_at'] <= now
        ]

        for scenario_id in expired:
            scenario = self.failure_scenarios[scenario_id]
            print(f"✅ Scenario expired: {scenario['type']}")
            del self.failure_scenarios[scenario_id]

    def get_active_scenarios(self) -> List[Dict]:
        """Get list of currently active failure scenarios, with their ids"""
        now = datetime.now()
        return [
            {
                'id': scenario_id,
                **scenario
            }
            for scenario_id, scenario in self.failure_scenarios.items()
            if scenario['expires_at'] > now
        ]
