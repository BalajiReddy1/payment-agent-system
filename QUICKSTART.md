# Quickstart

## 1. Start the API

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload
```

The API starts the simulated payment-agent runtime automatically. Check it at:

```text
http://localhost:8000/health
```

## 2. Start the frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Open `http://localhost:3000`.

## 3. Create a test incident

Use **Run test scenario** in the recovery desk, or call the API directly:

```bash
curl -X POST http://localhost:8000/scenarios/inject \
  -H "Content-Type: application/json" \
  -d '{"type":"issuer_degradation","issuer":"ICICI_BANK","severity":0.82,"duration_seconds":300}'
```

The recovery desk will update as the agent detects, evaluates, and measures the
incident.

## Docker alternative

```bash
docker compose up --build
```

Use `docker compose down` to stop both services.
