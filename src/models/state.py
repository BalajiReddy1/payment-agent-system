"""
Agent State and Data Models
Defines the core data structures for the payment agent system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set
from uuid import uuid4


class PaymentStatus(Enum):
    """Payment transaction status"""
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    RETRY = "retry"


class PaymentMethod(Enum):
    """Payment method types"""
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    UPI = "upi"
    NET_BANKING = "net_banking"
    WALLET = "wallet"


class ActionType(Enum):
    """Types of actions the agent can take"""
    ADJUST_RETRY = "adjust_retry"
    CIRCUIT_BREAKER = "circuit_breaker"
    ROUTE_CHANGE = "route_change"
    METHOD_SUPPRESS = "method_suppress"
    ALERT_OPS = "alert_ops"
    NO_ACTION = "no_action"


class RiskLevel(Enum):
    """Risk levels for actions"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AuthorizationLevel(Enum):
    """Authorization required for actions"""
    AUTOMATIC = "automatic"
    SEMI_AUTOMATIC = "semi_automatic"
    MANUAL = "manual"


@dataclass
class PaymentTransaction:
    """Represents a single payment transaction"""
    transaction_id: str
    timestamp: datetime
    amount: float
    currency: str
    payment_method: PaymentMethod
    issuer: str
    merchant_id: str
    status: PaymentStatus
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    retry_count: int = 0
    is_retry: bool = False
    original_transaction_id: Optional[str] = None
    region: str = "unknown"
    processor: str = "default"
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'transaction_id': self.transaction_id,
            'timestamp': self.timestamp.isoformat(),
            'amount': self.amount,
            'currency': self.currency,
            'payment_method': self.payment_method.value,
            'issuer': self.issuer,
            'merchant_id': self.merchant_id,
            'status': self.status.value,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'latency_ms': self.latency_ms,
            'retry_count': self.retry_count,
            'is_retry': self.is_retry,
            'original_transaction_id': self.original_transaction_id,
            'region': self.region,
            'processor': self.processor
        }


@dataclass
class Pattern:
    """Detected pattern in payment data"""
    pattern_id: str
    pattern_type: str
    description: str
    severity: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    affected_dimension: str  # issuer, method, region, etc.
    affected_value: str
    metrics: Dict[str, float]
    detected_at: datetime
    evidence: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.pattern_id:
            self.pattern_id = str(uuid4())


@dataclass
class Hypothesis:
    """A hypothesis about why a pattern is occurring"""
    hypothesis_id: str
    pattern_id: str
    root_cause: str
    probability: float
    supporting_evidence: List[str]
    contradicting_evidence: List[str]
    created_at: datetime
    
    def __post_init__(self):
        if not self.hypothesis_id:
            self.hypothesis_id = str(uuid4())


@dataclass
class Action:
    """An action the agent can take"""
    action_id: str
    action_type: ActionType
    target: str  # What the action affects (issuer_id, method, etc.)
    parameters: Dict[str, any]
    risk_level: RiskLevel
    authorization_level: AuthorizationLevel
    estimated_impact: Dict[str, float]
    reasoning: str
    confidence: float
    created_at: datetime
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, approved, executed, completed, rolled_back
    approver: Optional[str] = None
    actual_impact: Optional[Dict[str, float]] = None
    rollback_action_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.action_id:
            self.action_id = str(uuid4())


