# Architecture

How the system is put together, and why each part is the shape it is. Where a
number appears here it is measured — by a test in `tests/`, or by
`python -m src.utils.benchmark` — and the place it is measured is named.

## The shape of the thing

```
      traffic source                                    control plane
   ┌──────────────────┐                            ┌──────────────────────┐
   │ simulator        │                            │ versioned, append-   │
   │ gateway (PSP)    │──── transactions ────▶     │ only policy document │
   │ journal replay   │                            └──────────┬───────────┘
   └──────────────────┘                                       │
            ▲                                                 │ published
            │                                                 ▼
            │                              ┌──────────────────────────────┐
            └────────── reads the ─────────│  data/policy.json            │
                        policy             │  read by your checkout       │
                                           │  service (PolicyClient)      │
                                           └──────────────────────────────┘

   OBSERVE ──▶ REASON ──▶ DECIDE ──▶ ACT ──▶ LEARN
      │           │          │         │        │
      │           │          │         │        └─ outcomes, weighted by
      │           │          │         │           whether they were measured
      │           │          │         └─ guardrails, authorization tiers,
      │           │          │            approval queue, holdout assignment
      │           │          └─ every alternative scored, not only the winner
      │           └─ statistical detection: CUSUM, Bayesian rate estimates
      └─ sliding window, per-dimension accounting
```

Two structural claims hold the design together.

**The control plane is the agent's only output.** No component reaches into
payment routing directly. Every intervention is a revision to one versioned,
attributed document, which means rollback is derived by diffing revisions
rather than hand-written per action type, and the audit trail is the same
object as the mechanism.

**The loop is closed.** The traffic source reads the control plane, so an
intervention changes the transactions the agent subsequently observes. An
agent whose actions do not affect its own inputs is not an agent; it is a
report. Measured: open-loop success rate stays around 83% through an issuer
degradation, closed-loop recovers to ~97% (`tests/test_closed_loop.py`).

## The loop

### OBSERVE — `src/agent/observer.py`

A sliding window with per-dimension counters (issuer, method, region, error
code) maintained incrementally, plus an ordered outcome stream for sequential
detection.

Counters are decremented on eviction, not only incremented on arrival. A
counter that only grows becomes a permanent false positive the moment the
window moves past whatever caused it — an earlier version leaked 161 phantom
errors into a window holding 1.

Timestamps are normalised at ingest. The window is arithmetic against
`datetime.now()`, which is naive local time, while every real payment gateway
reports UTC-aware timestamps; mixing them raised `TypeError` deep inside
eviction. Aware timestamps are *converted*, not stripped — discarding the
offset would file an IST payment eleven and a half hours out of place, and the
window would quietly hold the wrong rows instead of raising.

### REASON — `src/agent/reasoner.py`, `src/analysis/statistics.py`

Detection is statistical, not threshold-based.

- **Sequential change detection.** A log-likelihood-ratio CUSUM over the
  outcome stream, threshold `log(1/0.001) = 6.9`. Measured on synthetic
  Bernoulli streams: ~4% false alarms per 2,000 healthy observations at a 95%
  baseline; detects a drop to 90% in ~310 transactions, to 80% in ~74, to 50%
  in ~22. An ad-hoc mean-shift formulation was tried first and could not
  separate signal from noise at any threshold — 78% false alarms at h=3, still
  12% at h=8.
- **Bayesian rate estimation.** Beta-binomial posteriors give
  `probability_below(rate)` rather than a point estimate crossing a guessed
  line. The regularised incomplete beta is implemented with a modified Lentz
  continued fraction against the standard library.

The agent is deliberately conservative here. CUSUM raises the alarm; the
posterior confirms it before anything is acted on. A payment operations agent
that cries wolf gets ignored, and an ignored agent is worse than none.

### DECIDE — `src/agent/decision_maker.py`

Multi-objective scoring over success rate, latency, cost and risk, with weights
that must sum to 1.0 (enforced at startup, not at 3am).

`rank_actions()` returns the whole ranking, so the console can show the
alternatives that lost. A decision trace showing only the winner is
indistinguishable from a rules engine.

Doing nothing is scored like anything else, and used to be unbeatable: a zero
delta scored 1.0 while every real intervention scored below it, so the agent
reliably chose inaction. The neutral score is now 0.5, and improvements and
regressions move away from it in proportion to their size.

### ACT — `src/agent/executor.py`, `src/safety/`, `src/analysis/experiment.py`

Three things happen before an action reaches the control plane.

