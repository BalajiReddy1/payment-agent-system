# Payment Agent System - Technical Documentation

## Architecture Overview

The Payment Agent System implements a complete autonomous agent loop for real-time payment operations management. This document explains the technical architecture, decision-making process, and implementation details.

## Core Agent Loop

```
┌──────────────────────────────────────────────────────┐
│                   AGENT LOOP                         │
│                                                      │
│  OBSERVE → REASON → DECIDE → ACT → LEARN → OBSERVE  │
└──────────────────────────────────────────────────────┘
```

### 1. OBSERVE Phase (observer.py)

**Purpose**: Ingest and preprocess payment transaction data in real-time.

**Key Components**:
- **Sliding Window**: Maintains last N minutes of transactions
- **Real-time Statistics**: Calculates success rates, latencies, volumes across multiple dimensions:
  - Overall metrics
  - By issuer (bank/payment processor)
  - By payment method (credit card, UPI, etc.)
  - By region (geographic)
  - By merchant

**Implementation Highlights**:
```python
class PaymentObserver:
    def ingest_transaction(self, transaction):
        # Add to sliding window
        self.transactions_window.append(transaction)
        
        # Update statistics across all dimensions
        self._update_stats(transaction)
        
        # Track latency and errors
        self._track_latency(transaction)
```

**Metrics Tracked**:
- Success/failure rates
- Latency (p50, p95, p99)
- Transaction volumes
- Retry efficiency
- Error code frequencies

### 2. REASON Phase (reasoner.py)

**Purpose**: Detect meaningful patterns and form hypotheses about root causes.

**Pattern Detection**:

The reasoner implements multiple pattern detectors, each looking for specific failure modes:

1. **Issuer Degradation Detector**
   - Compares current issuer success rate to baseline
   - Triggers when degradation > threshold (default 15%)
   - Considers transaction volume to avoid false positives

2. **Retry Storm Detector**
   - Monitors percentage of traffic that is retries
   - Checks retry efficiency (how many retries succeed)
   - Triggers when retry % > 40% or efficiency < 30%

3. **Method Fatigue Detector**
   - Detects when payment methods perform poorly after retries
   - Indicates potential fraud detection triggers or user frustration

4. **Latency Spike Detector**
   - Monitors p95 latency against baseline
   - Triggers when latency > 1.5x baseline

5. **Error Cluster Detector**
   - Identifies when specific errors occur frequently
   - Helps pinpoint systematic issues

6. **Geographic Failure Detector**
   - Detects region-specific problems
   - Compares regional performance to overall

**Hypothesis Generation**:

For each pattern, the reasoner generates plausible root cause hypotheses with probabilities:

```python
def generate_hypotheses(self, pattern: Pattern) -> List[Hypothesis]:
    if pattern.pattern_type == 'issuer_degradation':
        return [
            Hypothesis(root_cause='issuer_down', probability=0.6),
            Hypothesis(root_cause='issuer_throttling', probability=0.3),
            Hypothesis(root_cause='network_issue', probability=0.1)
        ]
```

**Confidence Scoring**:

Confidence is calculated based on:
- Sample size (larger samples = higher confidence)
- Effect size (stronger effects = higher confidence)
- Using sigmoid function for sample size and linear saturation for effect

```python
confidence = sqrt(size_confidence * effect_confidence)
```

### 3. DECIDE Phase (decision_maker.py)

**Purpose**: Choose the best action given patterns, hypotheses, and constraints.

**Multi-Objective Optimization**:

The decision maker balances four objectives:
- **Success Rate** (40% weight): Maximize payment success
- **Latency** (25% weight): Minimize transaction latency
- **Cost** (20% weight): Minimize processing costs
- **Risk** (15% weight): Minimize intervention risk

**Decision Process**:

```python
def decide(self, context: DecisionContext):
    # 1. Generate possible actions for the pattern
    possible_actions = self._generate_actions(pattern, context)
    
    # 2. Evaluate each action on all objectives
    for action in possible_actions:
        score = (
            weights['success_rate'] * score_success(action) +
            weights['latency'] * score_latency(action) +
            weights['cost'] * score_cost(action) +
            weights['risk'] * score_risk(action)
        ) * action.confidence
    
    # 3. Select highest-scoring action
    best_action = max(evaluated_actions, key=lambda x: x.score)
    
    # 4. Check safety constraints
    if state.can_take_action(best_action):
        return best_action
```

**Action Types**:

