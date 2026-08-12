# 🏦 Agentic AI for Smart Payment Operations

An intelligent, autonomous payment operations system that monitors real-time payment transactions, detects failure patterns, reasons about root causes, and executes corrective interventions — powered by **Google Gemini 2.5 Flash** with native function-calling and a full **Model Context Protocol (MCP)** tool layer.

---

## 🎯 Problem Statement

Payment failures cost fintech companies millions in lost revenue. Traditional rule-based systems react too slowly and can't handle the complexity of modern payment ecosystems with hundreds of banks, issuers, payment methods, and failure modes.

This **agentic AI system** acts as a real-time payment operations manager that:
- ✅ Continuously observes payment signals across issuers, methods, and geographies
- ✅ Reasons about emerging patterns with hypothesis generation
- ✅ Deploys a **Gemini 2.5 Flash** LLM brain for autonomous decision-making
- ✅ Executes real-time interventions via native function-calling
- ✅ Maintains safety guardrails with 3-tier authorization and auto-rollback
- ✅ Learns from outcomes to improve future decisions
- ✅ Explains every decision with full audit trail

---

## 🏗️ Architecture

The system follows a **"Brain + Hands"** architecture:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      Payment Agent System                                │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌─────────────────────┐      ┌──────────────────────────────────────┐  │
│   │  🧠 THE BRAIN       │      │  🤚 THE HANDS                       │  │
│   │  (adk_agent.py)     │      │  (payment_tools.py)                 │  │
│   │                     │      │                                     │  │
│   │  Gemini 2.5 Flash   │─────▶│  execute_circuit_breaker()          │  │
│   │  + System Prompt    │      │  adjust_retry_strategy()            │  │
│   │  + Native Function  │      │  change_routing()                   │  │
│   │    Calling (ADK)    │◀─────│  suppress_payment_method()          │  │
│   │                     │      │  alert_ops_team()                   │  │
│   └─────────────────────┘      │  monitor_and_rollback()             │  │
│            │                   │  get_agent_state()                  │  │
│            │                   └──────────────┬───────────────────────┘  │
│            │                                  │                          │
│   ┌────────▼──────────────────────────────────▼──────────────────────┐   │
│   │                OBSERVE → REASON → DECIDE → ACT → LEARN          │   │
│   │                                                                  │   │
│   │   Observer    Reasoner    Decision     Executor     Learner      │   │
│   │   .py         .py        Maker.py     .py          .py          │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │              🛡️ Safety (src/safety/guardrails.py)                │   │
│   │   • 3-tier authorization, enforced on every path                 │   │
│   │   • Rate limits, blast radius, concurrency, min confidence       │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                  │ the only way to change payment policy  │
│   ┌──────────────────────────────▼───────────────────────────────────┐   │
│   │           🗂️ Control Plane (src/control/plane.py)                │   │
│   │   Versioned, append-only policy: breakers, suppressions,         │   │
│   │   retry strategies, routing overrides. Every revision            │   │
│   │   attributed; rollback derived from the revision, not hand-      │   │
│   │   written per action type.                                       │   │
│   └──────────────────────────────┬───────────────────────────────────┘   │
│                                  │ read by the traffic source            │
│   ┌──────────────────────────────▼───────────────────────────────────┐   │
│   │   📝 Journal (src/store/) — transactions, patterns, actions,     │   │
│   │   outcomes, revisions. Restart safety + incident replay.         │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │              🖥️ MCP Server (mcp_server.py)                       │   │
│   │   • Same tools exposed via Model Context Protocol                │   │
│   │   • Supports stdio transport for multi-process setups            │   │
│   └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### How the Gemini Agent Works

1. **User submits a scenario** (e.g., *"ICICI Bank success rate dropped to 70%"*) via the Streamlit dashboard.
2. **`adk_agent.py`** sends the scenario to **Gemini 2.5 Flash** along with all 7 tool function signatures.
3. Gemini **reasons** about the situation and decides which tool(s) to call.
4. The SDK **automatically dispatches** the function call to `payment_tools.py`.
5. The tool executes the action through `PaymentExecutor` with full safety checks.
6. The result flows back to Gemini, which provides a **natural language summary** of what it did and why.
7. The dashboard displays reasoning, actions, and the **unified audit trail**.

