"""
Recorded gateway payloads.

The response shapes Razorpay and Stripe actually return, kept as fixtures so
the mapping is tested without credentials, without a network, and without the
test outcome depending on what a sandbox account happens to contain today.

Trimmed to the fields the mapper reads plus enough neighbours to keep the shape
honest - a payload with only the fields we use would stop catching the case
where a provider moves one.
"""

# ── Razorpay: GET /v1/payments ───────────────────────────────────────────────

RAZORPAY_PAYMENTS = {
    "entity": "collection",
    "count": 6,
    "items": [
        {
            "id": "pay_29QQoUBi66xm2f",
            "entity": "payment",
            "amount": 145000,           # paise
            "currency": "INR",
            "status": "captured",
            "order_id": "order_JHd1eZ1yQ1p2Kx",
            "method": "netbanking",
            "amount_refunded": 0,
            "captured": True,
            "card_id": None,
            "bank": "HDFC",
            "wallet": None,
            "vpa": None,
            "email": "buyer@example.com",
            "contact": "+919900000000",
            "notes": {"region": "NORTH"},
            "fee": 3422,
            "tax": 522,
            "error_code": None,
            "error_description": None,
            "error_source": None,
            "error_step": None,
            "error_reason": None,
            "created_at": 1717243800,
        },
        {
            "id": "pay_29QQoUBi66xm3g",
            "entity": "payment",
            "amount": 99900,
            "currency": "INR",
            "status": "failed",
            "method": "netbanking",
            "bank": "HDFC",
            "vpa": None,
            "wallet": None,
            "notes": {"region": "NORTH"},
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Your payment could not be completed as the bank is not responding.",
            "error_source": "bank",
            "error_step": "payment_authorization",
            "error_reason": "payment_failed",
            "created_at": 1717243860,
        },
        {
            "id": "pay_29QQoUBi66xm4h",
            "entity": "payment",
            "amount": 25000,
            "currency": "INR",
            "status": "captured",
            "method": "upi",
            "bank": None,
            "vpa": "buyer@okaxis",
            "wallet": None,
            "notes": {},
            "error_code": None,
            "created_at": 1717243900,
        },
        {
            "id": "pay_29QQoUBi66xm5i",
            "entity": "payment",
            "amount": 500000,
            "currency": "INR",
            "status": "captured",
            "method": "card",
            "bank": None,
            "card": {
                "id": "card_JHd1eZ1yQ1p2Ky",
                "last4": "1111",
                "network": "Visa",
                "type": "debit",
                "issuer": "ICIC",
                "international": False,
            },
            "acquirer_data": {"auth_code": "205111"},
            "notes": {},
            "error_code": None,
            "created_at": 1717243950,
        },
        {
            "id": "pay_29QQoUBi66xm6j",
            "entity": "payment",
            "amount": 120000,
            "currency": "INR",
            # An intermediate state, not a failure. Razorpay reports these and
            # counting one as a decline would have the agent respond to its own
            # accounting.
            "status": "authorized",
            "method": "card",
            "card": {"last4": "4242", "network": "Visa", "type": "credit", "issuer": "SBIN"},
            "notes": {},
            "error_code": None,
            "created_at": 1717244000,
        },
        {
            "id": "pay_29QQoUBi66xm7k",
            "entity": "payment",
            "amount": 75000,
            "currency": "INR",
            "status": "captured",
            "method": "wallet",
            "bank": None,
            "wallet": "paytm",
            "vpa": None,
            "notes": {},
            "error_code": None,
            "created_at": 1717244050,
        },
    ],
}


# ── Stripe: GET /v1/charges ──────────────────────────────────────────────────

STRIPE_CHARGES = {
    "object": "list",
    "url": "/v1/charges",
    "has_more": False,
    "data": [
        {
            "id": "ch_3PJ9xkH1n2K3l4m5",
            "object": "charge",
            "amount": 2599,             # cents
            "currency": "usd",
            "created": 1717243800,
            "status": "succeeded",
            "paid": True,
            "captured": True,
            "livemode": False,
            "failure_code": None,
            "failure_message": None,
            "outcome": {
                "network_status": "approved_by_network",
                "reason": None,
                "risk_level": "normal",
                "seller_message": "Payment complete.",
                "type": "authorized",
            },
            "payment_method_details": {
                "type": "card",
                "card": {
                    "brand": "visa",
                    "country": "US",
                    "exp_month": 8,
                    "exp_year": 2028,
                    "funding": "credit",
                    "last4": "4242",
                    "network": "visa",
                },
            },
        },
        {
            "id": "ch_3PJ9xkH1n2K3l4m6",
            "object": "charge",
            "amount": 15000,
            "currency": "usd",
            "created": 1717243860,
            "status": "failed",
            "paid": False,
            "captured": False,
            "livemode": False,
            "failure_code": "card_declined",
            "failure_message": "Your card was declined.",
            "outcome": {
                "network_status": "declined_by_network",
                "reason": "insufficient_funds",
                "risk_level": "normal",
                "seller_message": "The bank returned the decline code insufficient_funds.",
                "type": "issuer_declined",
            },
            "payment_method_details": {
                "type": "card",
                "card": {
                    "brand": "mastercard",
                    "country": "GB",
                    "funding": "debit",
                    "last4": "0002",
                    "network": "mastercard",
                },
            },
        },
        {
            "id": "ch_3PJ9xkH1n2K3l4m7",
            "object": "charge",
            "amount": 8800,
            "currency": "eur",
            "created": 1717243900,
            "status": "failed",
            "paid": False,
            "livemode": False,
            # The interesting case: no failure_code, the reason lives in
            # outcome. Reading only failure_code loses the decline entirely.
            "failure_code": None,
            "failure_message": None,
            "outcome": {
                "network_status": "not_sent_to_network",
                "reason": "highest_risk_level",
                "risk_level": "highest",
                "seller_message": "Stripe blocked this payment as too risky.",
                "type": "blocked",
            },
            "payment_method_details": {
                "type": "card",
                "card": {"brand": "amex", "country": "FR", "funding": "credit", "last4": "0005"},
            },
        },
        {
            "id": "ch_3PJ9xkH1n2K3l4m8",
            "object": "charge",
            "amount": 4200,
            "currency": "usd",
            "created": 1717243950,
            "status": "succeeded",
            "paid": True,
            "livemode": False,
            "failure_code": None,
            "outcome": {"network_status": "approved_by_network", "reason": None},
            "payment_method_details": {
                "type": "us_bank_account",
                "us_bank_account": {"bank_name": "STRIPE TEST BANK", "last4": "6789"},
            },
        },
    ],
}
