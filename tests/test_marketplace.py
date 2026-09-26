"""Block 10M coach marketplace (adults only, Stripe test mode).

The unit tests mock `services.api.payments` (or the Stripe SDK beneath it) and
need no database. The database tests run through `shoulder_api` under RLS and
the definer functions of migration 0020.
"""

import dataclasses
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

import stripe
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from services.api import marketplace_routes, marketplace_service, payments
from services.api.auth import authenticated_identity
from services.api.main import app
from services.api.schemas import BookingCreate, CoachProfileUpdate, CoachSlotCreate
from services.worker import jobs, retention

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402

WORKER_URL = os.environ.get("WORKER_DATABASE_URL")
ON = {"MARKETPLACE_ENABLED": "on"}
WEBHOOK_SECRET = "whsec_test_secret"
GATED_PATHS = (
    ("get", "/v1/me/age-attestation"),
    ("put", "/v1/me/age-attestation"),
    ("get", "/v1/coach-profile"),
    ("post", "/v1/coach-profile/submit"),
    ("get", "/v1/admin/coach-reviews"),
    ("get", f"/v1/admin/coach-reviews/{UUID(int=1)}/documents/{UUID(int=2)}/url"),
    ("get", "/v1/marketplace/coaches"),
    ("post", "/v1/marketplace/bookings"),
    ("get", "/v1/me/bookings"),
    ("post", "/v1/stripe/webhook"),
)