---

## ✨ Key Features

### 1. 🧠 LLM-Powered Autonomous Agent (Google Gemini 2.5 Flash)
- Natural language understanding of complex payment failure scenarios
- Autonomous reasoning and multi-step tool orchestration
- Native function-calling — no prompt hacking or JSON parsing
- Persistent reasoning display with unified state management

### 2. 🔍 Real-Time Pattern Detection
- Issuer degradation detection (e.g., HDFC Bank, ICICI Bank failures)
- Retry storm identification and suppression
- Payment method fatigue analysis
- Latency spike detection
- Multi-dimensional anomaly scoring

### 3. 🎯 Context-Aware Decision Making
- Multi-objective optimization (success rate, latency, cost, risk)
- Hypothesis generation with confidence scoring
- Trade-off analysis with full explainability

### 4. 🛡️ Safety Guardrails (3 Authorization Levels)

| Level | Actions | Human Approval |
|-------|---------|----------------|
| **AUTOMATIC** | Retry tuning, Alerts | ❌ Not required |
| **SEMI-AUTO** | Circuit breaker, Routing | ⚡ Quick approval |
| **MANUAL** | Method suppression | ✅ Required |

The mapping lives in one place — `ACTION_AUTHORIZATION` in `src/models/state.py` —
and every path that can create an action reads it: the autonomous loop, the LLM
tool layer and the MCP server alike. A tool call that proposes a MANUAL action
is queued for approval and returns `Success: False`, not executed. Alongside the
tiers, `SafetyGuardrails` enforces rate limits, a maximum blast radius, a
concurrency cap and a minimum confidence before any intervention runs.

### 5. 🔄 Automatic Rollback
If an action causes harm, the system automatically reverts it:
- Success rate drops > 5% → Rollback
- Latency increases > 50% → Rollback

Interventions that simply reach the end of their planned duration are *retired*,
not rolled back — they are recorded separately so that normal completions don't
consume the rollback budget that gates future actions.

### 6. 📖 Decision Explainability
Every decision includes:
- **Context**: What data triggered the analysis
- **Reasoning**: Why this pattern is significant
- **Options**: What actions were considered
- **Decision**: What was chosen and why
- **Expected Impact**: Predicted outcomes

### 7. 📚 Continuous Learning
- Updates action weights based on outcomes
- Tracks pattern detection accuracy
- Refines decision strategies over time

### 7a. 🔁 Closed Control Loop
The simulated payment world **reads the agent's control plane**. A circuit
breaker reroutes traffic away from the affected issuer, a suppressed method
stops being offered, a tightened retry limit reduces retry volume and a lowered
timeout truncates latency. Because the world responds, the metrics the agent
observes after acting reflect what it did — which is what makes rollback,
outcome scoring and learning measure something real rather than noise.

Run `pytest` to see this asserted end to end: an injected issuer outage drops
the success rate, and the agent's own intervention brings it back up.

### 7b. 🗂️ Versioned Control Plane
Every intervention is a change to one versioned policy document, and nothing
changes payment behaviour by any other route. Each revision records **who**
changed it, **why**, and **which action** caused it, so "why is UPI suppressed
right now" always has an answer:

```
r0 [system] initial empty policy
r1 [agent]  circuit_breaker on HDFC_BANK
              + circuit breaker: HDFC_BANK
r2 [agent]  route_change on HDFC_BANK
              + routing override: HDFC_BANK = {'reduce_routing_pct': 50}
```

Rollback is *derived* rather than hand-written: each action records the
revision it produced, and undoing it diffs that revision against its parent and
applies the inverse. The inverse lands on current state, so withdrawing one
intervention leaves any other still running untouched.

### 7c. 📝 Decision Journal & Replay
`--journal` records transactions, patterns, actions, outcomes and every control
plane revision to SQLite (standard library — no server to run). Two things this
buys:

- **Restart safety.** `open_interventions()` finds actions recorded as executed
  but never completed, so a restarted agent knows what it left running instead
  of losing track of live changes to payment routing.
