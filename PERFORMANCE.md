# Performance

Every number here comes from `python -m src.utils.benchmark` on the machine
described at the bottom. Reproduce it before quoting it — hardware moves these
figures by more than any of the differences discussed below.

## Method

The benchmark drives `agent.run_cycle()` with an issuer degradation injected,
because a quiet system measures the cheapest path through the code: no
patterns, no decisions, nothing executed. The cycle time worth knowing is the
one during the incident the agent exists to handle.

Phase timings are measured inside the cycle and reported by `run_cycle()`
itself in `results['phase_ms']`, not reconstructed by calling the components
separately. A cycle does work between the phases — journalling, incident
tracking, experiment bookkeeping — and a reconstruction silently drops it. That
is why the phases here add up to the whole cycle, and why an earlier version of
this document showed a breakdown of work that was never timed.

## Results

30 cycles × 250 transactions, one live incident:

| Metric | Value |
|--------|-------|
| Cycle time, mean | 18 ms |
| Cycle time, p50 | 17 ms |
| Cycle time, p95 | 40 ms |
| Ingest | 0.6 ms per 250 transactions |
| Ingest throughput | ~420,000 transactions/sec |
| Peak RSS | 27 MB |

Run-to-run variation on cycle mean is roughly ±15%; treat the p95 as the number
that matters, since that is what a cycle interval has to accommodate.

### Where the time goes

```
observe        5.8 ms  30.5%   window ingest accounting, summary statistics
reason         4.3 ms  22.6%   pattern detection, CUSUM, hypothesis generation
decide_act     3.3 ms  17.2%   scoring every alternative, guardrails, execution
baselines      2.5 ms  13.1%   rolling baselines for the next cycle
monitor        1.6 ms   8.3%   rollback checks, intervention expiry
learn          1.6 ms   8.2%   outcome scoring, weight updates
```

Detection and decision-making together are under 8 ms. The agent's thinking is
not the expensive part; holding the window is.

## What actually costs

Cycle time scales with **how many transactions are in the window**, not with
batch size. The window is `window_size_minutes × arrival rate`, and that
product is the only knob that matters:

| Transactions in window | Cycle mean | Cycle p95 |
|------------------------|-----------|-----------|
| 2,000 | 4 ms | 9 ms |
| 5,000 | 12 ms | 28 ms |
| 10,000 | 24 ms | 49 ms |
| 20,000 | 64 ms | 121 ms |

Roughly linear, drifting superlinear past ~10,000. At 200 transactions/sec a
10-minute window holds 120,000 — well past where this shape holds, so a
high-volume deployment shortens the window rather than lengthening the cycle
interval. A shorter window also detects faster; the trade is statistical power,
since a 1-minute window on a low-volume issuer may not hold enough payments to
distinguish a real degradation from noise.

## Resource usage

- **Peak RSS**: 27 MB at 7,500 transactions in window, 36 MB at 25,000.
- **Single-threaded.** The console runs the agent on one background thread and
  serves HTTP on others; the agent loop itself is sequential.
- **No NumPy, no SciPy, no GPU.** The statistics — beta-binomial posteriors,
  the regularised incomplete beta, two-proportion tests, log-likelihood-ratio
  CUSUM — are implemented against the standard library in
  `src/analysis/statistics.py`. An earlier version of this document claimed
  NumPy and SciPy; the project has never depended on either, and the agent core
  has no third-party dependencies at all.

## In production

- **Cycle interval** should exceed p95, not the mean. At the default window
  and a few hundred transactions/sec, a 3-second interval leaves ample room.
- **Memory limit** of 256 MB is comfortable at these window sizes. Size it
  against expected window occupancy, not against these figures.
- **Alert on cycle time** exceeding the interval — a cycle that overruns its
  interval means the loop is falling behind the traffic it is supposed to be
  watching. `/health` reports whether the loop thread is alive at all and
  answers 503 when it is not.
- **Scale horizontally by region or merchant**, one agent per control plane.
  Two agents publishing to the same policy document would race, and the last
  writer would silently win.

## Running it

```bash
python -m src.utils.benchmark
python -m src.utils.benchmark --cycles 50 --batch 500
python -m src.utils.benchmark --verbose      # keep agent logging on
```

Measured on: Linux x86-64 container, CPython 3.11, single core, no journal
attached.

### With a SQLite journal attached

Measured separately, 40 cycles × 250 transactions:

| | No journal | SQLite journal |
|---|---|---|
| Cycle | 25.9 ms | 27.8 ms |
| Ingest (250 txns) | 0.62 ms | 4.08 ms |

The cost lands on ingest, not the cycle — transactions are written per batch
while the cycle writes one summary row. Seven times a very small number is
still a very small number: journalling every transaction costs about 14 µs
each, and buys restart recovery and incident replay. The cycle difference is
inside run-to-run variance and should not be read as a real effect.
