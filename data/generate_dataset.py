"""
Sample Dataset Generator
Generates a realistic payment transaction dataset for demonstration.
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.state import PaymentMethod, PaymentStatus


def generate_sample_dataset(num_transactions: int = 10000) -> list:
    """Generate sample payment transactions."""
    
    issuers = [
        'HDFC_BANK', 'ICICI_BANK', 'SBI', 'AXIS_BANK',
        'KOTAK_BANK', 'YES_BANK', 'PAYTM_BANK', 'RAZORPAY'
    ]
    
    payment_methods = [
        ('CREDIT_CARD', 0.35),
        ('DEBIT_CARD', 0.30),
        ('UPI', 0.25),
        ('NET_BANKING', 0.07),
        ('WALLET', 0.03)
    ]
    
    regions = ['NORTH', 'SOUTH', 'EAST', 'WEST', 'CENTRAL']
    
    merchants = [f'MERCHANT_{i:04d}' for i in range(1, 51)]
    
    error_codes = [
        'INSUFFICIENT_FUNDS', 'INVALID_CARD', 'TIMEOUT',
        'ISSUER_DOWN', 'NETWORK_ERROR', 'DECLINED',
        'EXPIRED_CARD', 'FRAUD_SUSPECTED'
    ]
    
    transactions = []
    base_time = datetime.now() - timedelta(hours=24)
    
    for i in range(num_transactions):
        # Timestamp spread over 24 hours
        timestamp = base_time + timedelta(seconds=i * (86400 / num_transactions))
        
        # Payment method (weighted)
        methods, weights = zip(*payment_methods)
        payment_method = random.choices(methods, weights=weights)[0]
        
        # Other attributes
        issuer = random.choice(issuers)
        region = random.choice(regions)
        merchant = random.choice(merchants)
        
        # Success/failure (95% base success rate with variations)
        hour = timestamp.hour
        # Lower success during peak hours (10-14, 18-22)
        if 10 <= hour <= 14 or 18 <= hour <= 22:
            success_rate = 0.92
        else:
            success_rate = 0.96
        
        is_success = random.random() < success_rate
        
        # Retry logic
        is_retry = random.random() < 0.08
        retry_count = random.randint(1, 3) if is_retry else 0
        
        # Build transaction
        transaction = {
            'transaction_id': str(uuid4()),
            'timestamp': timestamp.isoformat(),
            'amount': round(random.lognormvariate(6, 1.5), 2),
            'currency': 'INR',
            'payment_method': payment_method,
            'issuer': issuer,
            'merchant_id': merchant,
            'status': 'SUCCESS' if is_success else 'FAILED',
            'error_code': None if is_success else random.choice(error_codes),
            'error_message': None if is_success else f"Transaction declined",
            'latency_ms': round(200 + random.gauss(0, 50), 2),
            'retry_count': retry_count,
            'is_retry': is_retry,
            'original_transaction_id': str(uuid4()) if is_retry else None,
            'region': region,
            'processor': 'default'
        }
        
        transactions.append(transaction)
    
    return transactions


def main():
    import csv
    
    print("Generating 10,000 sample transactions...")
    transactions = generate_sample_dataset(10000)
    
    # Save to JSON
    json_path = Path(__file__).parent / 'sample_payments.json'
    with open(json_path, 'w') as f:
        json.dump(transactions, f, indent=2)
    print(f"📁 JSON saved to: {json_path}")
    
    # Save to CSV
    csv_path = Path(__file__).parent / 'sample_payments.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=transactions[0].keys())
        writer.writeheader()
        writer.writerows(transactions)
    print(f"📁 CSV saved to: {csv_path}")
    
    # Print summary
    success_count = sum(1 for t in transactions if t['status'] == 'SUCCESS')
    print(f"\n✅ Generated {len(transactions)} transactions")
    print(f"\nDataset Summary:")
    print(f"  Total Transactions: {len(transactions)}")
    print(f"  Success Rate: {success_count/len(transactions):.1%}")
    print(f"  Columns: 16 fields per transaction")
    print(f"  Time Range: 24 hours")


if __name__ == '__main__':
    main()
