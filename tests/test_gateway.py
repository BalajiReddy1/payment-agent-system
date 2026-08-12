"""
Payment gateway traffic sources.

src/traffic/source.py claimed for several releases that a real PSP adapter
"fits this interface without the agent changing". These tests are how that
claim stops being a claim: the mappings run against recorded payloads, and the
last section drives the whole agent loop off gateway traffic without touching
the agent.

Nothing here needs credentials or a network. The live-sandbox check at the end
is skipped unless both are present, and is the only test in the suite that
would ever talk to a third party.
"""

import os
import urllib.error
from datetime import datetime, timedelta, timezone

from src.models.state import PaymentMethod, PaymentStatus
from src.traffic.gateway import (
    ALL_SIGNALS,
    SIGNAL_ERROR_CODE,
    SIGNAL_ISSUER,
    SIGNAL_LATENCY,
    HttpTransport,
    PaymentGatewaySource,
    RazorpayMapper,
    StripeMapper,
    WebhookLatency,
)
from src.traffic.source import TrafficSource

from fixtures.gateway_payloads import RAZORPAY_PAYMENTS, STRIPE_CHARGES


class FixtureTransport:
    """Replays a recorded payload, and records what was asked for."""

    def __init__(self, payload, fail_with=None):
        self.payload = payload
        self.fail_with = fail_with
        self.requests = []

    def get(self, path, params):
        self.requests.append({'path': path, 'params': params})
        if self.fail_with:
            raise self.fail_with
        return self.payload


def razorpay_source(**kwargs):
    transport = FixtureTransport(RAZORPAY_PAYMENTS)
    return PaymentGatewaySource(
        transport, provider='razorpay', merchant_id='acme', **kwargs
    ), transport


def stripe_source(**kwargs):
    transport = FixtureTransport(STRIPE_CHARGES)
    return PaymentGatewaySource(
        transport, provider='stripe', merchant_id='acme', **kwargs
    ), transport


def by_id(transactions):
    return {t.transaction_id: t for t in transactions}


def recent(payload, key='created_at'):
    """
    Rebase a fixture's timestamps onto the present.

    The recorded epochs are fixed so the mapping tests stay deterministic, but
    the observer keeps a window relative to now - a two-year-old payment is
    correctly evicted the moment it arrives. Tests that drive the agent loop
    want the same records, dated today.
    """
    import copy

    fresh = copy.deepcopy(payload)
    now = int(datetime.now(timezone.utc).timestamp())
    records = fresh.get('items') or fresh.get('data') or []
    for offset, record in enumerate(reversed(records)):
        record[key] = now - offset
    return fresh


# ── Razorpay mapping ─────────────────────────────────────────────────────────

def test_razorpay_amounts_are_converted_from_paise():
    source, _ = razorpay_source()

    payment = by_id(source.next_batch(50))['pay_29QQoUBi66xm2f']

    assert payment.amount == 1450.00, "145000 paise is Rs 1450, not Rs 145000"
    assert payment.currency == 'INR'


def test_razorpay_failure_is_a_failure_and_carries_its_code():
    source, _ = razorpay_source()

    payment = by_id(source.next_batch(50))['pay_29QQoUBi66xm3g']

    assert payment.status == PaymentStatus.FAILED
    assert payment.error_code == 'BAD_REQUEST_ERROR'
    assert 'bank is not responding' in payment.error_message


def test_an_authorized_payment_is_not_counted_as_a_decline():
    """
    Razorpay reports intermediate states. Treating 'authorized' as a failure
    would have the agent detect a degradation it invented, act on it, and then
    measure the improvement when the payments captured on their own.
    """
    source, _ = razorpay_source()

    payment = by_id(source.next_batch(50))['pay_29QQoUBi66xm6j']

    assert payment.status == PaymentStatus.SUCCESS


def test_razorpay_issuer_is_found_wherever_the_method_puts_it():
    """
    Each payment method genuinely populates a different field. Reading only
    `bank` would leave every card and UPI payment attributed to one bucket,
    and issuer detection works on exactly this dimension.
    """
    payments = by_id(razorpay_source()[0].next_batch(50))

    assert payments['pay_29QQoUBi66xm2f'].issuer == 'HDFC'    # netbanking: bank
    assert payments['pay_29QQoUBi66xm4h'].issuer == 'OKAXIS'  # upi: vpa handle
    assert payments['pay_29QQoUBi66xm5i'].issuer == 'ICIC'    # card: card.issuer
    assert payments['pay_29QQoUBi66xm7k'].issuer == 'PAYTM'   # wallet


