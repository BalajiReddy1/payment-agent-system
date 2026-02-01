"""
Payment Simulator
Generates realistic payment transaction streams with various failure scenarios.
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List
from uuid import uuid4

from src.models.state import PaymentMethod, PaymentStatus, PaymentTransaction


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
    """
    
    def __init__(self, base_success_rate: float = 0.95):
        self.base_success_rate = base_success_rate
        
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
        
        # Select payment method (weighted random)
        methods, weights = zip(*self.payment_methods)
        payment_method = random.choices(methods, weights=weights)[0]
        
        # Select other attributes
        issuer = random.choice(self.issuers)
        region = random.choice(self.regions)
        merchant = random.choice(self.merchants)
        
        # Determine if this is a retry
        is_retry = force_retry or random.random() < 0.05  # 5% base retry rate
        retry_count = random.randint(1, 3) if is_retry else 0
        
        # Calculate success/failure based on scenarios
        status, error_code, error_message = self._determine_outcome(
            issuer, payment_method, region, is_retry
        )
        
        # Generate latency
        latency_ms = self._generate_latency(status, issuer, region)
        
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
            processor='default'
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
    
    def _determine_outcome(
        self,
        issuer: str,
        payment_method: PaymentMethod,
        region: str,
        is_retry: bool
    ) -> tuple:
        """Determine if transaction succeeds or fails"""
        
        # Base success rate
        success_prob = self.base_success_rate
        
        # Apply failure scenarios
        for scenario_name, scenario in self.failure_scenarios.items():
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
        
        # Determine outcome
        if random.random() < success_prob:
            return PaymentStatus.SUCCESS, None, None
        else:
            # Failed - pick error code
            error_code = random.choice(self.error_codes)
            
            # Special error codes for scenarios
            for scenario in self.failure_scenarios.values():
                if scenario['type'] == 'issuer_degradation':
                    if issuer == scenario['issuer'] and random.random() < 0.7:
                        error_code = 'ISSUER_DOWN'
            
            error_message = f"{error_code}: Transaction declined"
            return PaymentStatus.FAILED, error_code, error_message
    
    def _generate_latency(
        self,
        status: PaymentStatus,
        issuer: str,
        region: str
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
        for scenario in self.failure_scenarios.values():
            if scenario['type'] == 'latency_spike':
                latency *= scenario['multiplier']
            
            elif scenario['type'] == 'geographic_failure':
                if region == scenario['region']:
                    latency *= 2.0
        
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
    
    def cleanup_expired_scenarios(self):
        """Remove expired failure scenarios"""
        now = datetime.now()
        expired = [
            scenario_id
            for scenario_id, scenario in self.failure_scenarios.items()
            if scenario['expires_at'] < now
        ]
        
        for scenario_id in expired:
            scenario = self.failure_scenarios[scenario_id]
            print(f"✅ Scenario expired: {scenario['type']}")
            del self.failure_scenarios[scenario_id]
    
    def get_active_scenarios(self) -> List[Dict]:
        """Get list of currently active failure scenarios"""
        return [
            {
                'id': scenario_id,
                **scenario
            }
            for scenario_id, scenario in self.failure_scenarios.items()
        ]