@dataclass
class AgentMemory:
    """Agent's memory of patterns, actions, and outcomes"""
    
    # Short-term memory (current session)
    recent_transactions: List[PaymentTransaction] = field(default_factory=list)
    active_patterns: List[Pattern] = field(default_factory=list)
    pending_actions: List[Action] = field(default_factory=list)
    
    # Long-term memory (persistent)
    known_patterns: Dict[str, Pattern] = field(default_factory=dict)
    action_history: List[Action] = field(default_factory=list)
    pattern_effectiveness: Dict[str, float] = field(default_factory=dict)
    
    # Learning memory
    action_outcomes: Dict[str, Dict[str, float]] = field(default_factory=dict)
    issuer_reliability: Dict[str, float] = field(default_factory=dict)
    method_performance: Dict[str, float] = field(default_factory=dict)
    
    def add_transaction(self, transaction: PaymentTransaction, max_recent: int = 10000):
        """Add transaction to recent memory"""
        self.recent_transactions.append(transaction)
        if len(self.recent_transactions) > max_recent:
            self.recent_transactions = self.recent_transactions[-max_recent:]
    
    def add_pattern(self, pattern: Pattern):
        """Add detected pattern"""
        self.active_patterns.append(pattern)
        self.known_patterns[pattern.pattern_id] = pattern
    
    def add_action(self, action: Action):
        """Add action to memory"""
        self.pending_actions.append(action)
        self.action_history.append(action)
    
    def update_action_outcome(self, action_id: str, outcome: Dict[str, float]):
        """Update the outcome of an executed action"""
        self.action_outcomes[action_id] = outcome
    
    def get_similar_patterns(self, pattern: Pattern, max_results: int = 5) -> List[Pattern]:
        """Find similar patterns from history"""
        similar = []
        for known_pattern in self.known_patterns.values():
            if (known_pattern.pattern_type == pattern.pattern_type and
                known_pattern.affected_dimension == pattern.affected_dimension):
                similar.append(known_pattern)
        return similar[:max_results]


@dataclass
class AgentState:
    """Current state of the payment agent"""
    
    # Operational state
    is_active: bool = True
    last_update: datetime = field(default_factory=datetime.now)
    
    # Performance metrics
    overall_success_rate: float = 0.95
    average_latency_ms: float = 200.0
    total_transactions: int = 0
    successful_transactions: int = 0
    failed_transactions: int = 0
    
    # Current conditions
    active_circuit_breakers: Set[str] = field(default_factory=set)
    suppressed_methods: Set[str] = field(default_factory=set)
    retry_strategies: Dict[str, Dict] = field(default_factory=dict)
    routing_overrides: Dict[str, str] = field(default_factory=dict)
    
    # Safety metrics
    actions_taken_last_hour: int = 0
    rollbacks_last_hour: int = 0
    human_overrides_last_hour: int = 0
    
    # Agent performance
    patterns_detected: int = 0
    false_positives: int = 0
    true_positives: int = 0
    actions_executed: int = 0
    actions_successful: int = 0
    
    def update_metrics(self, transactions: List[PaymentTransaction]):
        """Update state metrics from transactions"""
        self.total_transactions = len(transactions)
        self.successful_transactions = sum(
            1 for t in transactions if t.status == PaymentStatus.SUCCESS
        )
        self.failed_transactions = sum(
            1 for t in transactions if t.status == PaymentStatus.FAILED
        )
        
        if self.total_transactions > 0:
            self.overall_success_rate = self.successful_transactions / self.total_transactions
        
        latencies = [t.latency_ms for t in transactions if t.latency_ms > 0]
        if latencies:
            self.average_latency_ms = sum(latencies) / len(latencies)
        
        self.last_update = datetime.now()
    
    def can_take_action(self, action: Action) -> tuple[bool, str]:
        """Check if action is allowed based on safety constraints"""
        # Check hourly action limit
        if self.actions_taken_last_hour >= 50:
            return False, "Hourly action limit reached"
        
        # Check rollback rate
        if self.rollbacks_last_hour >= 10:
            return False, "Too many rollbacks in last hour"
        
        # Check if high-risk action and recent failures
        if action.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            if self.rollbacks_last_hour >= 3:
                return False, "High-risk action blocked due to recent rollbacks"
        
        return True, "Action allowed"


@dataclass
class DecisionContext:
    """Context for making a decision"""
    pattern: Pattern
    hypotheses: List[Hypothesis]
    available_actions: List[Action]
    current_state: AgentState
    historical_outcomes: Dict[str, Dict[str, float]]
    constraints: Dict[str, any]
    
    def __post_init__(self):
        if self.constraints is None:
            self.constraints = {}