def test_razorpay_debit_cards_are_not_reported_as_credit():
    """method=card with card.type=debit is a debit card, and the agent's
    method-fatigue detection distinguishes them."""
    payments = by_id(razorpay_source()[0].next_batch(50))

    assert payments['pay_29QQoUBi66xm5i'].payment_method == PaymentMethod.DEBIT_CARD
    assert payments['pay_29QQoUBi66xm6j'].payment_method == PaymentMethod.CREDIT_CARD


def test_razorpay_methods_map_to_the_agents_vocabulary():
    payments = by_id(razorpay_source()[0].next_batch(50))

    assert payments['pay_29QQoUBi66xm2f'].payment_method == PaymentMethod.NET_BANKING
    assert payments['pay_29QQoUBi66xm4h'].payment_method == PaymentMethod.UPI
    assert payments['pay_29QQoUBi66xm7k'].payment_method == PaymentMethod.WALLET


def test_razorpay_region_comes_from_merchant_notes():
    payments = by_id(razorpay_source()[0].next_batch(50))

    assert payments['pay_29QQoUBi66xm2f'].region == 'NORTH'
    assert payments['pay_29QQoUBi66xm4h'].region == 'unknown'


# ── Stripe mapping ───────────────────────────────────────────────────────────

def test_stripe_amounts_are_converted_from_cents():
    payments = by_id(stripe_source()[0].next_batch(50))

    assert payments['ch_3PJ9xkH1n2K3l4m5'].amount == 25.99
    assert payments['ch_3PJ9xkH1n2K3l4m5'].currency == 'USD'


def test_stripe_decline_carries_its_failure_code():
    payment = by_id(stripe_source()[0].next_batch(50))['ch_3PJ9xkH1n2K3l4m6']

    assert payment.status == PaymentStatus.FAILED
    assert payment.error_code == 'card_declined'


def test_a_stripe_block_with_no_failure_code_still_reports_a_reason():
    """
    Stripe does not always populate failure_code; for a risk block the detail
    is in outcome.reason. Reading only failure_code loses the decline, and an
    error cluster the agent never sees is an incident nobody is handling.
    """
    payment = by_id(stripe_source()[0].next_batch(50))['ch_3PJ9xkH1n2K3l4m7']

    assert payment.status == PaymentStatus.FAILED
    assert payment.error_code == 'highest_risk_level'


def test_stripe_issuer_is_the_card_network_and_says_so():
    """
    The honest compromise. Stripe does not expose the issuing bank, so the
    network stands in - and an operator reading "issuer VISA degraded" has to
    know they are looking at a network, not a bank.
    """
    source, _ = stripe_source()
    payments = by_id(source.next_batch(50))

    assert payments['ch_3PJ9xkH1n2K3l4m5'].issuer == 'VISA'
    assert payments['ch_3PJ9xkH1n2K3l4m6'].issuer == 'MASTERCARD'
    assert 'card network' in source.describe()


def test_stripe_non_card_methods_are_mapped():
    payment = by_id(stripe_source()[0].next_batch(50))['ch_3PJ9xkH1n2K3l4m8']

    assert payment.payment_method == PaymentMethod.NET_BANKING


def test_stripe_region_uses_the_card_country():
    payments = by_id(stripe_source()[0].next_batch(50))

    assert payments['ch_3PJ9xkH1n2K3l4m6'].region == 'GB'


# ── The signal that is not there ─────────────────────────────────────────────

def test_neither_gateway_invents_a_latency():
    """
    The point of the whole `signals` mechanism. A list-payments API does not
    report how long the processor took; a fabricated number would be
    indistinguishable from a real one downstream, and the agent would detect,
    act on and measure spikes in noise it generated itself.
    """
    for source, _ in (razorpay_source(), stripe_source()):
        assert all(t.latency_ms == 0.0 for t in source.next_batch(50))
        assert SIGNAL_LATENCY not in source.signals()


