"""
Reasoner Component
Detects patterns, forms hypotheses, and analyzes payment behavior.
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

from src.models.state import Hypothesis, Pattern, PaymentTransaction


class PaymentReasoner:
    """
    Reasons about payment patterns and forms hypotheses about root causes.
    
    Capabilities:
    - Pattern detection (issuer degradation, retry storms, method fatigue, etc.)
    - Root cause hypothesis generation
    - Confidence scoring
    - Evidence gathering
    """
    
    def __init__(self, baseline_window_hours: int = 24):
        self.baseline_window = timedelta(hours=baseline_window_hours)
        
        # Baseline metrics (learned over time)
        self.baselines = {
            'overall_success_rate': 0.95,
            'issuer_success_rates': defaultdict(lambda: 0.95),
            'method_success_rates': defaultdict(lambda: 0.95),
            'avg_latency': 200.0,
            'retry_efficiency': 0.60
        }
        
        # Pattern detection thresholds
        self.thresholds = {
            'issuer_degradation': 0.15,  # 15% drop from baseline
            'method_fatigue': 0.20,  # 20% drop from baseline
            'latency_spike': 1.5,  # 1.5x baseline
            'retry_storm': 0.40,  # 40% of traffic is retries
            'error_cluster': 10  # Same error 10+ times in window
        }
        
        # Known pattern library
        self.pattern_library = self._initialize_pattern_library()
    
    def _initialize_pattern_library(self) -> Dict[str, Dict]:
        """Initialize library of known payment patterns"""
        return {
            'issuer_degradation': {
                'description': 'Issuer experiencing elevated failure rates',
                'typical_causes': ['issuer_down', 'issuer_throttling', 'network_issue'],
                'indicators': ['sudden_failure_spike', 'specific_error_codes', 'geographic_clustering']
            },
            'retry_storm': {
                'description': 'Excessive retries causing cascading failures',
                'typical_causes': ['aggressive_retry_config', 'payment_gateway_issue', 'timeout_misconfiguration'],
                'indicators': ['high_retry_percentage', 'increasing_latency', 'low_retry_success']
            },
            'method_fatigue': {
                'description': 'Payment method showing degraded performance after retries',
                'typical_causes': ['card_issuer_limits', 'fraud_detection_triggers', 'user_cancellation'],
                'indicators': ['declining_retry_success', 'specific_method_affected', 'error_pattern']
            },
            'geographic_issue': {
                'description': 'Failures concentrated in specific region',
                'typical_causes': ['network_outage', 'regional_bank_issue', 'compliance_block'],
                'indicators': ['geographic_clustering', 'multiple_issuers_affected', 'timing_correlation']
            },
            'temporal_pattern': {
                'description': 'Time-based failure pattern',
                'typical_causes': ['peak_load_issue', 'scheduled_maintenance', 'business_hours_effect'],
                'indicators': ['time_correlation', 'recurring_pattern', 'volume_correlation']
            }
        }
    
    def analyze(self, observer) -> List[Pattern]:
        """
        Main analysis method - detect all patterns in current data.
        
        Args:
            observer: PaymentObserver instance with current data
        
        Returns:
            List of detected patterns
        """
        patterns = []
        
        # Detect different pattern types
        patterns.extend(self._detect_issuer_degradation(observer))
        patterns.extend(self._detect_retry_storms(observer))
        patterns.extend(self._detect_method_fatigue(observer))
        patterns.extend(self._detect_latency_spikes(observer))
        patterns.extend(self._detect_error_clusters(observer))
        patterns.extend(self._detect_geographic_issues(observer))
        
        # Sort by severity
        patterns.sort(key=lambda p: p.severity, reverse=True)
        
        return patterns
    
    def _detect_issuer_degradation(self, observer) -> List[Pattern]:
        """Detect issuers with degraded performance"""
        patterns = []
        issuer_health = observer.get_issuer_health()
        
        for issuer, health in issuer_health.items():
            baseline = self.baselines['issuer_success_rates'][issuer]
            degradation = baseline - health['success_rate']
            
            # Only flag if volume is significant and degradation exceeds threshold
            if health['volume'] >= 10 and degradation >= self.thresholds['issuer_degradation']:
                severity = min(degradation / 0.3, 1.0)  # Normalize to 0-1
                confidence = self._calculate_confidence(health['volume'], degradation)
                
                pattern = Pattern(
                    pattern_id='',
                    pattern_type='issuer_degradation',
                    description=f'Issuer {issuer} showing {degradation:.1%} drop in success rate',
                    severity=severity,
                    confidence=confidence,
                    affected_dimension='issuer',
                    affected_value=issuer,
                    metrics={
                        'current_success_rate': health['success_rate'],
                        'baseline_success_rate': baseline,
                        'degradation': degradation,
                        'volume': health['volume'],
                        'avg_latency': health['avg_latency']
                    },
                    detected_at=datetime.now(),
                    evidence=[
                        f'Success rate: {health["success_rate"]:.2%} (baseline: {baseline:.2%})',
                        f'Volume: {health["volume"]} transactions',
                        f'Average latency: {health["avg_latency"]:.0f}ms'
                    ]
                )
                patterns.append(pattern)
        
        return patterns
    
    def _detect_retry_storms(self, observer) -> List[Pattern]:
        """Detect excessive retry behavior"""
        patterns = []
        
        # Calculate retry percentage
        total_txns = observer.get_transaction_volume('overall', 'current')
        retry_count = sum(1 for txn in observer.transactions_window if txn.is_retry)
        
        if total_txns == 0:
            return patterns
        
        retry_percentage = retry_count / total_txns
        retry_efficiency = observer.get_retry_efficiency()
        
        if retry_percentage >= self.thresholds['retry_storm']:
            severity = min(retry_percentage / 0.6, 1.0)
            confidence = self._calculate_confidence(total_txns, retry_percentage - 0.2)
            
            pattern = Pattern(
                pattern_id='',
                pattern_type='retry_storm',
                description=f'{retry_percentage:.1%} of traffic is retries with {retry_efficiency:.1%} success rate',
                severity=severity,
                confidence=confidence,
                affected_dimension='overall',
                affected_value='retry_behavior',
                metrics={
                    'retry_percentage': retry_percentage,
                    'retry_efficiency': retry_efficiency,
                    'total_retries': retry_count,
                    'total_transactions': total_txns
                },
                detected_at=datetime.now(),
                evidence=[
                    f'Retry percentage: {retry_percentage:.1%}',
                    f'Retry efficiency: {retry_efficiency:.1%}',
                    f'{retry_count} retries out of {total_txns} transactions'
                ]
            )
            patterns.append(pattern)
        
        return patterns
    
    def _detect_method_fatigue(self, observer) -> List[Pattern]:
        """Detect payment methods with declining performance after retries"""
        patterns = []
        method_performance = observer.get_method_performance()
        
        for method, perf in method_performance.items():
            baseline = self.baselines['method_success_rates'][method]
            degradation = baseline - perf['success_rate']
            
            # Check if degradation is significant and volume is meaningful
            if perf['volume'] >= 20 and degradation >= self.thresholds['method_fatigue']:
                severity = min(degradation / 0.4, 1.0)
                confidence = self._calculate_confidence(perf['volume'], degradation)
                
                pattern = Pattern(
                    pattern_id='',
                    pattern_type='method_fatigue',
                    description=f'Payment method {method} showing {degradation:.1%} drop in success rate',
                    severity=severity,
                    confidence=confidence,
                    affected_dimension='payment_method',
                    affected_value=method,
                    metrics={
                        'current_success_rate': perf['success_rate'],
                        'baseline_success_rate': baseline,
                        'degradation': degradation,
                        'volume': perf['volume']
                    },
                    detected_at=datetime.now(),
                    evidence=[
                        f'Success rate: {perf["success_rate"]:.2%} (baseline: {baseline:.2%})',
                        f'Volume: {perf["volume"]} transactions',
                        f'Degradation: {degradation:.1%}'
                    ]
                )
                patterns.append(pattern)
        
        return patterns
    
    def _detect_latency_spikes(self, observer) -> List[Pattern]:
        """Detect unusual latency increases"""
        patterns = []
        latency_stats = observer.get_latency_stats('overall')
        baseline = self.baselines['avg_latency']
        
        current_p95 = latency_stats['p95']
        
        if current_p95 > baseline * self.thresholds['latency_spike']:
            spike_factor = current_p95 / baseline
            severity = min((spike_factor - 1.0) / 2.0, 1.0)
            confidence = 0.8  # High confidence for latency metrics
            
            pattern = Pattern(
                pattern_id='',
                pattern_type='latency_spike',
                description=f'P95 latency at {current_p95:.0f}ms ({spike_factor:.1f}x baseline)',
                severity=severity,
                confidence=confidence,
                affected_dimension='overall',
                affected_value='latency',
                metrics={
                    'p50': latency_stats['p50'],
                    'p95': latency_stats['p95'],
                    'p99': latency_stats['p99'],
                    'mean': latency_stats['mean'],
                    'baseline': baseline,
                    'spike_factor': spike_factor
                },
                detected_at=datetime.now(),
                evidence=[
                    f'P95 latency: {current_p95:.0f}ms (baseline: {baseline:.0f}ms)',
                    f'Spike factor: {spike_factor:.1f}x',
                    f'P99 latency: {latency_stats["p99"]:.0f}ms'
                ]
            )
            patterns.append(pattern)
        
        return patterns
    
    def _detect_error_clusters(self, observer) -> List[Pattern]:
        """Detect clusters of similar errors"""
        patterns = []
        top_errors = observer.get_top_errors(n=5)
        
        for error_code, count in top_errors:
            if count >= self.thresholds['error_cluster']:
                total = observer.get_transaction_volume('overall', 'current')
                error_rate = count / max(total, 1)
                
                severity = min(error_rate / 0.1, 1.0)  # 10% error rate = max severity
                confidence = self._calculate_confidence(count, error_rate)
                
                pattern = Pattern(
                    pattern_id='',
                    pattern_type='error_cluster',
                    description=f'Error {error_code} occurring {count} times ({error_rate:.1%} of traffic)',
                    severity=severity,
                    confidence=confidence,
                    affected_dimension='error_code',
                    affected_value=error_code,
                    metrics={
                        'error_count': count,
                        'total_transactions': total,
                        'error_rate': error_rate
                    },
                    detected_at=datetime.now(),
                    evidence=[
                        f'Error code: {error_code}',
                        f'Occurrences: {count}',
                        f'Error rate: {error_rate:.1%}'
                    ]
                )
                patterns.append(pattern)
        
        return patterns
    
    def _detect_geographic_issues(self, observer) -> List[Pattern]:
        """Detect region-specific failures"""
        patterns = []
        
        # Get regional statistics
        regional_stats = observer.stats['by_region']
        
        for region, stats in regional_stats.items():
            if stats['total'] < 10:  # Skip low-volume regions
                continue
            
            success_rate = stats['success'] / stats['total'] if stats['total'] > 0 else 1.0
            
            # Compare to overall success rate
            overall_rate = observer.get_success_rate('overall', 'current')
            degradation = overall_rate - success_rate
            
            if degradation >= 0.20:  # 20% worse than overall
                severity = min(degradation / 0.4, 1.0)
                confidence = self._calculate_confidence(stats['total'], degradation)
                
                pattern = Pattern(
                    pattern_id='',
                    pattern_type='geographic_issue',
                    description=f'Region {region} has {success_rate:.1%} success rate vs {overall_rate:.1%} overall',
                    severity=severity,
                    confidence=confidence,
                    affected_dimension='region',
                    affected_value=region,
                    metrics={
                        'region_success_rate': success_rate,
                        'overall_success_rate': overall_rate,
                        'degradation': degradation,
                        'volume': stats['total']
                    },
                    detected_at=datetime.now(),
                    evidence=[
                        f'Region success rate: {success_rate:.2%}',
                        f'Overall success rate: {overall_rate:.2%}',
                        f'Volume: {stats["total"]} transactions'
                    ]
                )
                patterns.append(pattern)
        
        return patterns
    
    def _calculate_confidence(self, sample_size: int, effect_size: float) -> float:
        """
        Calculate confidence score based on sample size and effect size.
        
        Uses statistical principles: larger samples and stronger effects = higher confidence.
        """
        # Sample size factor (sigmoid function)
        size_confidence = 1 / (1 + math.exp(-0.05 * (sample_size - 50)))
        
        # Effect size factor (linear with saturation)
        effect_confidence = min(effect_size / 0.3, 1.0)
        
        # Combined confidence (geometric mean)
        confidence = math.sqrt(size_confidence * effect_confidence)
        
        return min(max(confidence, 0.0), 1.0)
    
    def generate_hypotheses(self, pattern: Pattern) -> List[Hypothesis]:
        """
        Generate hypotheses about root causes for a detected pattern.
        
        Args:
            pattern: Detected pattern
        
        Returns:
            List of hypotheses with probabilities
        """
        hypotheses = []
        pattern_info = self.pattern_library.get(pattern.pattern_type, {})
        typical_causes = pattern_info.get('typical_causes', [])
        
        if pattern.pattern_type == 'issuer_degradation':
            hypotheses = self._generate_issuer_hypotheses(pattern, typical_causes)
        elif pattern.pattern_type == 'retry_storm':
            hypotheses = self._generate_retry_hypotheses(pattern, typical_causes)
        elif pattern.pattern_type == 'method_fatigue':
            hypotheses = self._generate_method_hypotheses(pattern, typical_causes)
        elif pattern.pattern_type == 'latency_spike':
            hypotheses = self._generate_latency_hypotheses(pattern, typical_causes)
        elif pattern.pattern_type == 'error_cluster':
            hypotheses = self._generate_error_hypotheses(pattern, typical_causes)
        elif pattern.pattern_type == 'geographic_issue':
            hypotheses = self._generate_geographic_hypotheses(pattern, typical_causes)
        
        # Normalize probabilities
        total_prob = sum(h.probability for h in hypotheses)
        if total_prob > 0:
            for h in hypotheses:
                h.probability /= total_prob
        
        return hypotheses
    
    def _generate_issuer_hypotheses(self, pattern: Pattern, typical_causes: List[str]) -> List[Hypothesis]:
        """Generate hypotheses for issuer degradation"""
        hypotheses = []
        metrics = pattern.metrics
        
        # Hypothesis 1: Issuer is down
        down_probability = 0.6 if metrics['current_success_rate'] < 0.20 else 0.3
        hypotheses.append(Hypothesis(
            hypothesis_id='',
            pattern_id=pattern.pattern_id,
            root_cause='issuer_down',
            probability=down_probability,
            supporting_evidence=[
                f'Success rate critically low: {metrics["current_success_rate"]:.1%}',
                f'Sudden degradation of {metrics["degradation"]:.1%}'
            ],
            contradicting_evidence=[
                'Some transactions still succeeding' if metrics['current_success_rate'] > 0.10 else ''
            ],
            created_at=datetime.now()
        ))
        
        # Hypothesis 2: Issuer throttling
        throttle_probability = 0.5 if metrics.get('avg_latency', 0) > 500 else 0.3
        hypotheses.append(Hypothesis(
            hypothesis_id='',
            pattern_id=pattern.pattern_id,
            root_cause='issuer_throttling',
            probability=throttle_probability,
            supporting_evidence=[
                f'Elevated latency: {metrics.get("avg_latency", 0):.0f}ms',
                f'Partial success rate: {metrics["current_success_rate"]:.1%}'
            ],
            contradicting_evidence=[],
            created_at=datetime.now()
        ))
        
        # Hypothesis 3: Network issue
        hypotheses.append(Hypothesis(
            hypothesis_id='',
            pattern_id=pattern.pattern_id,
            root_cause='network_issue',
            probability=0.2,
            supporting_evidence=[
                'Degradation pattern consistent with connectivity issues'
            ],
            contradicting_evidence=[],
            created_at=datetime.now()
        ))
        
        return hypotheses
    
    def _generate_retry_hypotheses(self, pattern: Pattern, typical_causes: List[str]) -> List[Hypothesis]:
        """Generate hypotheses for retry storms"""
        hypotheses = []
        metrics = pattern.metrics
        
        hypotheses.append(Hypothesis(
            hypothesis_id='',
            pattern_id=pattern.pattern_id,
            root_cause='aggressive_retry_config',
            probability=0.5,
            supporting_evidence=[
                f'High retry percentage: {metrics["retry_percentage"]:.1%}',
                f'Low retry efficiency: {metrics["retry_efficiency"]:.1%}'
            ],
            contradicting_evidence=[],
            created_at=datetime.now()
        ))
        
        hypotheses.append(Hypothesis(
            hypothesis_id='',
            pattern_id=pattern.pattern_id,
            root_cause='cascading_failures',
            probability=0.3,
            supporting_evidence=[
                'Retries may be causing additional system load',
                f'Total retries: {metrics["total_retries"]}'
            ],
            contradicting_evidence=[],
            created_at=datetime.now()
        ))
        
        hypotheses.append(Hypothesis(
            hypothesis_id='',
            pattern_id=pattern.pattern_id,
            root_cause='upstream_issue',
            probability=0.2,
            supporting_evidence=[
                'Multiple retries failing suggests upstream problem'
            ],
            contradicting_evidence=[],
            created_at=datetime.now()
        ))
        
        return hypotheses
    
    def _generate_method_hypotheses(self, pattern: Pattern, typical_causes: List[str]) -> List[Hypothesis]:
        """Generate hypotheses for payment method fatigue"""
        return [
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='fraud_detection_triggers',
                probability=0.4,
                supporting_evidence=['Repeated attempts may trigger fraud systems'],
                contradicting_evidence=[],
                created_at=datetime.now()
            ),
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='user_cancellation',
                probability=0.3,
                supporting_evidence=['Users may be canceling after failed retries'],
                contradicting_evidence=[],
                created_at=datetime.now()
            ),
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='method_limits',
                probability=0.3,
                supporting_evidence=['Payment method may have transaction limits'],
                contradicting_evidence=[],
                created_at=datetime.now()
            )
        ]
    
    def _generate_latency_hypotheses(self, pattern: Pattern, typical_causes: List[str]) -> List[Hypothesis]:
        """Generate hypotheses for latency spikes"""
        return [
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='system_load',
                probability=0.4,
                supporting_evidence=[f'Latency spike factor: {pattern.metrics["spike_factor"]:.1f}x'],
                contradicting_evidence=[],
                created_at=datetime.now()
            ),
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='network_congestion',
                probability=0.3,
                supporting_evidence=['Latency affecting all transactions'],
                contradicting_evidence=[],
                created_at=datetime.now()
            ),
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='downstream_slowness',
                probability=0.3,
                supporting_evidence=['Banks/processors may be slow'],
                contradicting_evidence=[],
                created_at=datetime.now()
            )
        ]
    
    def _generate_error_hypotheses(self, pattern: Pattern, typical_causes: List[str]) -> List[Hypothesis]:
        """Generate hypotheses for error clusters"""
        return [
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='specific_error_condition',
                probability=0.6,
                supporting_evidence=[f'Error {pattern.affected_value} highly concentrated'],
                contradicting_evidence=[],
                created_at=datetime.now()
            ),
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='configuration_issue',
                probability=0.4,
                supporting_evidence=['Systematic error pattern suggests config problem'],
                contradicting_evidence=[],
                created_at=datetime.now()
            )
        ]
    
    def _generate_geographic_hypotheses(self, pattern: Pattern, typical_causes: List[str]) -> List[Hypothesis]:
        """Generate hypotheses for geographic issues"""
        return [
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='regional_network_outage',
                probability=0.5,
                supporting_evidence=[f'Region {pattern.affected_value} significantly degraded'],
                contradicting_evidence=[],
                created_at=datetime.now()
            ),
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='regional_bank_issue',
                probability=0.3,
                supporting_evidence=['May affect specific banks in region'],
                contradicting_evidence=[],
                created_at=datetime.now()
            ),
            Hypothesis(
                hypothesis_id='',
                pattern_id=pattern.pattern_id,
                root_cause='compliance_block',
                probability=0.2,
                supporting_evidence=['Could be regulatory/compliance issue'],
                contradicting_evidence=[],
                created_at=datetime.now()
            )
        ]
    
    def update_baselines(self, observer):
        """Update baseline metrics based on recent healthy performance"""
        # Update overall baseline
        success_rate = observer.get_success_rate('overall', 'current')
        if success_rate >= 0.90:  # Only update if healthy
            self.baselines['overall_success_rate'] = (
                0.9 * self.baselines['overall_success_rate'] + 0.1 * success_rate
            )
        
        # Update issuer baselines
        for issuer, health in observer.get_issuer_health().items():
            if health['success_rate'] >= 0.90 and health['volume'] >= 20:
                current = self.baselines['issuer_success_rates'][issuer]
                self.baselines['issuer_success_rates'][issuer] = (
                    0.9 * current + 0.1 * health['success_rate']
                )
        
        # Update latency baseline
        latency_stats = observer.get_latency_stats('overall')
        if latency_stats['mean'] > 0:
            self.baselines['avg_latency'] = (
                0.9 * self.baselines['avg_latency'] + 0.1 * latency_stats['mean']
            )
