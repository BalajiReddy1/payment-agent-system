# Quick Start Guide

## Installation

### Prerequisites
- Python 3.10 or higher
- pip package manager

### Setup

1. **Clone the repository**:
```bash
git clone <your-repo-url>
cd payment-agent-system
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Verify installation**:
```bash
python -c "import numpy, scipy; print('Dependencies installed successfully')"
```

## Running the Agent

### Option 1: Demo Mode (Recommended for First Run)

Run the guided demonstration that showcases all agent capabilities:

```bash
python main.py --mode demo
```

**What happens**:
- Phase 1 (60s): Normal payment processing - establishes baseline
- Phase 2 (90s): Issuer degradation - agent detects and activates circuit breaker
- Phase 3 (60s): Retry storm - agent adjusts retry strategies

**Expected output**:
```
=================================================================
AGENTIC AI PAYMENT OPERATIONS SYSTEM - DEMONSTRATION
=================================================================

Initializing payment agent...
Initializing payment simulator...

=================================================================
PHASE 1: NORMAL OPERATION (60 seconds)
=================================================================
Simulating healthy payment processing...

[12:34:56] Cycle #1: 96.00% success rate, 423 transactions
[12:35:11] Cycle #2: 95.80% success rate, 861 transactions
...

=================================================================
PHASE 2: ISSUER DEGRADATION SCENARIO (90 seconds)
=================================================================
🔥 Injected issuer degradation: HDFC_BANK at 60% severity for 90s

[12:36:01] Cycle #5:
  Success Rate: 82.40%
  Patterns Detected: 1
    - issuer_degradation: Issuer HDFC_BANK showing 18.0% drop... (severity: 0.75)
  Action Taken: circuit_breaker on HDFC_BANK
    Expected Impact: +15.0% success rate
...
```

### Option 2: Continuous Mode

Run the agent continuously with periodic scenario injection:

```bash
python main.py --mode continuous --duration 60
```

This runs for 60 minutes (adjust `--duration` as needed) with random failure scenarios injected every 5 minutes.

## Understanding the Output

### Key Metrics to Watch

**Success Rate**: 
- Normal: 95-97%
- During incident: May drop to 75-90%
- After intervention: Should recover to 90-95%

**Patterns Detected**:
- `issuer_degradation`: Specific bank/issuer having problems
- `retry_storm`: Too many retries causing cascading failures
- `method_fatigue`: Payment method degrading after retries
- `latency_spike`: Unusual increase in processing time
- `error_cluster`: Specific error occurring frequently

**Actions Taken**:
- `circuit_breaker`: Stop routing to failing issuer
- `adjust_retry`: Change retry strategy (max attempts, backoff)
- `route_change`: Redirect traffic to alternative processors
- `alert_ops`: Notify operations team

### Example Agent Decision

```
[12:36:15] Cycle #6:
  Patterns Detected: 1
    - issuer_degradation: Issuer HDFC_BANK showing 18.0% drop in success rate (severity: 0.75)
  
  Hypotheses:
    - issuer_down (60% probability)
    - issuer_throttling (30% probability)
    - network_issue (10% probability)
  
  Action Taken: circuit_breaker on HDFC_BANK
    Expected Impact: +15.0% success rate, -200ms latency
    Risk Level: medium
    Authorization: automatic
```

## Monitoring Agent Performance

At the end of each demo, you'll see a comprehensive status report:

```
Final Agent Status:
  Total Cycles: 14
  Patterns Detected: 3
  Actions Executed: 2
  Success Rate: 2/2

Active Interventions:
  - circuit_breaker on HDFC_BANK

Learning Summary:
  Outcomes Recorded: 2
  Most Effective Actions:
    - circuit_breaker_HDFC_BANK: +14.8% avg improvement (2 samples)
```

## Customizing Scenarios

You can modify `main.py` to create custom scenarios:

```python
# In the demo function, add your own scenario:

# Inject a specific failure
simulator.inject_issuer_degradation(
    issuer='ICICI_BANK',
    severity=0.7,  # 70% failure rate
    duration_seconds=120  # 2 minutes
)

# Inject latency spike
simulator.inject_latency_spike(
    multiplier=4.0,  # 4x normal latency
    duration_seconds=180
)

# Inject payment method issues
simulator.inject_method_fatigue(
    method=PaymentMethod.CREDIT_CARD,
    severity=0.5,
    duration_seconds=200
)
```

## Verifying Agent Capabilities

The agent demonstrates the complete observe-reason-decide-act-learn loop:

### ✅ Observe
- Real-time ingestion of payment transactions
- Sliding window statistics across multiple dimensions
- Latency tracking, error monitoring, retry analysis

### ✅ Reason
- Pattern detection (6 different pattern types)
- Hypothesis generation with probabilities
- Confidence scoring based on evidence

### ✅ Decide
- Multi-objective optimization (success, latency, cost, risk)
- Trade-off analysis between alternatives
- Risk-based authorization levels

### ✅ Act
- Safe execution with pre-flight checks
- Multiple action types (circuit breakers, retry tuning, routing)
- Automatic rollback on negative outcomes

### ✅ Learn
- Action outcome tracking
- Pattern accuracy refinement
- Decision weight adaptation
- Threshold recommendations

## Troubleshooting

**Issue**: Import errors
```
ModuleNotFoundError: No module named 'numpy'
```
**Solution**: Install requirements
```bash
pip install -r requirements.txt
```

**Issue**: Agent not detecting patterns
**Cause**: Thresholds may be too high or scenarios too mild
**Solution**: Increase failure severity in simulator
```python
simulator.inject_issuer_degradation(issuer='X', severity=0.8)  # Increase from 0.6
```

**Issue**: Too many rollbacks
**Cause**: Actions may be too aggressive or rollback thresholds too sensitive
**Solution**: Adjust thresholds in `executor.py`:
```python
self.rollback_thresholds = {
    'success_rate_drop': 0.08,  # Increase from 0.05
    ...
}
```

## Next Steps

1. **Read ARCHITECTURE.md** for deep technical details
2. **Examine src/agent/core.py** to understand the main loop
3. **Customize decision weights** in `decision_maker.py`
4. **Add new patterns** in `reasoner.py`
5. **Extend with real integrations** (databases, monitoring systems, etc.)

## Getting Help

Check the comprehensive documentation:
- `README.md` - Project overview and features
- `ARCHITECTURE.md` - Technical architecture and implementation
- Code comments - Detailed inline documentation

For questions about specific components:
- Observer: See `src/agent/observer.py` docstrings
- Reasoner: See `src/agent/reasoner.py` docstrings
- Decision Maker: See `src/agent/decision_maker.py` docstrings
- Executor: See `src/agent/executor.py` docstrings
- Learner: See `src/agent/learner.py` docstrings