**Authorization.** Every action's tier comes from one map,
`ACTION_AUTHORIZATION` in `src/models/state.py`, read by every path that can
create an action: the autonomous loop, the LLM tool layer, the MCP server.
The tier was previously hardcoded to `AUTOMATIC` on the autonomous path, so a
circuit breaker ran unattended while the docs and the map both said it needed
an operator.

**Approval.** An action the agent may not take alone is queued, not skipped.
Requests **lapse** after 600s rather than being granted — a tier that
eventually approves itself is a delay, not a control. Repeat proposals dedupe,
because the agent re-proposes every cycle while an incident continues and an
operator should see one decision rather than forty copies.

**Holdout assignment.** A fraction of affected traffic (default 10%) is
deliberately left untreated, assigned deterministically by SHA-256 of the
transaction id, so the intervention can be measured against a concurrent
control.

That last one is the expensive decision in this design. It knowingly leaves
real payments unprotected. It is worth it because the alternative — comparing
after against before — is confounded by everything else that changed, not least
the incident resolving on its own. Measured on the same incident: before/after
attributed +6.5%, the concurrent holdout measured +70.1%.

### LEARN — `src/agent/learner.py`, `src/analysis/memory.py`

Outcomes update decision weights, but only outcomes that were actually
measured. An outcome attributed by before/after comparison is recorded and
ignored for learning: feeding a confounded number into the weights teaches the
agent about the incident's natural recovery, not about its own action.

Scoring is gated on `has_sufficient_data()` — 30 observations per arm. With
`outcome_evaluation_seconds=0` outcomes were previously recorded in the same
cycle the action executed, before any traffic had passed through the
experiment, so every measurement silently fell back to before/after.

**Incident memory** retrieves comparable past incidents by structured feature
similarity — pattern type (a gate, not a weight), affected dimension, target,
severity, error signature — rather than embeddings. Only outcomes that were
both holdout-attributed and statistically significant become advice.

## Statistics that do not overstate

`compare_proportions` reports a two-proportion z-test with an Agresti-Caffo
interval, clamped to [-1, 1].

The plain Wald interval breaks exactly where a payment incident puts you. A
control arm failing every transaction has p=0, so its variance term vanishes,
the interval is computed as though only the treated arm carried uncertainty,
and it runs off the end of the scale — a live run reported
`+94.7% (95% CI +87.6% to +101.8%)`, an upper bound describing something that
cannot happen. Measured coverage of the replacement at the boundary (p=1.00 vs
0.90, n=40): 98.5% for a nominal 95% interval.

`Experiment.summary()` gates `significant` on `has_sufficient_data()` as well
as the p-value. Before that, three control transactions rendered as
"significant" on the console — a stronger claim than the agent itself would act
on, made to the person deciding whether to trust it.

## The two-lane brain

The deterministic lane detects, scores and acts every cycle in tens of
milliseconds. The **advisor** (`src/agent/advisors.py`) is asked a narrower
question — *what should a human understand about this?* — once per **incident**,
not once per cycle. On one measured run: 12 detections, 1 advisor call.

Two constraints, both enforced rather than documented:

- **Advisors get no tools.** The tool-calling path already runs through the
  authorization tiers and the approval queue. Giving the advisor those tools
  would create a second decision path bypassing the ranking, the guardrails and
  the holdout measurement — an unaudited way to change payment routing, arrived
  at by a component whose job was to write a sentence. Asserted on the wire in
  `tests/test_advisors.py`.
- **The model is optional.** `build_advisor()` returns `None` when none is
  reachable. No API key, no SDK, or the lane switched off in config all degrade
  the narrative and never the mitigation.

## Durability and restart

`src/store/journal.py` records transactions, cycles, patterns, actions,
outcomes and control plane revisions to SQLite. It buys two things.

**Replay.** `JournalReplaySource` re-runs a recorded incident against changed
agent code, which is what turns "the agent handled it well" from an assertion
into a measurement.

**Recovery.** On startup with a journal, the agent adopts whatever the previous
run left in force. Without this, a circuit breaker outlives the process that
opened it: the published policy still refuses traffic to that issuer, the
restarted agent has never heard of it, and nothing will ever expire or roll it
back. The issuer recovers and the breaker stays shut indefinitely.

Adoption publishes a *new* revision rather than rewinding the counter, attributed
`system:recovery` and carrying the original decision-maker forward in the
reason. The log is append-only; what happened, happened. An inherited
intervention is never filed as this agent's own choice, and gets its own panel
on the console — it has no incident behind it and nothing in the decision
trace, which is exactly the blind spot that let one survive unnoticed.

## Integration surface

Two seams, and nothing else, separate the demo from a deployment.

