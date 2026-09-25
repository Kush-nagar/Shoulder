"""The only module that imports `stripe` (Block 10M, test mode).

Tests mock this one module. Every call refuses a live secret key unless
`MARKETPLACE_LIVE=on`, so a mis-set production secret cannot move real money
before legal review signs off. Amounts are integer US cents.
"""

import json
import os
import time
from typing import Any
from uuid import UUID

import stripe

PLATFORM_FEE_PERCENT = 10
# Stripe refuses a Checkout `expires_at` under 30 minutes; the extra minute
# absorbs clock skew between this host and Stripe.
CHECKOUT_TTL_SECONDS = 31 * 60


class PaymentsUnavailable(Exception):
    """Stripe is not configured, refused, or failed. Never carries its message."""


class InvalidWebhook(Exception):
    """The payload or its signature did not verify."""


def platform_fee(price_cents: int) -> int:
    """10 % rounded half up; matches `round(price * 0.10)` in Postgres."""
    return (price_cents * PLATFORM_FEE_PERCENT + 50) // 100


def secret_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    live = os.environ.get("MARKETPLACE_LIVE", "").strip().lower() == "on"
    if key.startswith("sk_test_") or (live and key.startswith("sk_live_")):
        return key
    raise PaymentsUnavailable("stripe key missing or not allowed")


def origin() -> str:
    value = os.environ.get("APP_ORIGIN", "").strip().rstrip("/")
    if not value.startswith(("https://", "http://")):
        raise PaymentsUnavailable("APP_ORIGIN is not configured")
    return value


def _client() -> stripe.StripeClient:
    return stripe.StripeClient(secret_key())


def _call(operation: Any, params: Any, idempotency_key: str | None = None) -> Any:
    try:
        options: Any = {"idempotency_key": idempotency_key} if idempotency_key else {}
        return operation(params=params, options=options)
    except stripe.StripeError:
        raise PaymentsUnavailable("stripe request failed") from None


def create_express_account(coach_profile_id: UUID) -> str:
    """One Express account per coach profile; retries return the same account."""
    account = _call(
        _client().v1.accounts.create,
        {
            "type": "express",
            "country": "US",
            "capabilities": {
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            "metadata": {"coach_profile_id": str(coach_profile_id)},
        },
        f"account-{coach_profile_id}",
    )
    return str(account.id)


def account_link(account_id: str) -> str:
    base = origin()
    link = _call(
        _client().v1.account_links.create,
        {
            "account": account_id,
            "refresh_url": f"{base}/coaching/coach?stripe=refresh",
            "return_url": f"{base}/coaching/coach?stripe=return",
            "type": "account_onboarding",
        },
    )
    return str(link.url)


def create_checkout_session(
    *,
    booking_id: UUID,
    price_cents: int,
    destination_account: str,
    description: str,
) -> tuple[str, str]:
    """Destination charge to the coach; the platform keeps a 10 % fee.

    Returns (session id, hosted checkout URL).
    """
    base = origin()
    metadata = {"booking_id": str(booking_id)}
    session = _call(
        _client().v1.checkout.sessions.create,
        {
            "mode": "payment",
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": price_cents,
                        "product_data": {"name": description},
                    },
                }
            ],
            "payment_intent_data": {
                "application_fee_amount": platform_fee(price_cents),
                "transfer_data": {"destination": destination_account},
                "metadata": metadata,
            },
            "metadata": metadata,
            "expires_at": int(time.time()) + CHECKOUT_TTL_SECONDS,
            "success_url": f"{base}/coaching/bookings?booking={booking_id}",
            "cancel_url": f"{base}/coaching/bookings",
        },
    )
    return str(session.id), str(session.url)


def refund(payment_intent: str, amount: int | None = None) -> None:
    """Refund to the player, pulling the coach transfer and fee back with it.

    Idempotent per payment intent and amount, so a retried cancel or webhook
    never refunds twice.
    """
    params: dict[str, Any] = {
        "payment_intent": payment_intent,
        "reverse_transfer": True,
        "refund_application_fee": True,
    }
    if amount is not None:
        params["amount"] = amount
    _call(
        _client().v1.refunds.create,
        params,
        f"refund-{payment_intent}-{amount if amount is not None else 'full'}",
    )


def verify_webhook(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    """The verified event as plain JSON, or InvalidWebhook."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise PaymentsUnavailable("webhook secret is not configured")
    try:
        stripe.Webhook.construct_event(payload, sig_header, secret)
        event = json.loads(payload)
    except (ValueError, stripe.SignatureVerificationError):
        raise InvalidWebhook from None
    if not isinstance(event, dict):
        raise InvalidWebhook
    return event