- **Evaluation.** A recorded incident can be re-run against changed code:

```bash
python main.py --mode demo --journal data/journal.db   # record
python main.py --mode replay --journal data/journal.db # re-run it
```

Same transactions, same order, so any difference in what the agent does comes
from the change rather than a fresh random draw.

### 8. 🌐 MCP Server (Model Context Protocol)
- All tools are also available as an MCP-compliant server (`mcp_server.py`)
- Supports `stdio` transport for integration with external AI agents
- Compatible with any MCP client (Claude Desktop, custom agents, etc.)

---

## 📁 Project Structure

```
payment-agent-system/
├── adk_agent.py                  # 🧠 Gemini 2.5 Flash agent (The Brain)
├── payment_tools.py              # 🤚 Tool functions for Gemini (The Hands)
├── mcp_server.py                 # 🌐 MCP server (tools via stdio)
├── main.py                       # CLI demo runner
├── src/
│   ├── agent/
│   │   ├── core.py               # Main agent orchestrator (OBSERVE→REASON→DECIDE→ACT→LEARN)
│   │   ├── observer.py           # Data ingestion & sliding-window statistics
│   │   ├── reasoner.py           # Pattern detection & hypothesis generation
│   │   ├── decision_maker.py     # Multi-objective decision engine
│   │   ├── executor.py           # Action execution with safety guardrails
│   │   └── learner.py            # Reinforcement learning from outcomes
│   ├── control/
│   │   └── plane.py              # Versioned policy document (the agent's only output)
│   ├── store/
│   │   └── journal.py            # Append-only decision journal (SQLite)
│   ├── traffic/
│   │   └── source.py             # TrafficSource interface + journal replay
│   ├── models/
│   │   └── state.py              # Agent state, memory, data models & authorization tiers
│   ├── safety/
│   │   └── guardrails.py         # Authorization tiers, rate limits & blast radius
│   ├── simulation/
│   │   └── payment_simulator.py  # Transaction & failure scenario simulation
│   ├── factory.py                # Composition root: config -> wired objects
│   └── utils/
│       ├── settings.py           # Typed, validated configuration
│       ├── stats.py              # Stdlib percentile/mean helpers
│       ├── benchmark.py          # Performance benchmarking
│       └── config_loader.py      # YAML configuration loader
├── api/
│   └── main.py                   # FastAPI REST endpoints
├── dashboard/
│   ├── app.py                    # Streamlit real-time command center
│   ├── components.py             # Reusable UI components
│   └── styles.py                 # Dark theme CSS
├── config/
│   ├── agent_config.yaml         # Agent behavior thresholds
│   ├── safety_rules.yaml         # Safety guardrail configuration
│   └── simulation_config.yaml    # Simulator parameters
├── tests/                        # pytest suite (98 tests)
├── data/
│   ├── sample_payments.json      # Sample transaction data
│   └── sample_payments.csv       # CSV format
├── Dockerfile                    # Production container (Cloud Run ready)
├── docker-compose.yml            # Multi-service local orchestration
├── requirements.txt              # Python dependencies
├── ARCHITECTURE.md               # Detailed technical architecture
├── QUICKSTART.md                 # Getting started guide
└── PERFORMANCE.md                # Benchmarks and metrics
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- A [Google Gemini API key](https://aistudio.google.com/apikey)

### Option 1: Local Development

```bash
# Clone and setup
cd payment-agent-system
python -m venv venv
.\venv\Scripts\activate        # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

# Set your Gemini API key
set GEMINI_API_KEY=your_key_here          # Windows CMD
# export GEMINI_API_KEY=your_key_here     # macOS/Linux

# Run the Dashboard (includes Gemini Agent)
streamlit run dashboard/app.py

# Run the CLI Demo (rule-based loop)
python main.py --mode demo

# Run the REST API (separate terminal)
uvicorn api.main:app --reload
```

### Running the tests

The agent core (`src/`, `payment_tools.py`) depends only on the standard
library, so the suite runs without installing the dashboard or LLM stack:

```bash
pip install -r requirements-dev.txt
pytest
```

### Option 2: Docker

```bash
# Start all services (Dashboard + API)
docker-compose up --build