def signed(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    stamp = int(time.time())
    digest = hmac.new(
        secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={stamp},v1={digest}"


class MoneyRuleTests(unittest.TestCase):
    def test_fee_is_ten_percent_rounded_half_up_like_postgres(self) -> None:
        for price in (1, 5, 500, 1000, 1004, 1005, 1015, 2250, 3333, 50000, 150000):
            expected = int(
                (Decimal(price) * Decimal("0.10")).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
            self.assertEqual(payments.platform_fee(price), expected, price)
        self.assertEqual(payments.platform_fee(4500), 450)

    def test_cancel_refund_is_decided_by_the_database_not_the_caller(self) -> None:
        # The 24-hour rule lives in `private.cancel_coach_booking`; the API
        # sends only the booking id and refunds exactly what it returns.
        connection = mock.Mock()
        booking = uuid4()
        with mock.patch.object(payments, "refund") as refund:
            for status, cents, intent, calls in (
                ("cancelled_by_player", 6000, "pi_1", 1),
                ("cancelled_by_player", 0, "pi_1", 0),
                ("cancelled_by_coach", 6000, None, 0),  # never paid
            ):
                refund.reset_mock()
                connection.execute.return_value.one.return_value = mock.Mock(
                    status=status, refund_cents=cents, stripe_payment_intent_id=intent
                )
                self.assertEqual(
                    marketplace_service.cancel_booking(connection, booking),
                    (status, cents),
                )
                sql, params = connection.execute.call_args.args
                self.assertIn("cancel_coach_booking(:id)", str(sql))
                self.assertEqual(params, {"id": str(booking)})
                self.assertEqual(refund.call_count, calls)
            refund.reset_mock()
            connection.execute.return_value.one.return_value = mock.Mock(
                status="cancelled_by_player",
                refund_cents=6000,
                stripe_payment_intent_id="pi_9",
            )
            marketplace_service.cancel_booking(connection, booking)
            refund.assert_called_once_with("pi_9", 6000)


class StripeKeyTests(unittest.TestCase):
    def key_with(self, **env: str) -> str:
        with mock.patch.dict(
            os.environ, {"STRIPE_SECRET_KEY": "", "MARKETPLACE_LIVE": "", **env}
        ):
            return payments.secret_key()

    def test_only_test_keys_unless_live_is_on(self) -> None:
        self.assertEqual(self.key_with(STRIPE_SECRET_KEY="sk_test_1"), "sk_test_1")
        for env in (
            {"STRIPE_SECRET_KEY": "sk_live_1"},
            {"STRIPE_SECRET_KEY": "sk_live_1", "MARKETPLACE_LIVE": "yes"},
            {"STRIPE_SECRET_KEY": "rk_live_1", "MARKETPLACE_LIVE": "on"},
            {"STRIPE_SECRET_KEY": ""},
        ):
            with self.subTest(env=env):
                with self.assertRaises(payments.PaymentsUnavailable):
                    self.key_with(**env)
        self.assertEqual(
            self.key_with(STRIPE_SECRET_KEY="sk_live_1", MARKETPLACE_LIVE="on"),
            "sk_live_1",
        )

    def test_live_key_never_reaches_stripe(self) -> None:
        with (
            mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_x"}),
            mock.patch.object(stripe, "StripeClient") as client,
        ):
            with self.assertRaises(payments.PaymentsUnavailable):
                payments.refund("pi_1")
        client.assert_not_called()


class StripeCallTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(
            os.environ,
            {"STRIPE_SECRET_KEY": "sk_test_x", "APP_ORIGIN": "https://app.test/"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        client = mock.patch.object(stripe, "StripeClient")
        self.client = client.start().return_value
        self.addCleanup(client.stop)

    def test_checkout_is_a_destination_charge_with_the_fee(self) -> None:
        session = self.client.v1.checkout.sessions.create
        session.return_value = mock.Mock(id="cs_test_1", url="https://pay/cs_test_1")
        booking = uuid4()
        before = int(time.time())
        result = payments.create_checkout_session(
            booking_id=booking,
            price_cents=4500,
            destination_account="acct_1",
            description="Coaching session with Sam",
        )
        self.assertEqual(result, ("cs_test_1", "https://pay/cs_test_1"))
        params = session.call_args.kwargs["params"]
        intent = params["payment_intent_data"]
        self.assertEqual(intent["application_fee_amount"], 450)
        self.assertEqual(intent["transfer_data"], {"destination": "acct_1"})
        self.assertEqual(params["metadata"], {"booking_id": str(booking)})
        # Cards only: no delayed method can settle after the hold lapses.
        self.assertEqual(params["payment_method_types"], ["card"])
        self.assertEqual(params["line_items"][0]["price_data"]["unit_amount"], 4500)
        self.assertGreaterEqual(params["expires_at"] - before, 30 * 60)
        self.assertTrue(params["success_url"].startswith("https://app.test/coaching"))

    def test_refund_reverses_the_transfer_and_is_idempotent(self) -> None:
        refunds = self.client.v1.refunds.create
        payments.refund("pi_1", 2000)
        payments.refund("pi_1")
        first, second = refunds.call_args_list
        self.assertEqual(first.kwargs["params"]["amount"], 2000)
        self.assertTrue(first.kwargs["params"]["reverse_transfer"])
        self.assertTrue(first.kwargs["params"]["refund_application_fee"])
        self.assertNotIn("amount", second.kwargs["params"])
        self.assertEqual(first.kwargs["options"]["idempotency_key"], "refund-pi_1-2000")
        self.assertEqual(
            second.kwargs["options"]["idempotency_key"], "refund-pi_1-full"
        )

    def test_client_has_a_short_timeout_and_one_retry(self) -> None:
        payments.refund("pi_1")
        kwargs = stripe.StripeClient.call_args.kwargs  # type: ignore[attr-defined]
        self.assertEqual(kwargs["max_network_retries"], 1)
        self.assertEqual(kwargs["http_client"]._timeout, 10)

    def test_stripe_errors_never_escape_with_their_message(self) -> None:
        self.client.v1.refunds.create.side_effect = stripe.StripeError(
            "card sk_test_secret declined"
        )
        with self.assertRaises(payments.PaymentsUnavailable) as caught:
            payments.refund("pi_1")
        self.assertNotIn("sk_test", str(caught.exception))


class SchemaTests(unittest.TestCase):
    def test_slot_shape(self) -> None:
        start = datetime(2030, 1, 1, 10, tzinfo=UTC)
        ok = CoachSlotCreate(
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            format="online",
            venue="ignored",
        )
        self.assertIsNone(ok.venue)
        for ends, fmt, venue in (
            (start + timedelta(minutes=29), "online", None),
            (start + timedelta(hours=3, minutes=1), "online", None),
            (start + timedelta(hours=1), "in_person", None),
        ):
            with self.assertRaises(ValidationError):
                CoachSlotCreate.model_validate(
                    {"starts_at": start, "ends_at": ends, "format": fmt, "venue": venue}
                )

    def test_profile_refuses_unknown_specialties_and_extra_fields(self) -> None:
        base: dict[str, Any] = {
            "display_name": "Sam Coach",
            "specialties": ["passing", "passing"],
            "city": "Leeds",
            "formats": ["online"],
            "rate_cents": 4000,
        }
        self.assertEqual(
            CoachProfileUpdate.model_validate(base).specialties, ["passing"]
        )
        changes: tuple[dict[str, Any], ...] = (
            {"specialties": ["rating"]},
            {"rate_cents": 999},
            {"status": "verified"},
            {"formats": []},
        )
        for change in changes:
            with self.assertRaises(ValidationError, msg=change):
                CoachProfileUpdate.model_validate({**base, **change})

    def test_free_text_refuses_contact_details(self) -> None:
        start = datetime(2030, 1, 1, 10, tzinfo=UTC)
        slot = {
            "starts_at": start,
            "ends_at": start + timedelta(hours=1),
            "format": "in_person",
        }
        profile: dict[str, Any] = {
            "display_name": "Sam Coach",
            "specialties": ["passing"],
            "city": "Leeds",
            "formats": ["online"],
            "rate_cents": 4000,
        }
        contacts = (
            "mail sam@coach.test",
            "call 07700 900123",
            "call +1 (555) 123-4567",
            "see https://sam.example",
            "www.samcoach.net",
            "samcoach.com",
            "DM @samcoach",
            "find me on Instagram",
            "snap me",
            "WhatsApp only",
            "telegram: sam",
        )
        for text_value in contacts:
            with self.subTest(text=text_value):
                for build in (
                    lambda v: CoachSlotCreate.model_validate({**slot, "venue": v}),
                    lambda v: BookingCreate(slot_id=uuid4(), note=v),
                    lambda v: CoachProfileUpdate.model_validate({**profile, "bio": v}),
                    lambda v: CoachProfileUpdate.model_validate(
                        {**profile, "display_name": v[:60]}
                    ),
                ):
                    with self.assertRaises(ValidationError):
                        build(text_value)
        # Ordinary text passes.
        self.assertEqual(
            CoachSlotCreate.model_validate(
                {**slot, "venue": "Roundhay Park pitch 3"}
            ).venue,
            "Roundhay Park pitch 3",
        )
        self.assertEqual(
            BookingCreate(slot_id=uuid4(), note="Working on my first touch").note,
            "Working on my first touch",
        )
        CoachProfileUpdate.model_validate(
            {**profile, "bio": "UEFA B licence, 10 years coaching instant decisions."}
        )


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_everything_is_404_while_the_flag_is_off(self) -> None:
        for value in ("", "off", "true"):
            with mock.patch.dict(os.environ, {"MARKETPLACE_ENABLED": value}):
                for method, path in GATED_PATHS:
                    with self.subTest(value=value, path=path):
                        response = getattr(self.client, method)(path)
                        self.assertEqual(response.status_code, 404, response.text)

    def test_signed_in_requests_are_still_404_while_off(self) -> None:
        app.dependency_overrides[authenticated_identity] = lambda: str(UUID(int=1))
        with mock.patch.dict(os.environ, {"MARKETPLACE_ENABLED": ""}):
            self.assertEqual(self.client.get("/v1/coach-profile").status_code, 404)

    def test_booking_without_stripe_configured_is_a_503_problem(self) -> None:
        # No key (or a live key while live mode is off): the slot hold rolls
        # back and the client gets a slug it can branch on.
        app.dependency_overrides[authenticated_identity] = lambda: str(UUID(int=1))
        connection = mock.MagicMock()
        transaction = mock.MagicMock()
        transaction.__enter__.return_value = connection
        for key in ("", "sk_live_1"):
            env = {**ON, "STRIPE_SECRET_KEY": key, "MARKETPLACE_LIVE": ""}
            with (
                self.subTest(key=key),
                mock.patch.dict(os.environ, env),
                mock.patch.object(
                    marketplace_routes, "user_transaction", return_value=transaction
                ),
                mock.patch.object(
                    marketplace_service,
                    "book",
                    side_effect=lambda _c, _b: payments.secret_key(),
                ),
            ):
                response = self.client.post(
                    "/v1/marketplace/bookings", json={"slot_id": str(uuid4())}
                )
            self.assertEqual(response.status_code, 503, response.text)
            body = response.json()
            self.assertTrue(body["type"].endswith("/payments-unavailable"))
            self.assertEqual(
                body["detail"], "Booking opens soon. Payments are being set up."
            )
            self.assertNotIn("sk_", response.text)

    def test_webhook_signature_failure_is_400(self) -> None:
        payload = json.dumps({"id": "evt_1", "type": "account.updated"}).encode()
        env = {**ON, "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(marketplace_routes, "run") as run,
        ):
            for header in (None, "t=1,v1=bad", signed(payload, "whsec_other")):
                with self.subTest(header=header):
                    headers = {"stripe-signature": header} if header else {}
                    response = self.client.post(
                        "/v1/stripe/webhook", content=payload, headers=headers
                    )
                    self.assertEqual(response.status_code, 400, response.text)
            run.assert_not_called()

    def test_verified_webhook_reaches_the_service_as_plain_json(self) -> None:
        profile = str(uuid4())
        event = {
            "id": "evt_2",
            "type": "account.updated",
            "data": {
                "object": {
                    "id": "acct_1",
                    "charges_enabled": True,
                    "metadata": {"coach_profile_id": profile},
                }
            },
        }
        payload = json.dumps(event).encode()
        env = {**ON, "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET}
        connection = mock.Mock()
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(
                marketplace_routes, "run", side_effect=lambda _u, work: work(connection)
            ),
        ):
            response = self.client.post(
                "/v1/stripe/webhook",
                content=payload,
                headers={"stripe-signature": signed(payload)},
            )
        self.assertEqual(response.status_code, 204, response.text)
        params = connection.execute.call_args.args[1]
        self.assertEqual(
            params, {"profile": profile, "account": "acct_1", "enabled": True}
        )

    def test_oversized_webhook_is_refused_before_verification(self) -> None:
        with mock.patch.dict(os.environ, ON):
            response = self.client.post(
                "/v1/stripe/webhook", content=b"x" * (300 * 1024)
            )
        self.assertEqual(response.status_code, 413)

    def test_completed_checkout_refunds_what_the_database_decides(self) -> None:
        connection = mock.Mock()
        booking = str(uuid4())
        session: dict[str, Any] = {
            "id": "cs_1",
            "payment_status": "paid",
            "payment_intent": "pi_1",
            "metadata": {"booking_id": booking},
        }
        with mock.patch.object(payments, "refund") as refund:
            for kind in (
                "checkout.session.completed",
                "checkout.session.async_payment_succeeded",
            ):
                event = {"type": kind, "data": {"object": session}}
                for outcome, amount, refunds in (
                    ("confirmed", 0, []),
                    ("ignored", 0, []),
                    ("refund", None, [mock.call("pi_1", None)]),
                    ("refund", 4000, [mock.call("pi_1", 4000)]),
                ):
                    with self.subTest(kind=kind, outcome=outcome, amount=amount):
                        refund.reset_mock()
                        connection.execute.return_value.one.return_value = (
                            outcome,
                            amount,
                        )
                        marketplace_service.apply_event(connection, event)
                        self.assertEqual(refund.call_args_list, refunds)
                        self.assertEqual(
                            connection.execute.call_args.args[1],
                            {"booking": booking, "session": "cs_1", "intent": "pi_1"},
                        )

    def test_sessions_this_app_did_not_create_are_never_touched(self) -> None:
        # No `booking_id` metadata (or not a UUID): not ours, so no database
        # call and no refund, whatever the event says.
        connection = mock.Mock()
        with mock.patch.object(payments, "refund") as refund:
            for metadata in (None, {}, {"booking_id": "not-a-uuid"}):
                for kind in (
                    "checkout.session.completed",
                    "checkout.session.async_payment_succeeded",
                    "checkout.session.expired",
                    "checkout.session.async_payment_failed",
                ):
                    obj: dict[str, Any] = {
                        "id": "cs_other",
                        "payment_status": "paid",
                        "payment_intent": "pi_other",
                    }
                    if metadata is not None:
                        obj["metadata"] = metadata
                    marketplace_service.apply_event(
                        connection, {"type": kind, "data": {"object": obj}}
                    )
            marketplace_service.apply_event(
                connection,
                {"type": "account.updated", "data": {"object": {"id": "acct_x"}}},
            )
        connection.execute.assert_not_called()
        refund.assert_not_called()
        # An unpaid completion with our metadata is ignored too.
        marketplace_service.apply_event(
            connection,
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_1",
                        "payment_status": "unpaid",
                        "metadata": {"booking_id": str(uuid4())},
                    }
                },
            },
        )
        connection.execute.assert_not_called()

    def test_failed_async_payment_expires_like_a_lapsed_session(self) -> None:
        booking = str(uuid4())
        for kind in (
            "checkout.session.expired",
            "checkout.session.async_payment_failed",
        ):
            connection = mock.Mock()
            marketplace_service.apply_event(
                connection,
                {
                    "type": kind,
                    "data": {
                        "object": {"id": "cs_1", "metadata": {"booking_id": booking}}
                    },
                },
            )
            sql, params = connection.execute.call_args.args
            self.assertIn("expire_booking_checkout", str(sql))
            self.assertEqual(params, {"booking": booking, "session": "cs_1"})


# -- database ---------------------------------------------------------------------

PUBLIC_COLUMNS = {
    "id",
    "display_name",
    "bio",
    "specialties",
    "city",
    "formats",
    "rate_cents",
    "verified_at",
}


@unittest.skipUnless(CONFIGURED, "database URLs are not configured")
class MarketplaceDatabaseTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        year = datetime.now(UTC).year
        self.adult = self.create_auth_user("mk.adult@example.test", "Alex Adult")
        self.adult_b = self.create_auth_user("mk.adultb@example.test", "Bea Adult")
        self.minor = self.create_auth_user("mk.minor@example.test", "Max Minor")
        self.unattested = self.create_auth_user("mk.none@example.test", "Nia None")
        self.coach_user = self.create_auth_user("mk.coach@example.test", "Cal Coach")
        self.coach_b_user = self.create_auth_user("mk.coachb@example.test", "Dee Coach")
        self.admin_user = self.create_auth_user("mk.admin@example.test", "Ada Admin")
        for user in (self.adult, self.adult_b, self.coach_user, self.coach_b_user):
            self.attest(user, 1990)
        self.attest(self.admin_user, 1980)
        self.attest(self.minor, year - 15)
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text("INSERT INTO app.platform_admin (user_id) VALUES (:id)"),
                {"id": self.admin_user},
            )
        self.coach = self.profile(self.coach_user, "verified")
        self.coach_b = self.profile(self.coach_b_user, "verified")
        self.slot = self.add_slot(self.coach)

    # -- fixtures -------------------------------------------------------------

    def attest(self, user: UUID, year: int) -> None:
        with self.admin.connect() as connection, connection.begin():
            connection.execute(
                text(
                    "INSERT INTO app.age_attestation (user_id, birth_year)"
                    " VALUES (:id, :year)"
                ),
                {"id": user, "year": year},
            )

    def profile(self, user: UUID, status: str, charges: bool = True) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.coach_profile (
                                user_id, display_name, bio, specialties, city,
                                formats, rate_cents, status, review_note,
                                stripe_account_id, charges_enabled
                            ) VALUES (
                                :user, 'Coach ' || left(:user_text, 6), 'Bio',
                                ARRAY['passing'], 'Leeds', ARRAY['online'], 4000,
                                :status, 'private note', 'acct_' || left(:user_text, 8),
                                :charges
                            ) RETURNING id
                        """),
                        {
                            "user": user,
                            "user_text": str(user),
                            "status": status,
                            "charges": charges,
                        },
                    ).scalar_one()
                )
            )

    def add_slot(self, profile: UUID, hours: int = 48) -> UUID:
        with self.admin.connect() as connection, connection.begin():
            return UUID(
                str(
                    connection.execute(
                        text("""
                            INSERT INTO app.coach_slot (
                                coach_profile_id, starts_at, ends_at, format
                            ) VALUES (
                                :profile, now() + make_interval(hours => :hours),
                                now() + make_interval(hours => :hours, mins => 90),
                                'online'
                            ) RETURNING id
                        """),
                        {"profile": profile, "hours": hours},
                    ).scalar_one()
                )
            )

    def add_document(
        self, profile: UUID, status: str = "ready", kind: str = "background_check"
    ) -> UUID:
        document = uuid4()
        self.admin_sql(
            "INSERT INTO app.coach_document (id, coach_profile_id, kind, object_key,"
            " content_type, size_bytes, status) VALUES (CAST(:id AS uuid),"
            " CAST(:p AS uuid), :kind, :key, 'application/pdf', 10, :status)",
            id=str(document),
            p=str(profile),
            kind=kind,
            key=f"coach-docs/{profile}/{document}.pdf",
            status=status,
        )
        return document

    def confirmed_booking(
        self, player: UUID, profile: UUID, status: str = "confirmed"
    ) -> UUID:
        """A settled booking on a fresh slot, written as the migration role."""
        slot = self.add_slot(profile)
        return UUID(
            str(
                self.admin_sql(
                    "INSERT INTO app.coach_booking (slot_id, coach_profile_id,"
                    " player_user_id, status, price_cents, platform_fee_cents,"
                    " stripe_payment_intent_id) VALUES (CAST(:s AS uuid),"
                    " CAST(:p AS uuid), CAST(:u AS uuid), :status, 6000, 600,"
                    " :intent) RETURNING id",
                    s=str(slot),
                    p=str(profile),
                    u=str(player),
                    status=status,
                    intent=f"pi_{slot.hex}",
                )[0].id
            )
        )

    def checkout(self, player: UUID, session: str) -> Any:
        """Hold the default slot and record a Checkout session for it."""
        booking = self.book(player)
        self.as_(
            player,
            "SELECT private.attach_booking_checkout(:id, :s)",
            id=booking.booking_id,
            s=session,
        )
        return booking

    def confirm(self, booking: UUID, session: str, intent: str = "pi_1") -> Any:
        return self.as_(
            None,
            "SELECT outcome, refund_amount"
            " FROM private.confirm_booking_payment(:b, :s, :i)",
            b=booking,
            s=session,
            i=intent,
        )[0]

    def as_(self, user: UUID | None, sql: str, **params: Any) -> list[Any]:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, user)
            return list(connection.execute(text(sql), params).all())

    def refused(self, user: UUID | None, sql: str, **params: Any) -> str | None:
        with self.assertRaises(DBAPIError) as caught:
            self.as_(user, sql, **params)
        return sqlstate(caught.exception)

    def book(self, user: UUID, slot: UUID | None = None) -> Any:
        return self.as_(
            user,
            "SELECT * FROM private.book_coach_slot(:slot, 'hi')",
            slot=slot or self.slot,
        )[0]

    def listed(self, user: UUID | None) -> set[UUID]:
        rows = self.as_(user, "SELECT id FROM private.marketplace_coaches(NULL, NULL)")
        return {UUID(str(row.id)) for row in rows}

    def admin_sql(self, sql: str, **params: Any) -> list[Any]:
        with self.admin.connect() as connection, connection.begin():
            result = connection.execute(text(sql), params)
            return list(result.all()) if result.returns_rows else []

    # -- adults only ----------------------------------------------------------

    def test_non_adults_cannot_browse_or_book(self) -> None:
        self.assertEqual(self.listed(self.adult), {self.coach, self.coach_b})
        for user in (self.minor, self.unattested, None):
            with self.subTest(user=user):
                self.assertEqual(self.listed(user), set())
                self.assertEqual(
                    self.as_(
                        user,
                        "SELECT * FROM private.marketplace_coach_slots(:id)",
                        id=self.coach,
                    ),
                    [],
                )
                self.assertEqual(
                    self.refused(
                        user,
                        "SELECT * FROM private.book_coach_slot(:slot, NULL)",
                        slot=self.slot,
                    ),
                    "42501",
                )

    def test_attested_age_cannot_be_raised(self) -> None:
        self.assertEqual(
            self.refused(self.minor, "SELECT private.attest_age(1990)"), "55000"
        )
        self.assertEqual(self.listed(self.minor), set())
        self.as_(self.adult, "SELECT private.attest_age(1995)")  # younger is fine

    def test_hidden_coaches_are_unbookable(self) -> None:
        cases = {
            "pending_review": self.profile(
                self.create_auth_user("mk.p@example.test"), "pending_review"
            ),
            "suspended": self.profile(
                self.create_auth_user("mk.s@example.test"), "suspended"
            ),
            "no_charges": self.profile(
                self.create_auth_user("mk.n@example.test"), "verified", charges=False
            ),
        }
        # A report blocks only once its reporter has paid for a session.
        self.admin_sql(
            "INSERT INTO app.marketplace_report (reporter_user_id, coach_profile_id,"
            " reason) VALUES (:user, :coach, 'Asked to meet at his house')",
            user=self.adult_b,
            coach=self.coach_b,
        )
        self.assertIn(self.coach_b, self.listed(self.adult))
        self.confirmed_booking(self.adult_b, self.coach_b)
        cases["reported"] = self.coach_b
        listed = self.listed(self.adult)
        for label, profile in cases.items():
            with self.subTest(label=label):
                self.assertNotIn(profile, listed)
                slot = self.add_slot(profile)
                self.assertEqual(
                    self.as_(
                        self.adult,
                        "SELECT * FROM private.marketplace_coach_slots(:id)",
                        id=profile,
                    ),
                    [],
                )
                self.assertEqual(
                    self.refused(
                        self.adult,
                        "SELECT * FROM private.book_coach_slot(:slot, NULL)",
                        slot=slot,
                    ),
                    "P0002",
                )

    def test_past_slots_and_own_slots_are_unbookable(self) -> None:
        past = self.add_slot(self.coach, hours=-3)
        self.assertEqual(
            self.refused(
                self.adult, "SELECT * FROM private.book_coach_slot(:s, NULL)", s=past
            ),
            "P0002",
        )
        self.assertEqual(
            self.refused(
                self.coach_user,
                "SELECT * FROM private.book_coach_slot(:s, NULL)",
                s=self.slot,
            ),
            "42501",
        )

    def test_browse_returns_public_columns_only(self) -> None:
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.adult)
            result = connection.execute(
                text("SELECT * FROM private.marketplace_coaches('passing', ' leeds ')")
            )
            self.assertEqual(set(result.keys()), PUBLIC_COLUMNS)
            rows = result.all()
        self.assertEqual({UUID(str(r.id)) for r in rows}, {self.coach, self.coach_b})
        payload = json.dumps([dict(r._mapping) for r in rows], default=str)
        for secret in ("acct_", "private note", str(self.coach_user)):
            self.assertNotIn(secret, payload)
        self.assertEqual(
            self.as_(
                self.adult,
                "SELECT id FROM private.marketplace_coaches('tactics', NULL)",
            ),
            [],
        )
        # Adults read no profile row directly; only the function.
        self.assertEqual(self.as_(self.adult, "SELECT id FROM app.coach_profile"), [])

    # -- isolation ------------------------------------------------------------

    def test_coach_cannot_read_another_coachs_documents_or_bookings(self) -> None:
        self.add_document(self.coach)
        booking = self.book(self.adult)
        own = self.as_(self.coach_user, "SELECT * FROM private.coach_booking_list()")
        self.assertEqual([UUID(str(r.id)) for r in own], [booking.booking_id])
        self.assertEqual(own[0].player_first_name, "Alex")
        self.assertNotIn("player_user_id", own[0]._mapping)
        for sql in (
            "SELECT id FROM app.coach_document",
            "SELECT id FROM app.coach_booking",
            "SELECT id FROM app.coach_slot WHERE coach_profile_id = :other",
            "SELECT id FROM app.coach_profile WHERE id = :other",
            "SELECT id FROM private.coach_booking_list()",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(self.as_(self.coach_b_user, sql, other=self.coach), [])
        # Writes on another coach's rows touch nothing.
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, self.coach_b_user)
            changed = connection.execute(
                text("UPDATE app.coach_slot SET status = 'cancelled' WHERE id = :id"),
                {"id": self.slot},
            ).rowcount
        self.assertEqual(changed, 0)

    def test_player_cannot_read_another_players_bookings(self) -> None:
        booking = self.book(self.adult)
        mine = self.as_(self.adult, "SELECT id FROM private.player_booking_list()")
        self.assertEqual([UUID(str(r.id)) for r in mine], [booking.booking_id])
        for sql in (
            "SELECT id FROM app.coach_booking",
            "SELECT id FROM private.player_booking_list()",
        ):
            self.assertEqual(self.as_(self.adult_b, sql), [])
        self.assertEqual(
            self.refused(
                self.adult_b,
                "SELECT * FROM private.cancel_coach_booking(:id)",
                id=booking.booking_id,
            ),
            "P0002",
        )

    def test_admin_reads_everything_and_others_read_no_admin_data(self) -> None:
        self.book(self.adult)
        for table in ("coach_profile", "coach_booking", "marketplace_audit"):
            with self.subTest(table=table):
                self.assertTrue(self.as_(self.admin_user, f"SELECT 1 FROM app.{table}"))
                self.assertEqual(
                    self.as_(self.adult_b, f"SELECT 1 FROM app.{table}"), []
                )
        self.assertEqual(self.as_(self.adult, "SELECT 1 FROM app.platform_admin"), [])

    def test_coach_cannot_verify_themselves(self) -> None:
        pending = self.profile(self.create_auth_user("mk.self@example.test"), "draft")
        owner = self.admin_sql(
            "SELECT user_id FROM app.coach_profile WHERE id = :id", id=pending
        )[0].user_id
        self.assertEqual(
            self.refused(owner, "UPDATE app.coach_profile SET status = 'verified'"),
            "42501",
        )
        self.assertEqual(
            self.refused(
                owner,
                "SELECT private.set_coach_profile_status(:id, 'verified', NULL)",
                id=pending,
            ),
            "55000",
        )
        # Submitting needs a ready background check.
        self.assertEqual(
            self.refused(
                owner,
                "SELECT private.set_coach_profile_status(:id, 'pending_review', NULL)",
                id=pending,
            ),
            "23514",
        )
        self.add_document(pending)
        self.as_(
            owner,
            "SELECT private.set_coach_profile_status(:id, 'pending_review', NULL)",
            id=pending,
        )
        self.as_(
            self.admin_user,
            "SELECT private.set_coach_profile_status(:id, 'verified', 'ok')",
            id=pending,
        )
        # Editing the rate sends a verified profile back to review.
        self.as_(owner, "UPDATE app.coach_profile SET rate_cents = 6000 RETURNING id")
        status = self.admin_sql(
            "SELECT status FROM app.coach_profile WHERE id = :id", id=pending
        )[0].status
        self.assertEqual(status, "pending_review")

    # -- audit ----------------------------------------------------------------

    def test_audit_rows_are_written_and_immutable(self) -> None:
        booking = self.book(self.adult)
        actions = {
            (row.action, row.actor_user_id)
            for row in self.admin_sql(
                "SELECT action, actor_user_id FROM app.marketplace_audit"
                " WHERE subject_id IN (:b, :s)",
                b=booking.booking_id,
                s=self.slot,
            )
        }
        self.assertIn(("coach_booking.pending_payment", self.adult), actions)
        self.assertIn(("coach_slot.held", self.adult), actions)
        for user in (self.admin_user, self.adult):
            for sql in (
                "UPDATE app.marketplace_audit SET action = 'x'",
                "DELETE FROM app.marketplace_audit",
                "INSERT INTO app.marketplace_audit (action) VALUES ('forged')",
            ):
                with self.subTest(user=user, sql=sql):
                    self.assertEqual(self.refused(user, sql), "42501")

    # -- booking concurrency and holds -----------------------------------------

    def test_two_concurrent_bookings_of_one_slot_one_wins(self) -> None:
        outcome: dict[str, Any] = {}

        def second() -> None:
            try:
                outcome["row"] = self.book(self.adult_b)
            except DBAPIError as error:
                outcome["state"] = sqlstate(error)

        with self.runtime.connect() as connection:
            transaction = connection.begin()
            self.as_user(connection, self.adult)
            first = connection.execute(
                text("SELECT * FROM private.book_coach_slot(:slot, NULL)"),
                {"slot": self.slot},
            ).one()
            racer = threading.Thread(target=second)
            racer.start()
            racer.join(timeout=1.0)
            self.assertTrue(racer.is_alive(), "the second booking must wait")
            transaction.commit()
        racer.join(timeout=10)
        self.assertEqual(outcome, {"state": "23505"})
        rows = self.admin_sql(
            "SELECT id, player_user_id FROM app.coach_booking WHERE slot_id = :s",
            s=self.slot,
        )
        self.assertEqual(
            [(r.id, r.player_user_id) for r in rows],
            [(first.booking_id, self.adult)],
        )

    def test_stale_holds_expire_and_the_slot_can_be_rebooked(self) -> None:
        booking = self.book(self.adult)
        self.admin_sql(
            "UPDATE app.coach_booking SET hold_expires_at = now() - interval '1 minute'"
            " WHERE id = :id",
            id=booking.booking_id,
        )
        self.assertEqual(
            self.as_(self.adult_b, "SELECT private.expire_marketplace_holds()")[0][0], 1
        )
        state = self.admin_sql(
            "SELECT b.status, s.status AS slot FROM app.coach_booking b"
            " JOIN app.coach_slot s ON s.id = b.slot_id WHERE b.id = :id",
            id=booking.booking_id,
        )[0]
        self.assertEqual((state.status, state.slot), ("expired", "open"))
        again = self.book(self.adult_b)
        self.assertEqual(again.booking_id, booking.booking_id)  # slot_id is unique
        self.assertEqual(
            self.as_(self.adult, "SELECT id FROM private.player_booking_list()"), []
        )

    def test_payment_confirms_once_and_late_payments_refund(self) -> None:
        booking = self.checkout(self.adult, "cs_test_1")
        for _ in range(2):
            self.assertEqual(
                tuple(self.confirm(booking.booking_id, "cs_test_1")), ("confirmed", 0)
            )
        # Not a session this app recorded for that booking: never touched.
        self.assertEqual(
            tuple(self.confirm(booking.booking_id, "cs_unknown")), ("ignored", 0)
        )
        self.assertEqual(tuple(self.confirm(uuid4(), "cs_test_1")), ("ignored", 0))
        slot = self.admin_sql(
            "SELECT status FROM app.coach_slot WHERE id = :id", id=self.slot
        )
        self.assertEqual(slot[0].status, "booked")
        # 48 h out: the function itself grants the full refund.
        cancelled = self.as_(
            self.adult,
            "SELECT * FROM private.cancel_coach_booking(:id)",
            id=booking.booking_id,
        )[0]
        self.assertEqual(
            (
                cancelled.status,
                cancelled.refund_cents,
                cancelled.stripe_payment_intent_id,
            ),
            ("cancelled_by_player", booking.price_cents, "pi_1"),
        )
        # A replayed completion after the cancel does not refund again.
        self.assertEqual(
            tuple(self.confirm(booking.booking_id, "cs_test_1")), ("ignored", 0)
        )

    def expire_hold(self, booking: UUID) -> None:
        self.admin_sql(
            "UPDATE app.coach_booking SET hold_expires_at = now() - interval '1 minute'"
            " WHERE id = :id",
            id=booking,
        )
        self.as_(self.adult, "SELECT private.expire_marketplace_holds()")

    def test_a_lapsed_session_whose_slot_was_rebooked_refunds_in_full(self) -> None:
        first = self.checkout(self.adult, "cs_a")
        self.expire_hold(first.booking_id)
        second = self.checkout(self.adult_b, "cs_b")
        self.assertEqual(second.booking_id, first.booking_id)
        self.assertEqual(
            tuple(self.confirm(first.booking_id, "cs_a")), ("refund", None)
        )
        self.assertEqual(
            tuple(self.confirm(second.booking_id, "cs_b", "pi_2")), ("confirmed", 0)
        )

    def test_late_payment_rechecks_the_coach(self) -> None:
        booking = self.checkout(self.adult, "cs_late")
        self.expire_hold(booking.booking_id)
        self.admin_sql(
            "UPDATE app.coach_profile SET status = 'suspended' WHERE id = :id",
            id=self.coach,
        )
        self.assertEqual(
            tuple(self.confirm(booking.booking_id, "cs_late")), ("refund", None)
        )
        row = self.admin_sql(
            "SELECT status, refund_cents FROM app.coach_booking WHERE id = :id",
            id=booking.booking_id,
        )[0]
        self.assertEqual(
            (row.status, row.refund_cents), ("expired", booking.price_cents)
        )
        # Reinstated later, the replayed event still refunds; it never confirms.
        self.admin_sql(
            "UPDATE app.coach_profile SET status = 'verified' WHERE id = :id",
            id=self.coach,
        )
        self.assertEqual(
            tuple(self.confirm(booking.booking_id, "cs_late")), ("refund", None)
        )
        # A late payment for a still-bookable coach and open slot confirms.
        slot = self.add_slot(self.coach_b)
        other = self.book(self.adult, slot)
        self.as_(
            self.adult,
            "SELECT private.attach_booking_checkout(:id, 'cs_ok')",
            id=other.booking_id,
        )
        self.expire_hold(other.booking_id)
        self.assertEqual(
            tuple(self.confirm(other.booking_id, "cs_ok", "pi_ok")), ("confirmed", 0)
        )

    def test_cancel_refund_follows_the_24_hour_rule(self) -> None:
        def paid(user: UUID, hours: int, session: str) -> UUID:
            slot = self.add_slot(self.coach, hours=hours)
            booking = self.book(user, slot).booking_id
            self.as_(
                user,
                "SELECT private.attach_booking_checkout(:id, :s)",
                id=booking,
                s=session,
            )
            self.assertEqual(tuple(self.confirm(booking, session)), ("confirmed", 0))
            return UUID(str(booking))

        def cancel(user: UUID, booking: UUID) -> int:
            return int(
                self.as_(
                    user,
                    "SELECT refund_cents FROM private.cancel_coach_booking(:id)",
                    id=booking,
                )[0].refund_cents
            )

        self.assertEqual(cancel(self.adult, paid(self.adult, 48, "cs_48")), 6000)
        self.assertEqual(cancel(self.adult, paid(self.adult, 12, "cs_12")), 0)
        self.assertEqual(cancel(self.coach_user, paid(self.adult, 12, "cs_c12")), 6000)

        # Cancelled before the payment arrived: the same rule at the cancel time.
        for hours, session, expected in (
            (48, "cs_u48", ("refund", 6000)),
            (12, "cs_u12", ("ignored", 0)),
        ):
            with self.subTest(hours=hours):
                slot = self.add_slot(self.coach, hours=hours)
                booking = self.book(self.adult, slot).booking_id
                self.as_(
                    self.adult,
                    "SELECT private.attach_booking_checkout(:id, :s)",
                    id=booking,
                    s=session,
                )
                self.assertEqual(cancel(self.adult, booking), 0)
                self.assertEqual(
                    tuple(self.confirm(booking, session, f"pi_{session}")), expected
                )
                row = self.admin_sql(
                    "SELECT refund_cents, stripe_payment_intent_id"
                    " FROM app.coach_booking WHERE id = :id",
                    id=booking,
                )[0]
                self.assertEqual(
                    (row.refund_cents, row.stripe_payment_intent_id),
                    (expected[1], f"pi_{session}"),
                )
                # Replayed: already settled.
                self.assertEqual(
                    tuple(self.confirm(booking, session, f"pi_{session}")),
                    ("ignored", 0),
                )

    def test_webhook_functions_refuse_signed_in_callers(self) -> None:
        booking = self.checkout(self.adult, "cs_hook")
        account = self.admin_sql(
            "SELECT stripe_account_id FROM app.coach_profile WHERE id = :id",
            id=self.coach,
        )[0].stripe_account_id
        for user in (self.adult, self.coach_user, self.admin_user):
            for sql, params in (
                (
                    "SELECT * FROM private.confirm_booking_payment("
                    ":b, 'cs_hook', 'pi_x')",
                    {"b": booking.booking_id},
                ),
                (
                    "SELECT private.expire_booking_checkout(:b, 'cs_hook')",
                    {"b": booking.booking_id},
                ),
                (
                    "SELECT private.set_coach_charges_enabled(:p, :a, false)",
                    {"p": self.coach, "a": account},
                ),
            ):
                with self.subTest(user=user, sql=sql):
                    self.assertEqual(self.refused(user, sql, **params), "42501")
        # Mismatched ids change nothing.
        self.as_(
            None,
            "SELECT private.expire_booking_checkout(:b, 'cs_other')",
            b=booking.booking_id,
        )
        self.as_(
            None,
            "SELECT private.set_coach_charges_enabled(:p, :a, false)",
            p=self.coach_b,
            a=account,
        )
        state = self.admin_sql(
            "SELECT b.status, cp.charges_enabled FROM app.coach_booking b"
            " JOIN app.coach_profile cp ON cp.id = b.coach_profile_id WHERE b.id = :id",
            id=booking.booking_id,
        )[0]
        self.assertEqual(
            (state.status, state.charges_enabled), ("pending_payment", True)
        )
        others = self.admin_sql(
            "SELECT charges_enabled FROM app.coach_profile WHERE id = :id",
            id=self.coach_b,
        )[0]
        self.assertTrue(others.charges_enabled)
        # The matching pair acts.
        self.as_(
            None,
            "SELECT private.expire_booking_checkout(:b, 'cs_hook')",
            b=booking.booking_id,
        )
        self.as_(
            None,
            "SELECT private.set_coach_charges_enabled(:p, :a, false)",
            p=self.coach,
            a=account,
        )
        state = self.admin_sql(
            "SELECT b.status, cp.charges_enabled FROM app.coach_booking b"
            " JOIN app.coach_profile cp ON cp.id = b.coach_profile_id WHERE b.id = :id",
            id=booking.booking_id,
        )[0]
        self.assertEqual((state.status, state.charges_enabled), ("expired", False))

    def test_audit_helper_and_stripe_account_are_definer_only(self) -> None:
        self.assertEqual(
            self.refused(
                self.admin_user,
                "SELECT private.write_marketplace_audit('forged', NULL, NULL, NULL)",
            ),
            "42501",
        )
        fresh = self.profile(self.create_auth_user("mk.acct@example.test"), "verified")
        owner = self.admin_sql(
            "SELECT user_id FROM app.coach_profile WHERE id = :id", id=fresh
        )[0].user_id
        self.admin_sql(
            "UPDATE app.coach_profile SET stripe_account_id = NULL WHERE id = :id",
            id=fresh,
        )
        self.assertEqual(
            self.refused(
                owner, "UPDATE app.coach_profile SET stripe_account_id = 'acct_evil'"
            ),
            "42501",
        )
        self.assertEqual(
            self.refused(
                owner, "SELECT private.set_coach_stripe_account('not an account')"
            ),
            "22023",
        )
        self.assertEqual(
            self.as_(owner, "SELECT private.set_coach_stripe_account('acct_1A')")[0][0],
            "acct_1A",
        )
        # Set once: a second id is ignored and the stored one comes back.
        self.assertEqual(
            self.as_(owner, "SELECT private.set_coach_stripe_account('acct_2B')")[0][0],
            "acct_1A",
        )
        # A draft profile gets no account.
        draft = self.profile(self.create_auth_user("mk.acct2@example.test"), "draft")
        draft_owner = self.admin_sql(
            "SELECT user_id FROM app.coach_profile WHERE id = :id", id=draft
        )[0].user_id
        self.assertEqual(
            self.refused(
                draft_owner, "SELECT private.set_coach_stripe_account('acct_3C')"
            ),
            "P0002",
        )

    def test_rereview_covers_every_public_field(self) -> None:
        for column, value in (
            ("display_name", "'Renamed Coach'"),
            ("city", "'York'"),
            ("formats", "ARRAY['online','in_person']"),
            ("bio", "'New bio'"),
        ):
            with self.subTest(column=column):
                self.admin_sql(
                    "UPDATE app.coach_profile SET status = 'verified' WHERE id = :id",
                    id=self.coach,
                )
                self.as_(
                    self.coach_user,
                    f"UPDATE app.coach_profile SET {column} = {value} RETURNING id",
                )
                status = self.admin_sql(
                    "SELECT status FROM app.coach_profile WHERE id = :id", id=self.coach
                )[0].status
                self.assertEqual(status, "pending_review")

    def test_reports_are_one_open_per_coach_and_five_a_day(self) -> None:
        insert = (
            "INSERT INTO app.marketplace_report (reporter_user_id, coach_profile_id,"
            " reason) VALUES (private.current_user_id(), :coach, 'Something is wrong')"
            " RETURNING id"
        )
        first = self.as_(self.adult, insert, coach=self.coach)[0].id
        self.assertEqual(self.refused(self.adult, insert, coach=self.coach), "23505")
        # No booking with the coach: still listed.
        self.assertIn(self.coach, self.listed(self.adult_b))
        self.admin_sql(
            "UPDATE app.marketplace_report SET status = 'resolved' WHERE id = :id",
            id=first,
        )
        self.as_(self.adult, insert, coach=self.coach)
        coaches = [self.coach_b] + [
            self.profile(self.create_auth_user(f"mk.r{i}@example.test"), "verified")
            for i in range(2)
        ]
        for coach in coaches:
            self.as_(self.adult, insert, coach=coach)
        spare = self.profile(self.create_auth_user("mk.r9@example.test"), "verified")
        self.assertEqual(self.refused(self.adult, insert, coach=spare), "42501")
        self.as_(self.adult_b, insert, coach=spare)  # another reporter is unaffected

    def owned_draft(self, email: str) -> tuple[UUID, UUID]:
        profile = self.profile(self.create_auth_user(email), "draft")
        owner = self.admin_sql(
            "SELECT user_id FROM app.coach_profile WHERE id = :id", id=profile
        )[0].user_id
        return profile, UUID(str(owner))

    def test_documents_are_capped_and_change_only_before_review(self) -> None:
        profile, owner = self.owned_draft("mk.docs@example.test")
        insert = (
            "INSERT INTO app.coach_document (coach_profile_id, kind, object_key,"
            " content_type, size_bytes) VALUES (CAST(:p AS uuid), 'certification',"
            " :key, 'application/pdf', 10) RETURNING id"
        )
        for index in range(10):
            self.as_(
                owner, insert, p=str(profile), key=f"coach-docs/{profile}/{index}.pdf"
            )
        self.assertEqual(
            self.refused(
                owner, insert, p=str(profile), key=f"coach-docs/{profile}/x.pdf"
            ),
            "54000",
        )
        self.admin_sql(
            "DELETE FROM app.coach_document WHERE coach_profile_id = :p", p=profile
        )
        ready = self.add_document(profile)
        uploading = self.add_document(profile, status="uploading", kind="id")

        def changed(sql: str, document: UUID) -> int:
            with self.runtime.connect() as connection, connection.begin():
                self.as_user(connection, owner)
                return connection.execute(text(sql), {"id": document}).rowcount

        # A ready document is final; an unfinished one may complete.
        update = "UPDATE app.coach_document SET uploaded_at = now() WHERE id = :id"
        self.assertEqual(changed(update, ready), 0)
        self.assertEqual(changed(update, uploading), 1)
        for status in ("pending_review", "verified", "suspended"):
            with self.subTest(status=status):
                self.admin_sql(
                    "UPDATE app.coach_profile SET status = :s WHERE id = :id",
                    s=status,
                    id=profile,
                )
                self.assertEqual(changed(update, uploading), 0)
                self.assertEqual(
                    changed("DELETE FROM app.coach_document WHERE id = :id", ready), 0
                )
                self.assertEqual(
                    self.refused(
                        owner,
                        insert,
                        p=str(profile),
                        key=f"coach-docs/{profile}/{status}.pdf",
                    ),
                    "42501",
                )
        self.admin_sql(
            "UPDATE app.coach_profile SET status = 'rejected' WHERE id = :id",
            id=profile,
        )
        self.assertEqual(
            changed("DELETE FROM app.coach_document WHERE id = :id", ready), 1
        )

    def test_deleted_documents_queue_their_objects_for_the_sweep(self) -> None:
        profile, owner = self.owned_draft("mk.purge@example.test")
        first = self.add_document(profile)
        second = self.add_document(profile, kind="id")
        with self.runtime.connect() as connection, connection.begin():
            self.as_user(connection, owner)
            connection.execute(
                text("DELETE FROM app.coach_document WHERE id = :id"), {"id": first}
            )
        # The profile goes (as with an account deletion): documents cascade.
        self.admin_sql("DELETE FROM app.coach_profile WHERE id = :id", id=profile)
        queued = {
            row.object_key
            for row in self.admin_sql("SELECT object_key FROM app.coach_document_purge")
        }
        self.assertLessEqual(
            {f"coach-docs/{profile}/{doc}.pdf" for doc in (first, second)}, queued
        )
        # The runtime role cannot read or write the queue.
        self.assertEqual(
            self.refused(self.admin_user, "SELECT 1 FROM app.coach_document_purge"),
            "42501",
        )

    @unittest.skipUnless(WORKER_URL, "WORKER_DATABASE_URL is not configured")
    def test_retention_sweep_purges_expired_documents(self) -> None:
        stale_upload = self.add_document(self.coach, status="uploading", kind="id")
        fresh_upload = self.add_document(
            self.coach, status="uploading", kind="certification"
        )
        self.admin_sql(
            "UPDATE app.coach_document SET created_at = now() - interval '25 hours'"
            " WHERE id = :id",
            id=stale_upload,
        )
        rejected, _owner = self.owned_draft("mk.rej@example.test")
        rejected_doc = self.add_document(rejected)
        recent, _other = self.owned_draft("mk.rej2@example.test")
        recent_doc = self.add_document(recent)
        for profile, age in ((rejected, "91 days"), (recent, "10 days")):
            self.admin_sql(
                "UPDATE app.coach_profile SET status = 'rejected' WHERE id = :id",
                id=profile,
            )
            self.admin_sql(
                "UPDATE app.marketplace_audit"
                " SET created_at = now() - CAST(:age AS interval)"
                " WHERE subject_id = :id AND action = 'coach_profile.rejected'",
                age=age,
                id=profile,
            )
        worker = f"coach-docs-{uuid4()}"
        job_id = self.admin_sql(
            """
            INSERT INTO app.processing_job (
                kind, idempotency_key, status, attempts, max_attempts,
                locked_at, locked_by, heartbeat_at
            ) VALUES (
                'retention_sweep', :key, 'running', 1, 5, now(), :worker, now()
            ) RETURNING id
            """,
            key=f"coach-docs:{uuid4()}",
            worker=worker,
        )[0].id
        job = jobs.Job(
            id=UUID(str(job_id)),
            kind="retention_sweep",
            video_id=None,
            email_delivery_id=None,
            player_id=None,
            deletion_manifest_id=None,
            attempts=1,
            max_attempts=5,
            payload={},
            locked_by=worker,
        )
        stale = dataclasses.replace(job, locked_by="not-the-holder")
        with mock.patch.object(retention.storage, "delete_object") as deleted:
            self.assertEqual(retention.purge_coach_documents(stale, lambda _p: True), 0)
            deleted.assert_not_called()
            with mock.patch.object(retention.storage, "head_object", return_value=None):
                retention.purge_coach_documents(job, lambda _p: True)
        removed = {call.args[0] for call in deleted.call_args_list}
        self.assertLessEqual(
            {
                f"coach-docs/{self.coach}/{stale_upload}.pdf",
                f"coach-docs/{rejected}/{rejected_doc}.pdf",
            },
            removed,
        )
        remaining = {
            UUID(str(row.id))
            for row in self.admin_sql(
                "SELECT id FROM app.coach_document WHERE id = ANY(:ids)",
                ids=[stale_upload, fresh_upload, rejected_doc, recent_doc],
            )
        }
        self.assertEqual(remaining, {fresh_upload, recent_doc})
        self.assertEqual(
            self.admin_sql(
                "SELECT count(*) AS n FROM app.coach_document_purge"
                " WHERE object_key = ANY(:k)",
                k=list(removed),
            )[0].n,
            0,
        )

    def test_price_and_fee_match_the_rate(self) -> None:
        booking = self.book(self.adult)
        # 4000 cents an hour for 90 minutes.
        self.assertEqual((booking.price_cents, booking.platform_fee_cents), (6000, 600))
        self.assertEqual(payments.platform_fee(booking.price_cents), 600)