**Traffic in** — `src/traffic/gateway.py` maps Razorpay and Stripe onto the
`TrafficSource` interface. Sources declare what they can supply via
`signals()`: a gateway's list-payments API does not report processor latency,
so `latency_ms` stays zero and the signal is marked absent rather than filled
with a plausible number. A fabricated latency is indistinguishable from a real
one downstream, and the agent would detect, act on, and then *measure
improvements in* noise it generated itself.

**Decisions out** — `src/control/publish.py` writes each revision where a real
checkout service reads it with `PolicyClient`. A document rather than a
callback: the agent needs no production credentials, and an outage on either
side degrades to "the last known policy stays in force" rather than to
inconsistency.

Three properties carry that:

- Writes go through a temp file and `rename`. A reader polling mid-write gets a
  truncated document, and a truncated policy parses as an empty one — which
  reads as "nothing is wrong" and would undo every live mitigation.
- A read failure keeps the last good policy. A parse error is not evidence that
  no interventions are in force; failing open resumes routing to a dead issuer.
- Documents carry an expiry and clients expose `stale`, so a crashed agent is
  distinguishable from a quiet one. A stale policy is still applied — the
  interventions were real and nothing has said otherwise.

Honouring `holdout_fraction()` in the routing layer is what makes the
measurement real rather than self-reported: the control group has to exist in
the system actually routing payments.

## Interfaces

`src/views.py` holds the read models. Both the console (`web/server.py`) and
the REST API (`api/main.py`) call it, so the two cannot answer differently
about the same agent — before it existed, the console claimed parity the API
did not have.

The console is stdlib-only: `http.server` plus SSE, no build step, no
third-party dependency. The agent core has none either, so the thing you use to
look at the agent has the same dependency profile as the agent.

## Safety, honestly stated

| Level | Actions | Requires |
|-------|---------|----------|
| AUTOMATIC | retry tuning, alerts | nothing |
| SEMI_AUTOMATIC | circuit breaker, routing | an approver, unless low risk |
| MANUAL | method suppression | an approver, always |

Alongside the tiers, `SafetyGuardrails` enforces rate limits, a maximum blast
radius, a concurrency cap and a minimum confidence. Config that fails to
classify every action type is rejected at startup, so adding a capability
cannot leave it unclassified and therefore unguarded.

Attribution distinguishes an agent's own auto-approval (`agent:auto_low_risk`)
from an operator's (`operator:name@example.com`) and from an inherited policy
(`system:recovery`). Labelling the first as an operator would put a person's
name against a decision no person made.

## What is not claimed

The traffic in the demo is synthetic. That is a real limitation and it is
stated rather than dressed up: what makes the loop meaningful is that the
agent's decisions change what happens next, and that the measurement is a
concurrent control rather than a before/after comparison. Point it at a gateway
and the same loop runs unchanged.

There are no accuracy figures for pattern detection precision, recall or
mean-time-to-detect against real payment traffic, because there is no real
payment traffic to measure them against. An earlier version of this document
quoted precision of 85-95% and an MTTD of 30 seconds; those numbers were never
measured. What *is* measured — CUSUM false alarm rates and detection lag,
holdout-attributed lift, interval coverage, cycle cost — is cited above with
its source.

## Layout

```
src/
├── agent/        core loop: observer, reasoner, decision_maker, executor,
│                 learner, incidents, advisors
├── analysis/     statistics, experiment, memory
├── control/      plane (versioned policy), publish (integration surface)
├── safety/       guardrails, approvals
├── store/        journal (SQLite)
├── traffic/      source (interface + replay), gateway (Razorpay, Stripe)
├── simulation/   payment_simulator
├── models/       state, data models, authorization map
├── utils/        settings, stats, config_loader, benchmark
├── views.py      read models shared by console and API
└── factory.py    composition root
```

Components take their settings as constructor arguments and never read YAML
themselves, so each is testable in isolation and there is one answer to "where
does this threshold come from".

## Extending it

- **A new action type**: add it to `ActionType`, classify it in
  `ACTION_AUTHORIZATION` and `safety_rules.yaml` (startup will refuse to
  proceed until you do), implement it on the control plane, and add its
  estimated impact to the decision maker.
- **A new traffic source**: implement `next_batch`, `describe` and `signals`.
  Declare the signals you cannot supply rather than defaulting them.
- **A new detector**: add it to the reasoner and give it a statistical basis
  with a measured false-alarm rate. `src/analysis/statistics.py` has the
  primitives.
- **A new gateway**: add a mapper to `src/traffic/gateway.py` with a recorded
  payload in `tests/fixtures/`. Two providers already disagree about nearly
  everything, so the seams are in the right places.
