"""
Payment gateway traffic sources.

src/traffic/source.py has always claimed a real PSP adapter "fits this
interface without the agent changing". This is that adapter, and writing it is
the only way to find out whether the claim was true. It was, with one
exception, which is the most useful thing in this module: see `signals`.

Two providers are mapped, Razorpay and Stripe, because they disagree about
almost everything - amounts in paise vs cents, epoch seconds vs ISO strings,
`error_code` vs `failure_code`, and, most consequentially, what a "issuer" even
is. Mapping two rather than one is what forces the seams into the right places.

No third-party dependencies. The transport is urllib from the standard library,
so importing this cannot break an install, and the client is injectable so
every mapping in here is tested against recorded payloads without a network.

## What is real and what is not

A gateway's list-payments API is not a metrics feed. It reports what happened
to each payment, not how long the processor took, and no amount of wanting
changes that. So `latency_ms` is left at zero and `signals()` says `latency` is
absent, rather than inventing a plausible-looking number - a fabricated latency
would be indistinguishable from a real one downstream, and the agent would
detect, act on, and *measure* spikes in noise it generated itself.

Where a latency really is available - a webhook's receipt time against the
payment's creation time - `WebhookLatency` supplies it explicitly, and only
then does the signal turn on.
"""

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Protocol

from src.models.state import PaymentMethod, PaymentStatus, PaymentTransaction

logger = logging.getLogger(__name__)

# Signals a traffic source may or may not be able to provide. The agent's
# detectors key off these; a source that cannot supply one says so instead of
# supplying a fake.
SIGNAL_STATUS = 'status'
SIGNAL_ERROR_CODE = 'error_code'
SIGNAL_LATENCY = 'latency'
SIGNAL_RETRY = 'retry'
SIGNAL_ISSUER = 'issuer'
SIGNAL_REGION = 'region'

ALL_SIGNALS = frozenset({
    SIGNAL_STATUS, SIGNAL_ERROR_CODE, SIGNAL_LATENCY,
    SIGNAL_RETRY, SIGNAL_ISSUER, SIGNAL_REGION,
})


class GatewayTransport(Protocol):
    """
    Fetches raw payloads from a provider.

    Separated from the mapping so the mapping - which is where the bugs live -
    can be tested against recorded payloads, and so a sandbox, a live account
    and a fixture are interchangeable.
    """

    def get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...