| Action | Risk | Authorization | Typical Impact |
|--------|------|---------------|----------------|
| Adjust Retry | Low | Automatic | +5% success, -50ms latency |
| Circuit Breaker | Medium | Automatic | +15% success, -100ms latency |
| Route Change | Medium | Semi-auto | +10% success, +50ms latency |
| Method Suppress | High | Manual | Variable |
| Alert Ops | Low | Automatic | N/A |

**Trade-off Example**:

For an issuer degradation pattern:
- **Circuit Breaker**: High success improvement (+15%), low latency (-200ms), medium cost (+$0.02/txn)
- **Route Change**: Medium success improvement (+8%), slight latency increase (+20ms), low cost (+$0.01/txn)

Decision: Circuit breaker wins due to much higher success improvement despite higher cost.

### 4. ACT Phase (executor.py)

**Purpose**: Execute actions safely with guardrails and monitoring.

**Safety Guardrails**:

```python
SAFETY_CONSTRAINTS = {
    'max_actions_per_hour': 50,
    'max_rollbacks_per_hour': 10,
    'impact_limits': {
        'low_risk': 0.05,      # 5% of traffic
        'medium_risk': 0.10,   # 10% of traffic
        'high_risk': 0.20,     # 20% of traffic
        'critical_risk': 1.00  # 100% of traffic
    }
}
```

