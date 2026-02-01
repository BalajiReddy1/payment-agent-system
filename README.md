# 🏦 Agentic AI for Smart Payment Operations

An intelligent, autonomous payment operations agent that monitors real-time payment transactions, identifies failure patterns, makes context-aware decisions, and executes interventions with full explainability and safety guardrails.

## 🎯 Problem Statement

Payment failures cost fintech companies millions in lost revenue. Traditional rule-based systems react too slowly and can't handle the complexity of modern payment ecosystems with hundreds of banks, issuers, payment methods, and failure modes.

This **agentic AI system** acts as a real-time payment operations manager that:
- ✅ Continuously observes payment signals
- ✅ Reasons about emerging patterns with hypothesis generation
- ✅ Makes informed decisions under uncertainty
- ✅ Takes autonomous action within safety guardrails
- ✅ Learns from outcomes to improve future decisions
- ✅ Explains its reasoning at any point

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Payment Agent System                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   OBSERVE ──▶ REASON ──▶ DECIDE ──▶ ACT ──▶ LEARN              │
│      │          │          │         │        │                 │
│      ▼          ▼          ▼         ▼        ▼                 │
│   Observer   Reasoner   Decision  Executor  Learner             │
│   .py        .py        Maker.py   .py       .py                │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │              Safety Module (src/safety/)                │   │
│   │   • Guardrails (authorization levels)                   │   │
│   │   • Rollback (automatic reversion)                      │   │
│   │   • Audit (decision trail)                              │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## ✨ Key Features

### 1. Real-time Pattern Detection
- Issuer degradation detection
- Retry storm identification
- Payment method fatigue analysis
- Latency spike detection
- Multi-dimensional anomaly detection

### 2. Context-Aware Decision Making
- Multi-objective optimization (success rate, latency, cost, risk)
- Hypothesis generation with confidence scoring
- Trade-off analysis with full explainability

### 3. Safety Guardrails (3 Authorization Levels)
| Level | Actions | Human Approval |
|-------|---------|----------------|
| **AUTOMATIC** | Retry tuning, Alerts | ❌ Not required |
| **SEMI-AUTO** | Circuit breaker, Routing | ⚡ Quick approval |
| **MANUAL** | Method suppression | ✅ Required |

### 4. Automatic Rollback
If an action causes harm, the system automatically rolls back:
- Success rate drops > 5% → Rollback
- Latency increases > 50% → Rollback
- Error rate increases > 10% → Rollback

### 5. Decision Explainability
Every decision includes:
- **Context**: What data triggered the analysis
- **Reasoning**: Why this pattern is significant
- **Options**: What actions were considered
- **Decision**: What was chosen and why
- **Expected Impact**: Predicted outcomes

### 6. Continuous Learning
- Updates action weights based on outcomes
- Tracks pattern detection accuracy
- Refines decision strategies over time

## 📁 Project Structure

```
payment-agent-system/
├── src/
│   ├── agent/
│   │   ├── core.py              # Main agent orchestrator
│   │   ├── observer.py          # Data ingestion & statistics
│   │   ├── reasoner.py          # Pattern detection & hypotheses
│   │   ├── decision_maker.py    # Multi-objective decision engine
│   │   ├── executor.py          # Action execution with guardrails
│   │   └── learner.py           # Learning from outcomes
│   ├── models/
│   │   └── state.py             # Agent state & memory management
│   ├── safety/
│   │   ├── guardrails.py        # Authorization levels & limits
│   │   ├── rollback.py          # Automatic rollback logic
│   │   └── audit.py             # Decision audit trail
│   ├── simulation/
│   │   └── payment_simulator.py # Transaction & failure simulation
│   └── utils/
│       ├── benchmark.py         # Performance benchmarking
│       └── config_loader.py     # YAML config loader
├── api/
│   └── main.py                  # FastAPI REST endpoints
├── dashboard/
│   ├── app.py                   # Streamlit dashboard
│   ├── components.py            # UI components
│   └── styles.py                # Dark theme CSS
├── config/
│   ├── agent_config.yaml        # Agent behavior settings
│   ├── safety_rules.yaml        # Safety guardrails config
│   └── simulation_config.yaml   # Simulator parameters
├── data/
│   ├── sample_payments.json     # Sample transaction data
│   └── sample_payments.csv      # CSV format
├── Dockerfile                   # Container image
├── docker-compose.yml           # Multi-service orchestration
├── requirements.txt             # Python dependencies
└── README.md
```