# Access:
# Dashboard: http://localhost:8501
# API:       http://localhost:8000
# API Docs:  http://localhost:8000/docs
```

### Option 3: Google Cloud Run

```bash
# Set your GCP project
gcloud config set project YOUR_PROJECT_ID

# Deploy (builds container automatically)
gcloud run deploy payment-agent \
  --source . \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=YOUR_GEMINI_API_KEY
```

---

## 📊 Dashboard Features

The Streamlit Command Center provides a unified real-time view of the entire payment system:

| Panel | Description |
|-------|-------------|
| **🧠 Agentic Reasoning** | Deploy Gemini agent with custom scenarios; persisted results |
| **💰 KPI Cards** | Success rate, latency, transactions, agent actions |
| **🎯 Health Gauge** | Real-time system health score (0–100) |
| **🧠 Explainability** | WHY patterns were detected, WHAT actions were taken |
| **📈 Trend Charts** | Success rate & latency trends over time |
| **🏦 Issuer Health** | Per-issuer success rates (color-coded bar chart) |
| **🔍 Patterns** | Detected anomalies with severity & confidence |
| **🛡️ Interventions** | Active agent interventions (unified with Gemini) |
| **🛡️ Safety Guardrails** | Authorization levels, limits & rollback triggers |
| **📜 Decision Log** | Unified audit trail with 🤖 Gemini-led tags |
| **🔥 Scenario Injection** | Simulate issuer failures, retry storms, latency spikes |

---

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Agent status & metrics |
| `/cycle` | POST | Trigger analysis cycle |
| `/transactions` | POST | Submit transactions for processing |
| `/scenarios/inject` | POST | Inject failure scenario |
| `/scenarios/clear` | DELETE | Clear active scenarios |
| `/scenarios` | GET | List active scenarios |

---

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

---

## 📈 Performance

| Metric | Value |
|--------|-------|
| Avg Cycle Time | ~50ms |
| Throughput | ~850 txn/sec |
| Pattern Detection | ~5ms |
| Memory (Peak) | ~45 MB |

---

## 🛡️ Why This is Truly Agentic

| Agentic Trait | Implementation |
|---------------|----------------|
| **Autonomy** | Auto-executes low-risk actions; Gemini reasons and acts independently |
| **State/Memory** | `AgentState`, `AgentMemory` — unified across UI and LLM |
| **Goal-Directed** | Multi-objective optimization (success rate, latency, cost, risk) |
| **Reasoning** | Gemini 2.5 Flash with structured hypothesis generation |
| **Tool Use** | Native function-calling: circuit breakers, routing, retries, alerts |
| **Learning** | Weight updates from action outcomes; strategy refinement |
| **Explainability** | Full decision audit trail with 🤖 Gemini-tagged entries |
| **Safety** | 3-tier authorization, automatic rollback, rate limiting |
| **MCP Compliance** | Tools exposed via Model Context Protocol for interoperability |

---

## 🧑‍💻 Technology Stack

| Layer | Technology |
|-------|------------|
| **LLM Brain** | Google Gemini 2.5 Flash (via `google-genai` SDK) |
| **Tool Protocol** | Model Context Protocol (MCP) with `FastMCP` |
| **Agent Framework** | Custom OBSERVE→REASON→DECIDE→ACT→LEARN loop |
| **Frontend** | Streamlit (real-time dark-themed dashboard) |
| **REST API** | FastAPI with Pydantic validation |
| **Visualization** | Plotly (interactive gauges, charts, bar graphs) |
| **Containerization** | Docker + Docker Compose |
| **Cloud Deployment** | Google Cloud Run |
| **Language** | Python 3.11 |
| **Configuration** | YAML |

---

## 📄 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Detailed technical architecture
- [QUICKSTART.md](QUICKSTART.md) — Getting started guide
- [PERFORMANCE.md](PERFORMANCE.md) — Benchmarks and metrics

---

## 📝 License

MIT License — See LICENSE file for details.