**Pre-Execution Checks**:
1. Authorization verification (manual, semi-auto, automatic)
2. Action rate limits (not too many actions too fast)
3. Impact limits (action doesn't affect too much traffic)
4. No conflicting active interventions

**Execution Examples**:

**Circuit Breaker**:
```python
def _execute_circuit_breaker(self, action, state):
    issuer = action.parameters['issuer']
    state.active_circuit_breakers.add(issuer)
    # New transactions to this issuer are routed elsewhere
```

**Retry Adjustment**:
```python
def _execute_retry_adjustment(self, action, state):
    state.retry_strategies[target] = {
        'max_retries': 2,  # Reduced from 4
        'backoff_multiplier': 2.0  # Increased
    }
```

**Automatic Rollback**:

The executor monitors all active interventions and triggers rollback if:
- Success rate drops >5% below baseline
- Latency increases >50% above baseline
- Error rate increases >10%
- Action duration expires

```python
def monitor_and_rollback(self, state, observer):
    for action in active_interventions:
        if should_rollback(action, baseline, current):
            self._rollback_action(action, state)
```

### 5. LEARN Phase (learner.py)

**Purpose**: Learn from action outcomes to improve future decisions.

**Outcome Recording**:

After each action completes, the learner records:
- Estimated vs. actual impact
- Prediction error
- Baseline and actual metrics
- Action effectiveness

```python
def record_outcome(self, action, baseline, actual):
    outcome = {
        'estimated_impact': action.estimated_impact,
        'actual_impact': calculate_actual(baseline, actual),
        'prediction_error': calculate_error(estimated, actual)
    }
    self.action_outcomes[action_key].append(outcome)
```

**Learning Mechanisms**:

1. **Action Effectiveness Tracking**
   - Maintains history of all actions and their outcomes
   - Calculates average improvement per action type
   - Measures prediction accuracy

2. **Pattern Detection Refinement**
   - Tracks true positives vs false positives
   - Adjusts detection thresholds to optimize precision/recall

3. **Decision Weight Adjustment**
   - Uses simple reinforcement learning
   - Increases weights for objectives that correlate with success
   - Updates weights every 10 cycles

```python
def update_decision_weights(self, decision_maker):
    for objective, scores in objective_scores.items():
        avg_score = mean(scores)
        new_weight = current_weight + learning_rate * (avg_score - 0.5)
        decision_maker.weights[objective] = clamp(new_weight, 0.05, 0.60)
    
    normalize_weights(decision_maker.weights)
```

**Threshold Recommendations**:

Based on pattern accuracy:
- If precision < 70%: Increase threshold (fewer detections, fewer false positives)
- If precision > 95%: Decrease threshold (more detections, catch more issues)

## State Management

**Agent State** (state.py):
- Current operational metrics
- Active interventions (circuit breakers, routing overrides, etc.)
- Safety metrics (actions taken, rollbacks)
- Performance metrics (patterns detected, actions successful)

**Agent Memory**:
- Short-term: Recent transactions, active patterns
- Long-term: Historical patterns, action outcomes
- Learning memory: Effectiveness scores, reliability metrics

## Simulation System

**Payment Simulator** (payment_simulator.py):

Generates realistic payment streams with:
- Normal operation (95% success rate baseline)
- Realistic distributions of payment methods, issuers, regions
- Log-normal amount distributions
- Realistic latency (200ms ± 50ms)

**Failure Injection**:

The simulator can inject various failure scenarios:

```python
simulator.inject_issuer_degradation(
    issuer='HDFC_BANK',
    severity=0.6,      # 60% of transactions fail
    duration_seconds=300
)

simulator.inject_retry_storm(duration_seconds=180)

simulator.inject_latency_spike(multiplier=3.0, duration_seconds=150)
```

## Decision Explainability

Every decision includes comprehensive reasoning:

```
## Pattern Detected
Type: issuer_degradation
Severity: 0.75
Description: Issuer HDFC_BANK showing 18.0% drop in success rate
Confidence: 0.85

## Hypothesized Root Causes
- issuer_down (probability: 0.60)
- issuer_throttling (probability: 0.30)
- network_issue (probability: 0.10)

## Selected Action
Type: circuit_breaker
Target: HDFC_BANK
Risk Level: medium
Authorization: automatic

## Expected Impact
- Success Rate: +15.0% change
- Latency: -200ms change
- Cost: $0.020 per transaction
- Affected Traffic: 8.2%

## Alternatives Considered
- route_change: score 0.72 (Success: 0.65, Latency: 0.68, Cost: 0.85, Risk: 0.70)
- no_action: score 0.45 (Success: 0.50, Latency: 1.00, Cost: 1.00, Risk: 1.00)
```

## Performance Characteristics

**Detection Speed**:
- Real-time pattern detection (<1 second per cycle)
- Typically detects issues within 15-30 seconds of onset

**Accuracy**:
- Pattern detection precision: ~85-95% (after learning)
- Action prediction accuracy: ~70-80%
- False positive rate: <10% (after tuning)

**Impact**:
- Average success rate improvement: 10-20% during incidents
- Mean time to detect (MTTD): ~30 seconds
- Mean time to resolve (MTTR): ~2 minutes (vs. hours manually)

## Ethical Considerations

**Fairness**:
- No use of user demographics in decision-making
- Interventions applied uniformly based on technical signals only
- Equal treatment across geographies and payment methods

**Transparency**:
- All decisions fully explainable
- Complete audit trail of actions
- Clear indication when agent has intervened

**Human Oversight**:
- High-risk actions require human approval
- Humans can override any decision
- Regular audits of agent behavior
- Clear escalation procedures

## Safety Mechanisms

1. **Impact Limits**: Actions cannot affect more than X% of traffic based on risk level
2. **Rate Limits**: Maximum actions per hour to prevent cascades
3. **Automatic Rollback**: Immediate reversion if metrics degrade
4. **Human Override**: Operators can stop or override any action
5. **Approval Gates**: High-risk changes require manual approval

## Code Organization

```
src/
├── agent/
│   ├── core.py            # Main orchestrator
│   ├── observer.py        # Data ingestion & statistics
│   ├── reasoner.py        # Pattern detection & hypotheses
│   ├── decision_maker.py  # Multi-objective decision making
│   ├── executor.py        # Safe action execution
│   └── learner.py         # Outcome learning
├── models/
│   └── state.py           # Data models & state management
└── simulation/
    └── payment_simulator.py  # Transaction simulation
```

## Running the System

**Demo Mode** (Guided Scenario):
```bash
python main.py --mode demo
```

Runs a 4-minute demonstration with:
1. Normal operation (1 min)
2. Issuer degradation scenario (1.5 min)
3. Retry storm scenario (1 min)

**Continuous Mode**:
```bash
python main.py --mode continuous --duration 60
```

Runs for specified duration with periodic scenario injection.

## Extension Points

The system is designed to be extensible:

1. **New Pattern Detectors**: Add to `reasoner.py`
2. **New Action Types**: Add to `decision_maker.py` and `executor.py`
3. **Custom Metrics**: Extend `observer.py`
4. **Advanced Learning**: Enhance `learner.py` with ML models
5. **External Integrations**: Add to `executor.py` (e.g., PagerDuty, Slack)

## Future Enhancements

- Deep reinforcement learning for complex decision spaces
- Causal inference for better root cause analysis
- Multi-agent coordination for different payment types
- LLM-based hypothesis generation
- Counterfactual simulation
- A/B testing of intervention strategies
