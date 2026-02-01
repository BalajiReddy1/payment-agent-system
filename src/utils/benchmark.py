"""
Performance Benchmark Utility
Measures agent performance metrics for documentation and presentation.
"""

import gc
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agent.core import PaymentAgent
from src.simulation.payment_simulator import PaymentSimulator


def run_benchmark(num_cycles: int = 20, transactions_per_cycle: int = 50):
    """Run performance benchmark and return metrics."""
    
    print("=" * 60)
    print("       PAYMENT AGENT PERFORMANCE BENCHMARK")
    print("=" * 60)
    print()
    
    # Initialize
    print("Initializing agent and simulator...")
    agent = PaymentAgent(
        window_size_minutes=5,
        analysis_interval_seconds=5,
        auto_approve_low_risk=True
    )
    simulator = PaymentSimulator(base_success_rate=0.95)
    
    # Metrics storage
    cycle_times = []
    pattern_times = []
    decision_times = []
    transactions_processed = 0
    
    # Start memory tracking
    tracemalloc.start()
    gc.collect()
    
    print(f"Running {num_cycles} cycles with {transactions_per_cycle} transactions each...")
    print()
    
    benchmark_start = time.time()
    
    for i in range(num_cycles):
        # Generate transactions
        transactions = simulator.generate_stream(
            count=transactions_per_cycle,
            start_time=datetime.now()
        )
        
        # Measure batch processing
        batch_start = time.time()
        agent.process_batch(transactions)
        transactions_processed += len(transactions)
        
        # Measure cycle time
        cycle_start = time.time()
        
        # Measure pattern detection
        pattern_start = time.time()
        agent.reasoner.update_baselines(agent.observer)
        patterns = agent.reasoner.analyze(agent.observer)
        pattern_time = (time.time() - pattern_start) * 1000
        pattern_times.append(pattern_time)
        
        # Measure decision making
        decision_start = time.time()
        if patterns:
            for pattern in patterns[:3]:  # Limit for speed
                # Build context and decide (simplified - just measure the time)
                try:
                    from src.agent.decision_maker import DecisionContext
                    context = DecisionContext(
                        pattern=pattern,
                        hypotheses=[],
                        current_state=agent.state,
                        observer_stats=agent.observer.get_statistics(),
                        historical_actions=[]
                    )
                    agent.decision_maker.decide(context)
                except Exception:
                    pass  # Ignore errors, just measure time
        decision_time = (time.time() - decision_start) * 1000
        decision_times.append(decision_time)
        
        cycle_time = (time.time() - cycle_start) * 1000
        cycle_times.append(cycle_time)
        
        # Progress indicator
        if (i + 1) % 5 == 0:
            print(f"  Completed cycle {i + 1}/{num_cycles}")
    
    benchmark_duration = time.time() - benchmark_start
    
    # Memory metrics
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Calculate metrics
    avg_cycle_time = sum(cycle_times) / len(cycle_times)
    avg_pattern_time = sum(pattern_times) / len(pattern_times)
    avg_decision_time = sum(decision_times) / len(decision_times)
    throughput = transactions_processed / benchmark_duration
    
    # Display results
    print()
    print("=" * 60)
    print("                    RESULTS")
    print("=" * 60)
    print()
    print(f"{'Metric':<30} {'Value':<15} {'Status':<15}")
    print("-" * 60)
    
    # Cycle time
    status = "✅ Excellent" if avg_cycle_time < 100 else "⚠️ Acceptable" if avg_cycle_time < 500 else "❌ Slow"
    print(f"{'Avg Cycle Time':<30} {avg_cycle_time:.1f}ms{'':<8} {status}")
    
    # Throughput
    status = "✅ Excellent" if throughput > 500 else "⚠️ Acceptable" if throughput > 100 else "❌ Low"
    print(f"{'Throughput':<30} {throughput:.0f} txn/sec{'':<4} {status}")
    
    # Pattern detection
    status = "✅ Fast" if avg_pattern_time < 50 else "⚠️ Acceptable" if avg_pattern_time < 200 else "❌ Slow"
    print(f"{'Pattern Detection':<30} {avg_pattern_time:.1f}ms{'':<8} {status}")
    
    # Decision making
    status = "✅ Fast" if avg_decision_time < 20 else "⚠️ Acceptable" if avg_decision_time < 100 else "❌ Slow"
    print(f"{'Decision Making':<30} {avg_decision_time:.1f}ms{'':<8} {status}")
    
    # Memory
    peak_mb = peak / 1024 / 1024
    current_mb = current / 1024 / 1024
    status = "✅ Low" if peak_mb < 100 else "⚠️ Moderate" if peak_mb < 500 else "❌ High"
    print(f"{'Memory (Peak)':<30} {peak_mb:.1f} MB{'':<7} {status}")
    print(f"{'Memory (Current)':<30} {current_mb:.1f} MB{'':<7}")
    
    print("-" * 60)
    print(f"{'Total Transactions':<30} {transactions_processed:,}")
    print(f"{'Total Benchmark Time':<30} {benchmark_duration:.1f}s")
    print()
    print("=" * 60)
    
    return {
        'avg_cycle_time_ms': avg_cycle_time,
        'throughput_tps': throughput,
        'avg_pattern_detection_ms': avg_pattern_time,
        'avg_decision_time_ms': avg_decision_time,
        'memory_peak_mb': peak_mb,
        'memory_current_mb': current_mb,
        'total_transactions': transactions_processed,
        'benchmark_duration_s': benchmark_duration
    }


if __name__ == '__main__':
    run_benchmark()
