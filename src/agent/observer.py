"""
Observer Component
Ingests and preprocesses payment transaction data in real-time.
"""

import json
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from src.models.state import (
    AgentMemory,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
)


class PaymentObserver:
    """
    Observes payment transaction streams and maintains real-time statistics.
    
    Responsibilities:
    - Ingest payment transactions from various sources
    - Maintain sliding window statistics
    - Calculate real-time metrics
    - Detect basic anomalies in transaction flow
    """
    
    def __init__(self, window_size_minutes: int = 10):
        self.window_size = timedelta(minutes=window_size_minutes)
        self.memory = AgentMemory()
        
        # Sliding windows for different dimensions
        self.transactions_window = deque()
        
        # Real-time statistics
        self.stats = {
            'overall': defaultdict(lambda: {'success': 0, 'failed': 0, 'total': 0}),
            'by_issuer': defaultdict(lambda: {'success': 0, 'failed': 0, 'total': 0}),
            'by_method': defaultdict(lambda: {'success': 0, 'failed': 0, 'total': 0}),
            'by_region': defaultdict(lambda: {'success': 0, 'failed': 0, 'total': 0}),
            'by_merchant': defaultdict(lambda: {'success': 0, 'failed': 0, 'total': 0}),
        }
        
        # Latency tracking
        self.latencies = {
            'overall': deque(maxlen=1000),
            'by_issuer': defaultdict(lambda: deque(maxlen=100)),
            'by_method': defaultdict(lambda: deque(maxlen=100)),
        }
        
        # Error tracking
        self.error_codes = defaultdict(int)
        self.error_messages = defaultdict(int)
        
        # Retry tracking
        self.retry_stats = defaultdict(lambda: {'attempted': 0, 'succeeded': 0})
        
    def ingest_transaction(self, transaction: PaymentTransaction):
        """
        Ingest a single payment transaction.
        
        Args:
            transaction: PaymentTransaction object
        """
        # Add to memory
        self.memory.add_transaction(transaction)
        
        # Add to sliding window
        self.transactions_window.append(transaction)
        self._cleanup_old_transactions()
        
        # Update statistics
        self._update_stats(transaction)
        
        # Track latency
        self._track_latency(transaction)
        
        # Track errors
        if transaction.status == PaymentStatus.FAILED:
            if transaction.error_code:
                self.error_codes[transaction.error_code] += 1
            if transaction.error_message:
                self.error_messages[transaction.error_message] += 1
        
        # Track retries
        if transaction.is_retry:
            original_id = transaction.original_transaction_id or transaction.transaction_id
            self.retry_stats[original_id]['attempted'] += 1
            if transaction.status == PaymentStatus.SUCCESS:
                self.retry_stats[original_id]['succeeded'] += 1
    
    def ingest_batch(self, transactions: List[PaymentTransaction]):
        """Ingest multiple transactions"""
        for transaction in transactions:
            self.ingest_transaction(transaction)
    
    def _cleanup_old_transactions(self):
        """Remove transactions outside the sliding window"""
        cutoff_time = datetime.now() - self.window_size
        while self.transactions_window and self.transactions_window[0].timestamp < cutoff_time:
            old_txn = self.transactions_window.popleft()
            self._remove_from_stats(old_txn)
    
    def _update_stats(self, transaction: PaymentTransaction):
        """Update real-time statistics"""
        status_key = 'success' if transaction.status == PaymentStatus.SUCCESS else 'failed'
        
        # Overall stats
        self.stats['overall']['current'][status_key] += 1
        self.stats['overall']['current']['total'] += 1
        
        # By issuer
        self.stats['by_issuer'][transaction.issuer][status_key] += 1
        self.stats['by_issuer'][transaction.issuer]['total'] += 1
        
        # By payment method
        method = transaction.payment_method.value
        self.stats['by_method'][method][status_key] += 1
        self.stats['by_method'][method]['total'] += 1
        
        # By region
        self.stats['by_region'][transaction.region][status_key] += 1
        self.stats['by_region'][transaction.region]['total'] += 1
        
        # By merchant
        self.stats['by_merchant'][transaction.merchant_id][status_key] += 1
        self.stats['by_merchant'][transaction.merchant_id]['total'] += 1
    
    def _remove_from_stats(self, transaction: PaymentTransaction):
        """Remove transaction from statistics when it leaves the window"""
        status_key = 'success' if transaction.status == PaymentStatus.SUCCESS else 'failed'
        
        # Overall stats
        self.stats['overall']['current'][status_key] -= 1
        self.stats['overall']['current']['total'] -= 1
        
        # By issuer
        self.stats['by_issuer'][transaction.issuer][status_key] -= 1
        self.stats['by_issuer'][transaction.issuer]['total'] -= 1
        
        # By payment method
        method = transaction.payment_method.value
        self.stats['by_method'][method][status_key] -= 1
        self.stats['by_method'][method]['total'] -= 1
        
        # By region
        self.stats['by_region'][transaction.region][status_key] -= 1
        self.stats['by_region'][transaction.region]['total'] -= 1
        
        # By merchant
        self.stats['by_merchant'][transaction.merchant_id][status_key] -= 1
        self.stats['by_merchant'][transaction.merchant_id]['total'] -= 1
    
    def _track_latency(self, transaction: PaymentTransaction):
        """Track latency metrics"""
        if transaction.latency_ms > 0:
            self.latencies['overall'].append(transaction.latency_ms)
            self.latencies['by_issuer'][transaction.issuer].append(transaction.latency_ms)
            self.latencies['by_method'][transaction.payment_method.value].append(transaction.latency_ms)
    
    def get_success_rate(self, dimension: str = 'overall', key: str = 'current') -> float:
        """
        Calculate success rate for a dimension.
        
        Args:
            dimension: 'overall', 'by_issuer', 'by_method', 'by_region', 'by_merchant'
            key: specific key within dimension (e.g., issuer name)
        
        Returns:
            Success rate as a float between 0 and 1
        """
        stats = self.stats[dimension][key]
        total = stats['total']
        if total == 0:
            return 1.0
        return stats['success'] / total
    
    def get_failure_rate(self, dimension: str = 'overall', key: str = 'current') -> float:
        """Calculate failure rate"""
        return 1.0 - self.get_success_rate(dimension, key)
    
    def get_latency_stats(self, dimension: str = 'overall', key: str = None) -> Dict[str, float]:
        """
        Get latency statistics.
        
        Returns:
            Dictionary with p50, p95, p99, mean, max
        """
        if dimension == 'overall':
            latencies = list(self.latencies['overall'])
        else:
            latencies = list(self.latencies[dimension][key])
        
        if not latencies:
            return {'p50': 0, 'p95': 0, 'p99': 0, 'mean': 0, 'max': 0}
        
        latencies_array = np.array(latencies)
        return {
            'p50': float(np.percentile(latencies_array, 50)),
            'p95': float(np.percentile(latencies_array, 95)),
            'p99': float(np.percentile(latencies_array, 99)),
            'mean': float(np.mean(latencies_array)),
            'max': float(np.max(latencies_array))
        }
    
    def get_transaction_volume(self, dimension: str = 'overall', key: str = 'current') -> int:
        """Get transaction volume"""
        return self.stats[dimension][key]['total']
    
    def get_retry_efficiency(self) -> float:
        """Calculate overall retry efficiency"""
        if not self.retry_stats:
            return 1.0
        
        total_retries = sum(s['attempted'] for s in self.retry_stats.values())
        successful_retries = sum(s['succeeded'] for s in self.retry_stats.values())
        
        if total_retries == 0:
            return 1.0
        
        return successful_retries / total_retries
    
    def get_top_errors(self, n: int = 5) -> List[tuple]:
        """Get top N error codes by frequency"""
        sorted_errors = sorted(self.error_codes.items(), key=lambda x: x[1], reverse=True)
        return sorted_errors[:n]
    
    def get_issuer_health(self) -> Dict[str, Dict[str, float]]:
        """
        Get health metrics for all issuers.
        
        Returns:
            Dictionary mapping issuer to health metrics
        """
        health = {}
        for issuer, stats in self.stats['by_issuer'].items():
            total = stats['total']
            if total == 0:
                continue
            
            success_rate = stats['success'] / total
            latency = self.get_latency_stats('by_issuer', issuer)
            
            health[issuer] = {
                'success_rate': success_rate,
                'failure_rate': 1.0 - success_rate,
                'volume': total,
                'avg_latency': latency['mean'],
                'p95_latency': latency['p95']
            }
        
        return health
    
    def get_method_performance(self) -> Dict[str, Dict[str, float]]:
        """Get performance metrics for all payment methods"""
        performance = {}
        for method, stats in self.stats['by_method'].items():
            total = stats['total']
            if total == 0:
                continue
            
            success_rate = stats['success'] / total
            latency = self.get_latency_stats('by_method', method)
            
            performance[method] = {
                'success_rate': success_rate,
                'failure_rate': 1.0 - success_rate,
                'volume': total,
                'avg_latency': latency['mean'],
                'p95_latency': latency['p95']
            }
        
        return performance
    
    def detect_basic_anomalies(self) -> List[Dict]:
        """
        Detect basic anomalies in the transaction stream.
        
        Returns:
            List of anomaly dictionaries
        """
        anomalies = []
        
        # Check for sudden drops in success rate
        overall_success = self.get_success_rate('overall', 'current')
        if overall_success < 0.85:  # Below 85% success rate
            anomalies.append({
                'type': 'low_success_rate',
                'severity': 1.0 - overall_success,
                'message': f'Overall success rate dropped to {overall_success:.2%}'
            })
        
        # Check individual issuers
        for issuer, health in self.get_issuer_health().items():
            if health['success_rate'] < 0.80 and health['volume'] >= 10:
                anomalies.append({
                    'type': 'issuer_degradation',
                    'severity': 1.0 - health['success_rate'],
                    'affected': issuer,
                    'message': f'Issuer {issuer} has {health["success_rate"]:.2%} success rate'
                })
        
        # Check for high latency
        latency_stats = self.get_latency_stats('overall')
        if latency_stats['p95'] > 1000:  # Over 1 second at p95
            anomalies.append({
                'type': 'high_latency',
                'severity': min(latency_stats['p95'] / 2000, 1.0),
                'message': f'P95 latency at {latency_stats["p95"]:.0f}ms'
            })
        
        # Check retry efficiency
        retry_efficiency = self.get_retry_efficiency()
        if retry_efficiency < 0.30 and len(self.retry_stats) >= 10:
            anomalies.append({
                'type': 'low_retry_efficiency',
                'severity': 1.0 - retry_efficiency,
                'message': f'Retry success rate only {retry_efficiency:.2%}'
            })
        
        return anomalies
    
    def get_summary(self) -> Dict:
        """Get a summary of current observations"""
        return {
            'timestamp': datetime.now().isoformat(),
            'window_size_minutes': self.window_size.seconds / 60,
            'total_transactions': len(self.transactions_window),
            'overall_success_rate': self.get_success_rate('overall', 'current'),
            'overall_latency': self.get_latency_stats('overall'),
            'retry_efficiency': self.get_retry_efficiency(),
            'top_errors': self.get_top_errors(3),
            'issuer_count': len(self.stats['by_issuer']),
            'method_count': len(self.stats['by_method']),
            'anomalies': self.detect_basic_anomalies()
        }