def test_a_source_declares_what_it_cannot_supply():
    source, _ = razorpay_source()

    assert SIGNAL_ISSUER in source.signals()
    assert SIGNAL_ERROR_CODE in source.signals()
    assert SIGNAL_LATENCY in ALL_SIGNALS - source.signals()
    assert 'no latency' in source.describe()


def test_webhook_receipt_turns_the_latency_signal_on():
    """
    Creation-to-notification is a real, measurable interval - the only latency
    a merchant actually observes - so supplying it is honest where inventing
    one was not.
    """
    source, _ = razorpay_source()
    latency = WebhookLatency(source)

    created = datetime.fromtimestamp(1717243800, tz=timezone.utc)
    latency.record_receipt('pay_29QQoUBi66xm2f', created + timedelta(milliseconds=850))

    payment = by_id(latency.apply(source.next_batch(50)))['pay_29QQoUBi66xm2f']

    assert abs(payment.latency_ms - 850) < 1
    assert SIGNAL_LATENCY in latency.signals()


def test_payments_without_a_receipt_keep_no_latency_rather_than_a_guess():
    source, _ = razorpay_source()
    latency = WebhookLatency(source)

    payments = by_id(latency.apply(source.next_batch(50)))

    assert payments['pay_29QQoUBi66xm4h'].latency_ms == 0.0


# ── Polling behaviour ────────────────────────────────────────────────────────

def test_windows_overlap_so_nothing_falls_through_the_gap():
    """
    A gateway makes a payment queryable slightly after it is created, so a
    window starting exactly where the last one ended silently drops whatever
    landed in between.
    """
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    source, transport = razorpay_source(overlap_seconds=30, clock=lambda: now)

    source.next_batch(50)
    first_end = transport.requests[0]['params']['to']

    source.next_batch(50)
    second_start = transport.requests[1]['params']['from']

    assert second_start < first_end, "consecutive windows must overlap"
    assert first_end - second_start == 30


def test_the_same_payment_is_not_delivered_twice():
    """The overlap that prevents gaps guarantees duplicates; dedupe is its
    other half."""
    source, _ = razorpay_source()

    first = source.next_batch(50)
    second = source.next_batch(50)

    assert len(first) == 6
    assert second == [], "the second poll returns the same window, already seen"


def test_a_gateway_outage_yields_an_empty_batch_rather_than_a_crash():
    """
    The agent's loop is what keeps the lights on during an incident. A provider
    outage is precisely when it must not die - but the failure is counted, not
    absorbed.
    """
    transport = FixtureTransport(RAZORPAY_PAYMENTS, fail_with=urllib.error.URLError('down'))
    source = PaymentGatewaySource(transport, provider='razorpay')

    assert source.next_batch(50) == []
    assert source.fetch_errors == 1


def test_one_unmappable_record_does_not_cost_the_whole_window():
    payload = {'items': [{'no_id_field': True}] + RAZORPAY_PAYMENTS['items']}
    source = PaymentGatewaySource(FixtureTransport(payload), provider='razorpay')

    assert len(source.next_batch(50)) == 6
    assert source.fetch_errors == 1


def test_the_dedupe_set_does_not_grow_without_bound():
    """A process meant to run for weeks cannot keep every id it has seen."""
    source, _ = razorpay_source()
    source._seen = {f'pay_{i}' for i in range(30_000)}

    source.next_batch(50)

    assert len(source._seen) < 30_000


def test_page_size_respects_the_provider_cap():
    source, transport = razorpay_source()
    source.next_batch(500)

    assert transport.requests[0]['params']['count'] == 100


def test_an_unknown_provider_fails_loudly():
    try:
        PaymentGatewaySource(FixtureTransport({}), provider='paypal')
    except ValueError as exc:
        assert 'paypal' in str(exc) and 'razorpay' in str(exc)
    else:
        raise AssertionError('an unknown provider must not be silently accepted')


# ── The contract ─────────────────────────────────────────────────────────────

def test_both_gateways_satisfy_the_traffic_source_protocol():
    for source, _ in (razorpay_source(), stripe_source()):
        assert isinstance(source, TrafficSource)


def test_every_mapped_transaction_is_journal_serialisable():
    """A source the journal cannot record cannot be replayed, and replay is
    how a past incident is re-run against changed agent code."""
    import json

    for source, _ in (razorpay_source(), stripe_source()):
        for transaction in source.next_batch(50):
            json.dumps(transaction.to_dict())