## 🚀 Quick Start

### Option 1: Local Development

```bash
# Clone and setup
cd payment-agent-system
python -m venv venv
.\venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Run the Dashboard
streamlit run dashboard/app.py

# Run the API (separate terminal)
uvicorn api.main:app --reload

# Run Demo Mode
python main.py --mode demo
```

### Option 2: Docker

```bash
# Start all services
docker-compose up --build

# Access:
# Dashboard: http://localhost:8501
# API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

## 📊 Dashboard Features

| Panel | Description |
|-------|-------------|
| **KPI Cards** | Success rate, latency, transactions, actions |
| **Health Gauge** | Real-time system health (0-100) |
| **Explainability** | WHY patterns detected, WHAT actions taken |
| **Trend Charts** | Success rate & latency over time |
| **Issuer Health** | Per-issuer success rates (color-coded) |
| **Patterns** | Detected anomalies with confidence |
| **Interventions** | Active agent interventions |
| **Safety Guardrails** | Authorization levels & limits |
| **Decision Log** | Recent agent decisions |
| **Scenario Injection** | Simulate failures (sidebar) |

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Agent status & metrics |
| `/cycle` | POST | Trigger analysis cycle |
| `/transactions` | POST | Submit transactions |
| `/scenarios/inject` | POST | Inject failure scenario |
| `/scenarios/clear` | DELETE | Clear active scenarios |
| `/scenarios` | GET | List active scenarios |

## ⚙️ Configuration

### Agent Config (`config/agent_config.yaml`)
```yaml
thresholds:
  success_rate:
    warning: 0.90
    critical: 0.80
  latency:
    warning: 500
    critical: 1000
```

### Safety Rules (`config/safety_rules.yaml`)
```yaml
guardrails:
  max_traffic_impact_percent: 15
  max_actions_per_hour: 10
  max_rollbacks_per_hour: 3
authorization_levels:
  automatic: [adjust_retry, send_alert]
  semi_automatic: [circuit_breaker, route_change]
  manual: [method_suppress]
```

## 📈 Performance

| Metric | Value |
|--------|-------|
| Avg Cycle Time | ~50ms |
| Throughput | ~850 txn/sec |
| Pattern Detection | ~5ms |
| Memory (Peak) | ~45 MB |

## 🛡️ Why This is Truly Agentic

| Agentic Trait | Implementation |
|---------------|----------------|
| **Autonomy** | Auto-executes low-risk actions |
| **State/Memory** | `AgentState`, `AgentMemory` |
| **Goal-Directed** | Multi-objective optimization |
| **Reasoning** | Hypothesis generation |
| **Tool Use** | Circuit breakers, routing, retries |
| **Learning** | Weight updates from outcomes |
| **Explainability** | Full decision trails |
| **Safety** | 3-tier authorization, auto-rollback |

## 📄 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Detailed technical architecture
- [QUICKSTART.md](QUICKSTART.md) - Getting started guide
- [PERFORMANCE.md](PERFORMANCE.md) - Benchmarks and metrics
- [SUBMISSION.md](SUBMISSION.md) - Hackathon submission details

## 🧑‍💻 Technology Stack

- **Python 3.11** - Core agent logic
- **Streamlit** - Real-time dashboard
- **FastAPI** - REST API
- **Plotly** - Interactive visualizations
- **Docker** - Containerization
- **YAML** - Configuration management

## 📝 License

MIT License - See LICENSE file for details.
