# Quick Start

## The fastest path

```bash
cd payment-agent-system
python web/server.py
```

Open <http://localhost:8080>. That is the whole setup — no install step, no
dependencies, no API key. The console and the agent core are standard library
only.

Inject a failure from the left rail and watch the loop work: the agent detects
the degradation, ranks its options, applies what it may apply on its own,
queues what it may not, and measures the result against a concurrent holdout.
It is not told what you injected — it has to find it.

## What to watch

**The state indicator** moves `observing → mitigating → monitoring`. Mitigating
means an incident is open; monitoring means an intervention is live and being
measured.

**Issuer health**, worst first. The injected issuer should visibly separate
from the others within a few cycles.

**Awaiting authorization** appears when the agent decides on something it is not
allowed to do alone. Approve or deny it and watch the policy history record who
decided. If you leave it, it lapses — it is never granted by default.

**Decision trace** shows every alternative that was scored, not only the one
chosen. This is the screen that distinguishes reasoning from a rules engine.

**Measured effect** shows treated versus held-out control. Early on it reads
"still collecting": the control arm needs 30 observations before the system
will call a result significant, and it says so rather than overclaiming from
three.

**Policy history** is the audit trail. Every revision is attributed and shows
what actually changed — `+ circuit breaker: SBI`, `+ holdout: SBI = 10% left as
control`.

## Reading the numbers

| Signal | Healthy | During an incident | After the agent acts |
|--------|---------|--------------------|----------------------|
| Success rate | 95-97% | 75-90% | recovers toward 95% |
| Patterns detected | 0 | 1+ per cycle | falls as the incident closes |

Patterns the agent can detect: `issuer_degradation`, `retry_storm`,
`method_fatigue`, `latency_spike`, `error_cluster`.

Actions it can take: `circuit_breaker`, `route_change`, `adjust_retry`,
`method_suppress`, `alert_ops`.

## Other ways to run it

Everything below needs `pip install -r requirements.txt`.

```bash
# Scripted three-phase demo in the terminal (~3 minutes)
python main.py --mode demo

# Continuous operation with scenarios injected periodically
python main.py --mode continuous --duration 60

# Record a run, then replay it against current agent code. Replay is how
# "the agent handled it well" becomes a measurement: the same transactions,
# re-run after you change a threshold or a weight.
python main.py --mode continuous --duration 10 --journal data/run.db
python main.py --mode replay --journal data/run.db

# REST API
uvicorn api.main:app --reload

# Everything, containerised
docker-compose up --build
```

## Verifying it works

```bash
pytest
```

The agent core has no third-party dependencies, so the suite runs without the
dashboard or LLM stack installed.

```bash
python -m src.utils.benchmark
```

Measures the real loop under a live incident and reports per-phase timings the
cycle records about itself. See PERFORMANCE.md.

## Turning on the LLM

Optional. Without it the agent detects, decides and acts identically — only the
written assessment on each incident is missing.

```bash
export GEMINI_API_KEY=your_key_here     # macOS/Linux
set GEMINI_API_KEY=your_key_here        # Windows CMD
```

The advisor runs once per **incident**, not once per cycle, and is given no
tools. Disable it explicitly with `advisor.enabled: false` in
`config/agent_config.yaml` if sending incident detail to a provider is not
acceptable in your environment.

## Configuration

Change behaviour in `config/*.yaml`, not in code. Defaults live in
`src/utils/settings.py` and the YAML overrides them, so the system runs with no
config files present and a config file cannot silently drop a setting the code
depends on.

| File | Controls |
|------|----------|
| `agent_config.yaml` | window size, detection thresholds, decision weights, holdout fraction, advisor, control plane publishing |
| `safety_rules.yaml` | authorization tiers, rate limits, blast radius, rollback triggers |
| `simulation_config.yaml` | baseline success rate, traffic mix |

Validation is strict about what is dangerous to get wrong. Decision weights
must sum to 1.0, and the authorization section must classify every action type
— adding a capability cannot leave it unclassified and therefore unguarded.
Both are checked at startup rather than mid-incident.

## Troubleshooting

**The agent detects nothing.** Severity may be too low for the window. Raise it
(`severity=0.8`) or shorten `window_size_minutes` — a shorter window detects
faster, at the cost of statistical power on low-volume issuers.

**An experiment stays "still collecting".** The control arm is 10% of affected
traffic by default and needs 30 observations. Either wait, or raise
`holdout_fraction`. This is working as intended: the alternative is announcing
significance from a handful of transactions.

**`ModuleNotFoundError` running the console.** There should not be one — the
console imports nothing outside the standard library. Check you are running
`python web/server.py` from the project root.

**`ModuleNotFoundError: google`** running the dashboard or the tool path. The
LLM SDK is optional and imported lazily; install it with
`pip install google-genai`, or use the console, which never needs it.

**Too many rollbacks.** Adjust `rollback_triggers` in `safety_rules.yaml`.

## Next

- **ARCHITECTURE.md** — how it is put together and why each part is that shape.
- **PERFORMANCE.md** — measured cost of the loop and what actually scales.
- **README.md** — connecting it to a real gateway and a real checkout service.
- `src/agent/core.py` — the loop itself.
