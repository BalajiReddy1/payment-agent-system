import argparse
import random
import time
from datetime import datetime

from src.factory import build_system

# Cycle cadences. Driven off an explicit next-run timestamp rather than
# `int(elapsed) % N == 0`, which silently skips any N the sleep interval
# never lands on exactly.
CYCLE_INTERVAL = 15
CONTINUOUS_CYCLE_INTERVAL = 30


def run_demo_scenario():
    
    print("=" * 80)
    print("AGENTIC AI PAYMENT OPERATIONS SYSTEM - DEMONSTRATION")
    print("=" * 80)
    print()
    
    print("Initializing payment agent and simulator from config/...")
    # The simulator is wired to the agent's control plane, so interventions
    # actually move the metrics the agent then observes.
    agent, simulator, settings = build_system(
        window_size_minutes=5,
        analysis_interval_seconds=CYCLE_INTERVAL,
        # The demo runs for a few minutes, so score outcomes sooner than the
        # production default or the learning phase never has any input.
        outcome_evaluation_seconds=45,
    )
    print(f"  detection thresholds: {agent.reasoner.thresholds}")
    print(f"  decision weights:     {agent.decision_maker.weights}")
    
    print("\n" + "=" * 80)
    print("PHASE 1: NORMAL OPERATION (60 seconds)")
    print("=" * 80)
    print("Simulating healthy payment processing...")
    print()
    
    # Phase 1: Normal operation
    start_time = time.time()
    next_cycle = start_time + CYCLE_INTERVAL
    while time.time() - start_time < 60:
        # Generate transactions
        transactions = simulator.generate_stream(count=20, start_time=datetime.now())
        agent.process_batch(transactions)

        if time.time() >= next_cycle:
            next_cycle = time.time() + CYCLE_INTERVAL
            results = agent.run_cycle()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                  f"Cycle #{results['cycle']}: "
                  f"{results['observation_summary']['overall_success_rate']:.2%} success rate, "
                  f"{results['observation_summary']['total_transactions']} transactions")
        
        time.sleep(2)
    
    # Show status
    print("\nPhase 1 Complete. Agent Status:")
    status = agent.get_status()
    print(f"  Success Rate: {status['state']['success_rate']:.2%}")
    print(f"  Avg Latency: {status['state']['avg_latency_ms']:.0f}ms")
    print(f"  Total Transactions: {status['state']['total_transactions']}")
    
    print("\n" + "=" * 80)
    print("PHASE 2: ISSUER DEGRADATION SCENARIO (90 seconds)")
    print("=" * 80)
    print("Injecting failure: HDFC_BANK experiencing 60% failure rate...")
    print()
    
    # Phase 2: Inject issuer degradation
    simulator.inject_issuer_degradation(issuer='HDFC_BANK', severity=0.6, duration_seconds=90)
    
    start_time = time.time()
    next_cycle = start_time + CYCLE_INTERVAL
    while time.time() - start_time < 90:
        transactions = simulator.generate_stream(count=20, start_time=datetime.now())
        agent.process_batch(transactions)

        if time.time() >= next_cycle:
            next_cycle = time.time() + CYCLE_INTERVAL
            results = agent.run_cycle()
            
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Cycle #{results['cycle']}:")
            print(f"  Success Rate: {results['observation_summary']['overall_success_rate']:.2%}")
            print(f"  Patterns Detected: {len(results['patterns_detected'])}")
            
            if results['patterns_detected']:
                for pattern in results['patterns_detected']:
                    print(f"    - {pattern['type']}: {pattern['description']} "
                          f"(severity: {pattern['severity']:.2f})")
            
            if results['actions_taken']:
                for action in results['actions_taken']:
                    print(f"  Action Taken: {action['type']} on {action['target']}")
                    print(f"    Expected Impact: +{action['estimated_impact'].get('success_rate_delta', 0):.1%} success rate")
        
        simulator.cleanup_expired_scenarios()
        time.sleep(2)
    
    print("\nPhase 2 Complete.")
    print(f"  Actions Executed: {agent.state.actions_executed}")
    print(f"  Rollbacks: {agent.state.rollbacks_last_hour}")
    
    print("\n" + "=" * 80)
    print("PHASE 3: RETRY STORM SCENARIO (60 seconds)")
    print("=" * 80)
    print("Injecting failure: Retry storm causing cascading failures...")
    print()
    
    # Phase 3: Retry storm
    simulator.inject_retry_storm(duration_seconds=60)
    
    start_time = time.time()
    next_cycle = start_time + CYCLE_INTERVAL
    while time.time() - start_time < 60:
        # Generate more retries during storm
        transactions = simulator.generate_stream(count=15, start_time=datetime.now())
        retries = simulator.generate_stream(count=10, start_time=datetime.now())
        for txn in retries:
            txn.is_retry = True
            txn.retry_count = 2
        
        agent.process_batch(transactions + retries)

        if time.time() >= next_cycle:
            next_cycle = time.time() + CYCLE_INTERVAL
            results = agent.run_cycle()
            
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Cycle #{results['cycle']}:")
            
            for pattern in results['patterns_detected']:
                if pattern['type'] == 'retry_storm':
                    print(f"  🔴 RETRY STORM DETECTED!")
                    print(f"     {pattern['description']}")
            
            for action in results['actions_taken']:
                print(f"  Action: {action['type']} on {action['target']} (score {action.get('score', 0):.2f})")
        
        simulator.cleanup_expired_scenarios()
        time.sleep(2)
    
    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)
    
    # Final status
    print("\nFinal Agent Status:")
    final_status = agent.get_status()
    print(f"  Total Cycles: {final_status['cycle_count']}")
    print(f"  Patterns Detected: {final_status['performance']['patterns_detected']}")
    print(f"  Actions Executed: {final_status['performance']['actions_executed']}")
    print(f"  Actions Attempted: {final_status['performance']['actions_attempted']}")
    print(f"  Alerts Raised: {final_status['performance']['alerts_raised']}")
    
    if final_status['active_interventions']:
        print(f"\nActive Interventions:")
        for intervention in final_status['active_interventions']:
            print(f"  - {intervention['type']} on {intervention['target']}")
    
    # Learning summary
    learning = final_status['learning_summary']
    print(f"\nLearning Summary:")
    print(f"  Outcomes Recorded: {learning['total_outcomes_recorded']}")
    
    if learning['top_actions']:
        print(f"  Most Effective Actions:")
        for action_info in learning['top_actions'][:3]:
            action = action_info['action']
            details = action_info['details']
            print(f"    - {action}: {details['avg_success_improvement']:.1%} avg improvement "
                  f"({details['sample_size']} samples)")
    
    print("\n" + "=" * 80)
    print("Thank you for watching the demonstration!")
    print("=" * 80)