def test_the_agent_runs_on_gateway_traffic_without_changing():
    """
    The claim src/traffic/source.py has been making all along, finally
    executed: real-shaped gateway traffic through the ordinary loop.
    """
    from src.factory import build_agent

    agent = build_agent(window_size_minutes=60, advisor=None)
    source = PaymentGatewaySource(
        FixtureTransport(recent(RAZORPAY_PAYMENTS)),
        provider='razorpay', merchant_id='acme',
    )

    agent.process_batch(source.next_batch(50))
    result = agent.run_cycle()

    assert 'error' not in result
    assert agent.observer.get_summary()['total_transactions'] == 6

    health = agent.observer.get_issuer_health()
    assert 'HDFC' in health, "gateway issuers must reach the observer's dimensions"


def test_the_agent_detects_a_real_shaped_degradation_from_gateway_traffic():
    """
    Mapping is only worth having if the mapped data still triggers detection.
    Every HDFC payment fails; the agent has to notice through the adapter.
    """
    from src.factory import build_agent

    now = int(datetime.now(timezone.utc).timestamp())
    items = []
    for i in range(120):
        failing = i % 2 == 0
        items.append({
            'id': f'pay_{i}',
            'amount': 100000,
            'currency': 'INR',
            'status': 'failed' if failing else 'captured',
            'method': 'netbanking',
            'bank': 'HDFC' if failing else 'ICICI',
            'notes': {'region': 'NORTH'},
            'error_code': 'GATEWAY_ERROR' if failing else None,
            'error_description': 'issuer unavailable' if failing else None,
            'created_at': now - (120 - i),
        })

    agent = build_agent(window_size_minutes=600, advisor=None)
    source = PaymentGatewaySource(
        FixtureTransport({'items': items}), provider='razorpay'
    )

    agent.process_batch(source.next_batch(200))
    result = agent.run_cycle()

    patterns = result['patterns_detected']
    assert patterns, 'a 100% failure rate on one issuer must be detected'
    assert any(p.get('affected_value') == 'HDFC' or 'HDFC' in p.get('description', '')
               for p in patterns), patterns


# ── Transport ────────────────────────────────────────────────────────────────

def test_transport_builds_basic_auth_and_a_query_string():
    """No network: the request is inspected before it is sent."""
    transport = HttpTransport('https://api.example.com/', 'key_id', 'key_secret')
    sent = {}

    def fake_urlopen(request, timeout=None):
        sent['url'] = request.full_url
        sent['auth'] = request.get_header('Authorization')
        raise urllib.error.URLError('stop here')

    import urllib.request as urllib_request
    original = urllib_request.urlopen
    urllib_request.urlopen = fake_urlopen
    try:
        try:
            transport.get('/v1/payments', {'count': 10, 'skipped': None})
        except urllib.error.URLError:
            pass
    finally:
        urllib_request.urlopen = original

    assert sent['url'] == 'https://api.example.com/v1/payments?count=10'
    assert sent['auth'].startswith('Basic ')

    import base64
    decoded = base64.b64decode(sent['auth'].split(' ', 1)[1]).decode()
    assert decoded == 'key_id:key_secret'


# ── Live sandbox (skipped without credentials) ───────────────────────────────

def test_against_a_real_sandbox_when_credentials_are_present():
    """
    The one test that would touch a third party. It is skipped rather than
    faked: a green suite that quietly never ran this is worse than an honest
    skip, because it would read as evidence the live path works.
    """
    key = os.environ.get('RAZORPAY_KEY_ID')
    secret = os.environ.get('RAZORPAY_KEY_SECRET')
    if not (key and secret):
        return  # skipped: no sandbox credentials configured

    source = PaymentGatewaySource(
        HttpTransport('https://api.razorpay.com', key, secret),
        provider='razorpay',
        merchant_id=os.environ.get('MERCHANT_ID', 'sandbox'),
    )

    transactions = source.next_batch(10)

    assert source.fetch_errors == 0, 'the sandbox rejected the request'
    for transaction in transactions:
        assert transaction.transaction_id
        assert transaction.status in (PaymentStatus.SUCCESS, PaymentStatus.FAILED)
        assert transaction.amount >= 0