class HttpTransport:
    """
    urllib-backed transport.

    Deliberately small. Retries are not implemented here: a gateway that is
    failing to answer is itself a payment operations signal, and swallowing it
    inside the transport would hide the outage the agent exists to notice.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str = '',
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        credentials = f"{api_key}:{api_secret}".encode('utf-8')
        self._auth = base64.b64encode(credentials).decode('ascii')

    def get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
        url = f"{self.base_url}/{path.lstrip('/')}?{query}"

        request = urllib.request.Request(url)
        request.add_header('Authorization', f'Basic {self._auth}')
        request.add_header('Accept', 'application/json')

        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode('utf-8'))


# ── Mapping ──────────────────────────────────────────────────────────────────


class RazorpayMapper:
    """
    Maps Razorpay's Payments API onto PaymentTransaction.

    Amounts arrive in paise and timestamps as epoch seconds. `bank` carries the
    issuing bank for netbanking and UPI, which is exactly the dimension the
    agent's issuer detection works on - so Razorpay traffic exercises the agent
    the way the simulator does.
    """

    provider = 'razorpay'
    path = '/v1/payments'

    METHODS = {
        'card': PaymentMethod.CREDIT_CARD,
        'debit_card': PaymentMethod.DEBIT_CARD,
        'netbanking': PaymentMethod.NET_BANKING,
        'upi': PaymentMethod.UPI,
        'wallet': PaymentMethod.WALLET,
        'emi': PaymentMethod.CREDIT_CARD,
    }

    # Razorpay reports intermediate states. Only 'failed' is a failure; the
    # rest are stages of a payment that has not failed, and treating
    # 'authorized' as anything other than success would make the agent respond
    # to its own accounting.
    TERMINAL_FAILURE = {'failed'}
    PENDING = {'created'}

    def signals(self) -> FrozenSet[str]:
        return frozenset({
            SIGNAL_STATUS, SIGNAL_ERROR_CODE, SIGNAL_ISSUER,
        })

    def params(self, since: datetime, until: datetime, limit: int) -> Dict[str, Any]:
        return {
            'from': int(since.timestamp()),
            'to': int(until.timestamp()),
            'count': min(limit, 100),  # Razorpay caps a page at 100
        }

    def extract(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return payload.get('items') or []

    def to_transaction(self, record: Dict[str, Any], merchant_id: str) -> PaymentTransaction:
        status = record.get('status', '')
        if status in self.PENDING:
            failed = False
        else:
            failed = status in self.TERMINAL_FAILURE

        method_key = record.get('method', '')
        # Razorpay reports debit cards as method=card with card.type=debit.
        card = record.get('card') or {}
        if method_key == 'card' and card.get('type') == 'debit':
            method_key = 'debit_card'

        return PaymentTransaction(
            transaction_id=record['id'],
            timestamp=_from_epoch(record.get('created_at')),
            amount=(record.get('amount') or 0) / 100.0,  # paise
            currency=record.get('currency', 'INR'),
            payment_method=self.METHODS.get(method_key, PaymentMethod.CREDIT_CARD),
            issuer=_issuer_from_razorpay(record),
            merchant_id=merchant_id,
            status=PaymentStatus.FAILED if failed else PaymentStatus.SUCCESS,
            error_code=record.get('error_code'),
            error_message=record.get('error_description'),
            latency_ms=0.0,  # not reported by this API; see the module docstring
            region=(record.get('notes') or {}).get('region', 'unknown'),
            processor=self.provider,
        )


class StripeMapper:
    """
    Maps Stripe's Charges API onto PaymentTransaction.

    One mapping here is a genuine compromise rather than a detail. Stripe does
    not tell a merchant which bank issued the card, so there is nothing to put
    in `issuer` that means what it means everywhere else in this system. The
    card network is used instead - it is the dimension Stripe actually lets you
    slice failures by - and `describe()` says so, because an operator reading
    "issuer VISA degraded" needs to know they are looking at a network and not
    a bank.
    """

    provider = 'stripe'
    path = '/v1/charges'
    caveat = (
        ' - note: "issuer" is the card network; '
        'Stripe does not expose the issuing bank'
    )

    METHODS = {
        'card': PaymentMethod.CREDIT_CARD,
        'link': PaymentMethod.WALLET,
        'us_bank_account': PaymentMethod.NET_BANKING,
        'acss_debit': PaymentMethod.NET_BANKING,
        'cashapp': PaymentMethod.WALLET,
    }

    def signals(self) -> FrozenSet[str]:
        return frozenset({
            SIGNAL_STATUS, SIGNAL_ERROR_CODE, SIGNAL_ISSUER, SIGNAL_REGION,
        })

    def params(self, since: datetime, until: datetime, limit: int) -> Dict[str, Any]:
        return {
            'created[gte]': int(since.timestamp()),
            'created[lt]': int(until.timestamp()),
            'limit': min(limit, 100),
        }

    def extract(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return payload.get('data') or []

    def to_transaction(self, record: Dict[str, Any], merchant_id: str) -> PaymentTransaction:
        details = record.get('payment_method_details') or {}
        card = details.get('card') or {}
        failed = record.get('status') == 'failed' or not record.get('paid', True)

        return PaymentTransaction(
            transaction_id=record['id'],
            timestamp=_from_epoch(record.get('created')),
            amount=(record.get('amount') or 0) / 100.0,  # cents
            currency=(record.get('currency') or 'usd').upper(),
            payment_method=self.METHODS.get(
                details.get('type', 'card'), PaymentMethod.CREDIT_CARD
            ),
            issuer=(card.get('brand') or details.get('type') or 'unknown').upper(),
            merchant_id=merchant_id,
            status=PaymentStatus.FAILED if failed else PaymentStatus.SUCCESS,
            error_code=record.get('failure_code') or _decline_reason(record),
            error_message=record.get('failure_message'),
            latency_ms=0.0,  # not reported by this API; see the module docstring
            region=card.get('country', 'unknown'),
            processor=self.provider,
        )


MAPPERS = {
    'razorpay': RazorpayMapper,
    'stripe': StripeMapper,
}


# ── The source ───────────────────────────────────────────────────────────────


class PaymentGatewaySource:
    """
    A TrafficSource backed by a real payment gateway.

    Polls for payments created since the last poll and hands them to the agent.
    Deduplicates by payment id, because the polling windows overlap on purpose:
    a gateway makes a payment queryable slightly after it is created, so a
    window that started exactly where the last one ended would drop whatever
    landed in the gap.
    """

    def __init__(
        self,
        transport: GatewayTransport,
        mapper=None,
        provider: str = 'razorpay',
        merchant_id: str = 'merchant',
        overlap_seconds: float = 30.0,
        clock: Callable[[], datetime] = None,
    ):
        if mapper is None:
            if provider not in MAPPERS:
                raise ValueError(
                    f"Unknown provider {provider!r}. "
                    f"Known: {', '.join(sorted(MAPPERS))}"
                )
            mapper = MAPPERS[provider]()

        self.transport = transport
        self.mapper = mapper
        self.merchant_id = merchant_id
        self.overlap = timedelta(seconds=overlap_seconds)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

        self._seen: set = set()
        self._watermark: Optional[datetime] = None
        self.fetch_errors = 0

    def next_batch(self, count: int) -> List[PaymentTransaction]:
        """
        Fetch the next window of payments.

        A gateway that will not answer returns an empty batch rather than
        raising. The agent's loop is the thing keeping the lights on during an
        incident, and a provider outage is the moment it must not crash - but
        the failure is counted and logged, never silently absorbed.
        """
        now = self.clock()
        since = (self._watermark - self.overlap) if self._watermark else (
            now - timedelta(minutes=5)
        )

        try:
            payload = self.transport.get(
                self.mapper.path, self.mapper.params(since, now, count)
            )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.fetch_errors += 1
            logger.warning("Gateway fetch failed (%s): %s", self.mapper.provider, exc)
            return []

        self._watermark = now

        transactions = []
        for record in self.mapper.extract(payload):
            try:
                transaction = self.mapper.to_transaction(record, self.merchant_id)
            except (KeyError, TypeError, ValueError) as exc:
                # One malformed record must not cost us the whole window.
                self.fetch_errors += 1
                logger.warning("Skipping unmappable %s record: %s", self.mapper.provider, exc)
                continue

            if transaction.transaction_id in self._seen:
                continue
            self._seen.add(transaction.transaction_id)
            transactions.append(transaction)

        self._forget_old_ids()
        return transactions

    def signals(self) -> FrozenSet[str]:
        """
        Which signals this source can actually supply.

        The simulator supplies all of them; a gateway does not. Publishing the
        difference is what stops a detector drawing conclusions from a field
        that was only ever a default value.
        """
        return self.mapper.signals()

    def describe(self) -> str:
        missing = sorted(ALL_SIGNALS - self.signals())
        caveat = f"; no {', '.join(missing)}" if missing else ''
        note = getattr(self.mapper, 'caveat', '')
        return f"{self.mapper.provider} gateway ({self.merchant_id}{caveat}){note}"

    def _forget_old_ids(self, keep: int = 20_000):
        """
        Bound the dedupe set.

        It only has to cover the overlap window, but an unbounded set in a
        process designed to run for weeks is a slow leak.
        """
        if len(self._seen) > keep:
            self._seen = set(list(self._seen)[-keep // 2:])


class WebhookLatency:
    """
    Turns the latency signal on, honestly.

    A gateway's list API cannot tell you how long a payment took, but a webhook
    can: the payment carries the time it was created, and the receiver knows
    when it arrived. That difference is real, measurable, and the only latency
    a merchant can actually observe - so it is the one the agent gets, rather
    than a number chosen to look like one.

    It measures creation-to-notification, which includes the gateway's own
    webhook dispatch delay. That is a wider interval than pure authorization
    time, and it is named for what it is.
    """

    def __init__(self, source: PaymentGatewaySource):
        self.source = source
        self._received: Dict[str, datetime] = {}

    def record_receipt(self, payment_id: str, received_at: datetime = None):
        """Note when a webhook for this payment arrived."""
        self._received[payment_id] = received_at or datetime.now(timezone.utc)

    def apply(self, transactions: List[PaymentTransaction]) -> List[PaymentTransaction]:
        """Fill in latency for the transactions we have a receipt time for."""
        for transaction in transactions:
            received = self._received.pop(transaction.transaction_id, None)
            if received is None:
                continue
            created = transaction.timestamp
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            delta = (received - created).total_seconds() * 1000.0
            transaction.latency_ms = max(0.0, delta)
        return transactions

    def signals(self) -> FrozenSet[str]:
        return self.source.signals() | {SIGNAL_LATENCY}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _from_epoch(value: Any) -> datetime:
    """Epoch seconds to an aware datetime; both providers use seconds."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _issuer_from_razorpay(record: Dict[str, Any]) -> str:
    """
    The issuing bank, from whichever field this payment method puts it in.

    Razorpay reports it as `bank` for netbanking, inside `card` for cards, and
    as the handle suffix for UPI. Falling through them in order is not
    defensive coding - each method genuinely populates a different field.
    """
    bank = record.get('bank')
    if bank:
        return str(bank).upper()

    card = record.get('card') or {}
    if card.get('issuer'):
        return str(card['issuer']).upper()

    acquirer = record.get('acquirer_data') or {}
    if acquirer.get('bank'):
        return str(acquirer['bank']).upper()

    vpa = record.get('vpa')
    if vpa and '@' in vpa:
        return vpa.split('@', 1)[1].upper()

    wallet = record.get('wallet')
    if wallet:
        return str(wallet).upper()

    return 'UNKNOWN'


def _decline_reason(record: Dict[str, Any]) -> Optional[str]:
    """Stripe puts the useful decline detail in outcome.reason, not failure_code."""
    outcome = record.get('outcome') or {}
    return outcome.get('reason')