def run_continuous(duration_minutes: int = 60):
    """Run continuous operation with periodic scenario injection"""
    
    print(f"Starting continuous operation for {duration_minutes} minutes...")
    
    agent, simulator, _settings = build_system()
    
    # Run for specified duration
    start_time = time.time()
    next_cycle = start_time + CONTINUOUS_CYCLE_INTERVAL
    scenario_interval = 300  # Inject scenario every 5 minutes
    last_scenario_time = 0
    
    while time.time() - start_time < duration_minutes * 60:
        # Generate transactions
        transactions = simulator.generate_stream(count=30, start_time=datetime.now())
        agent.process_batch(transactions)
        
        # Run agent cycle
        if time.time() >= next_cycle:
            next_cycle = time.time() + CONTINUOUS_CYCLE_INTERVAL
            results = agent.run_cycle()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Cycle #{results['cycle']}")
        
        # Periodically inject scenarios
        elapsed = time.time() - start_time
        if elapsed - last_scenario_time >= scenario_interval:
            # Randomly pick a scenario
            scenario_type = random.choice(['issuer', 'retry', 'latency'])
            
            if scenario_type == 'issuer':
                issuer = random.choice(simulator.issuers)
                simulator.inject_issuer_degradation(issuer, severity=0.5)
            elif scenario_type == 'retry':
                simulator.inject_retry_storm()
            elif scenario_type == 'latency':
                simulator.inject_latency_spike(multiplier=2.5)
            
            last_scenario_time = elapsed
        
        simulator.cleanup_expired_scenarios()
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(
        description='Agentic AI Payment Operations System'
    )
    parser.add_argument(
        '--mode',
        choices=['demo', 'continuous'],
        default='demo',
        help='Run mode: demo (guided scenario) or continuous'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Duration in minutes for continuous mode'
    )
    
    args = parser.parse_args()
    
    if args.mode == 'demo':
        run_demo_scenario()
    else:
        run_continuous(duration_minutes=args.duration)


if __name__ == '__main__':
    main()
