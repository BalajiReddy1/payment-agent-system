# Flowstate

**Payment recovery with evidence.** Flowstate spots a sustained payment
degradation, chooses a bounded response, records what changed, and compares
the result with an untreated holdout before it claims value recovered.

The product consists of a Next.js operations desk and a FastAPI runtime. It is
designed to make the recovery decision inspectable: what failed, why the
response was chosen, what required approval, and whether it actually helped.

## What to see first

1. Start the product and open `http://localhost:3000`.
2. Select **Open the recovery desk**.
3. Select **Run demo**.
4. Watch the incident appear, the routing response be evaluated, and the
   recovery result populate against the control group.

The demonstration is deterministic, so the same scenario and measurement are
reproducible for a review or recorded walkthrough.

| Page | Purpose |
| --- | --- |
| `/` | What Flowstate does, the operating loop, and the measurement claim |
| `/onboarding` | First run: source, blast radius, approver, holdout size |
| `/desk` | The live recovery desk |

Setup is stored in the browser only. The desk runs on its own defaults if you
skip it.

## The two lanes

The deterministic lane detects, ranks and acts. It owns every decision that can
reach customer traffic, and it is the only lane the guardrails, the approval
queue and the holdout measurement apply to.

The advisor lane writes the assessment a human reads on an incident. It runs
once per incident, is given **no tools**, and cannot change routing. A second
path to alter payments, arrived at by a component whose job was to write a
sentence, is the failure mode the split exists to prevent.

To turn the advisor on, copy `.env.example` to `.env` and set `GEMINI_API_KEY`
(one is free at https://aistudio.google.com/apikey), then restart the API. The
desk names the lane that wrote each assessment, so an operator never has to
guess. Without a key the agent still detects, decides, guards and measures, and
the desk says the advisor is off rather than passing detector output off as
model output.

## System architecture

```mermaid
flowchart LR
  source["Payment source\nSimulator or Razorpay test mode"] --> runtime["Flowstate runtime"]
  runtime --> observe["Observe\nRates, issuers, decline codes"]
  observe --> decide["Decide\nRank permitted responses"]
  decide --> guardrails["Guardrails\nLimits, approval, holdout"]
  guardrails --> control["Versioned control plane\nPolicy revision + audit record"]
  control --> router["Checkout / routing client\nReads the current policy"]
  router --> outcomes["Payment outcomes"]
  outcomes --> measure["Measurement\nTreatment compared with holdout"]
  measure --> runtime
  runtime --> api["FastAPI read model"]
  api --> desk["Next.js recovery desk"]
```

The runtime never edits a payment provider directly. It publishes a versioned
policy for an external routing client, making every action reversible and
auditable. See [ARCHITECTURE.md](ARCHITECTURE.md) for the detailed design.

## Run locally

Prerequisites: Python 3.11+, Node.js 20+, and pnpm.

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload
```

In a second terminal:

```bash
cd frontend
pnpm install
pnpm dev
```

Open `http://localhost:3000`. The frontend proxies agent requests to
`http://localhost:8000` by default.

## Run with Docker

```bash
docker compose up --build
```

This starts the recovery desk on port `3000` and the API on port `8000`.
Stop both with `docker compose down`.

## API surface

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Service health |
| `GET /snapshot` | Consistent operations read model |
| `POST /demo/run` | Run the deterministic demonstration |
| `POST /scenarios/inject` | Create a simulated payment incident |
| `POST /approvals/{request_id}/approve` | Approve a queued action |
| `POST /approvals/{request_id}/deny` | Reject a queued action |
| `POST /sources/razorpay/test-mode` | Switch to read-only Razorpay test-mode intake |

Interactive API documentation is available at `http://localhost:8000/docs`.

## Razorpay test-mode intake

Flowstate can ingest Razorpay test-mode payment records without sending a
payment action to Razorpay. Set these variables on the API service, then call
`POST /sources/razorpay/test-mode`:

```text
RAZORPAY_TEST_KEY_ID=rzp_test_...
RAZORPAY_TEST_KEY_SECRET=...
RAZORPAY_MERCHANT_ID=your-test-merchant
```

Docker Compose forwards these values from your local shell; do not place them
in the repository. The browser never receives the credentials. Razorpay's
payment list supplies status, decline code, and issuer data. It does not carry
treatment/control attribution, so recovery measurement stays in the governed
simulator until the production router returns those tags.

## Repository map

```text
api/          FastAPI transport and lifecycle hooks
config/       Agent, simulator, and safety configuration
frontend/     Next.js product frontend
src/          Agent loop, policies, analysis, simulation, and runtime
tests/        Behavioural and documentation regression tests
```

## Verification

```bash
pytest
cd frontend && pnpm build
docker compose config --quiet
```

The agent core does not depend on scientific-computing libraries. FastAPI and
PyYAML support the service and configuration layers.
