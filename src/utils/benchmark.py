"""
Performance benchmark.

Measures the agent loop that actually runs. The previous version of this file
reconstructed a pseudo-cycle - reasoner and decision maker called directly,
with act, learn, monitoring, journalling and experiment bookkeeping left out -
and the numbers it printed went into PERFORMANCE.md as though they described a
cycle. They understated throughput by about a hundredfold and the phase
breakdown described work that was never timed.

So this drives run_cycle() and reads the per-phase timings the cycle reports
about itself. Everything printed here is measured; nothing is apportioned.

Usage:
    python -m src.utils.benchmark
    python -m src.utils.benchmark --cycles 50 --batch 500
"""

import argparse
import contextlib
import gc
import io
import logging
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.factory import build_system  # noqa: E402

try:
    import resource
except ImportError:  # Windows does not ship POSIX resource.getrusage.
    resource = None

PHASES = ('observe', 'reason', 'decide_act', 'monitor', 'learn', 'baselines')


def peak_rss_mb() -> float:
    """
    Peak resident set size.

    tracemalloc only counts Python objects, which reported ~4 MB against a
    documented 30-60 MB and made the two look unrelated. RSS is the number that
    decides whether this fits in a container.
    """
    if resource is not None:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kilobytes, macOS bytes.
        return peak / 1024.0 if sys.platform.startswith('linux') else peak / (1024.0 ** 2)

    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD),
                ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        if ok:
            return counters.PeakWorkingSetSize / (1024.0 ** 2)

    return 0.0


def run_benchmark(cycles: int = 30, batch: int = 250, quiet: bool = True):
    """
    Drive the real loop under a real incident and report what it cost.

    An incident is injected on purpose. Benchmarking a quiet system measures
    the cheapest path through the code - no patterns, no decisions, no
    executions - and the cycle time that matters is the one during the
    incident the agent exists to handle.
    """
    if quiet:
        logging.disable(logging.WARNING)

    agent, simulator, _settings = build_system(
        window_size_minutes=5, advisor=None
    )
    with contextlib.redirect_stdout(io.StringIO() if quiet else sys.stdout):
        simulator.inject_issuer_degradation('SBI', severity=0.8, duration_seconds=7200)

    gc.collect()

    cycle_ms, ingest_ms = [], []
    phase_ms = {name: [] for name in PHASES}
    transactions = 0

    # The alert path writes to stdout. Left alone it both floods the report and
    # charges terminal I/O to the cycle it happens to fire in - which on an
    # incident is most of them, and which is not what anyone reading a cycle
    # time wants measured.
    sink = io.StringIO() if quiet else sys.stdout

    for _ in range(cycles):
        stream = simulator.generate_stream(count=batch, start_time=datetime.now())

        with contextlib.redirect_stdout(sink):
            start = time.perf_counter()
            agent.process_batch(stream)
            ingest_ms.append((time.perf_counter() - start) * 1000.0)

            start = time.perf_counter()
            results = agent.run_cycle()
            cycle_ms.append((time.perf_counter() - start) * 1000.0)

        transactions += len(stream)
        for name, value in (results.get('phase_ms') or {}).items():
            phase_ms.setdefault(name, []).append(value)

    return {
        'cycles': cycles,
        'batch': batch,
        'transactions': transactions,
        'cycle_ms': cycle_ms,
        'ingest_ms': ingest_ms,
        'phase_ms': phase_ms,
        'ingest_throughput': transactions / (sum(ingest_ms) / 1000.0),
        'peak_rss_mb': peak_rss_mb(),
        'patterns': agent.state.patterns_detected,
        'actions': agent.state.actions_executed,
    }


def report(metrics: dict):
    cycle = sorted(metrics['cycle_ms'])
    n = len(cycle)

    print('=' * 66)
    print('  PAYMENT AGENT BENCHMARK')
    print('=' * 66)
    print(f"  {metrics['cycles']} cycles x {metrics['batch']} transactions "
          f"= {metrics['transactions']:,} transactions, one live incident")
    print(f"  {metrics['patterns']} patterns detected, "
          f"{metrics['actions']} actions executed")
    print()

    print('  Cycle time (end to end, run_cycle)')
    print(f"    mean {statistics.mean(cycle):7.1f} ms")
    print(f"    p50  {cycle[n // 2]:7.1f} ms")
    print(f"    p95  {cycle[min(int(n * 0.95), n - 1)]:7.1f} ms")
    print(f"    max  {cycle[-1]:7.1f} ms")
    print()

    print('  Phase breakdown (measured inside the cycle, mean ms)')
    total = sum(
        statistics.mean(values) for values in metrics['phase_ms'].values() if values
    )
    for name in PHASES:
        values = metrics['phase_ms'].get(name) or []
        if not values:
            continue
        mean = statistics.mean(values)
        share = mean / total if total else 0
        bar = '█' * max(1, round(share * 30))
        print(f"    {name:<11} {mean:6.1f} ms  {share:5.1%}  {bar}")
    print(f"    {'(accounted)':<11} {total:6.1f} ms of "
          f"{statistics.mean(cycle):.1f} ms cycle")
    print()

    print('  Ingest')
    print(f"    {statistics.mean(metrics['ingest_ms']):.1f} ms per "
          f"{metrics['batch']} transactions")
    print(f"    {metrics['ingest_throughput']:,.0f} transactions/sec")
    print()

    print(f"  Peak RSS: {metrics['peak_rss_mb']:.0f} MB")
    print('=' * 66)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=30)
    parser.add_argument('--batch', type=int, default=250)
    parser.add_argument('--verbose', action='store_true',
                        help='keep agent logging on (slows the loop)')
    args = parser.parse_args()

    report(run_benchmark(args.cycles, args.batch, quiet=not args.verbose))


if __name__ == '__main__':
    main()
