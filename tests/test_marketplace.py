"""Block 10M coach marketplace (adults only, Stripe test mode).

The unit tests mock `services.api.payments` (or the Stripe SDK beneath it) and
need no database. The database tests run through `shoulder_api` under RLS and
the definer functions of migration 0020.
"""

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
from services.api.schemas import CoachProfileUpdate, CoachSlotCreate

sys.path.append(str(Path(__file__).resolve().parent))

from test_database import CONFIGURED, DatabaseTestCase, sqlstate  # noqa: E402

ON = {"MARKETPLACE_ENABLED": "on"}
WEBHOOK_SECRET = "whsec_test_secret"
GATED_PATHS = (
    ("get", "/v1/me/age-attestation"),
    ("put", "/v1/me/age-attestation"),
    ("get", "/v1/coach-profile"),
    ("post", "/v1/coach-profile/submit"),
    ("get", "/v1/admin/coach-reviews"),
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

    def test_refund_windows(self) -> None:
        now = datetime(2026, 9, 24, 12, tzinfo=UTC)
        refund = marketplace_service.refund_for
        self.assertEqual(refund(5000, now + timedelta(hours=25), now, "player"), 5000)
        self.assertEqual(
            refund(5000, now + timedelta(hours=24, seconds=1), now, "player"), 5000
        )
        self.assertEqual(refund(5000, now + timedelta(hours=24), now, "player"), 0)
        self.assertEqual(refund(5000, now + timedelta(hours=2), now, "player"), 0)
        self.assertEqual(refund(5000, now + timedelta(minutes=5), now, "coach"), 5000)


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
        event = {
            "id": "evt_2",
            "type": "account.updated",
            "data": {"object": {"id": "acct_1", "charges_enabled": True}},
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
        self.assertEqual(params, {"account": "acct_1", "enabled": True})

    def test_oversized_webhook_is_refused_before_verification(self) -> None:
        with mock.patch.dict(os.environ, ON):
            response = self.client.post(
                "/v1/stripe/webhook", content=b"x" * (300 * 1024)
            )
        self.assertEqual(response.status_code, 413)

    def test_completed_checkout_refunds_when_nothing_is_confirmed(self) -> None:
        connection = mock.Mock()
        event: dict[str, Any] = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_1",
                    "payment_status": "paid",
                    "payment_intent": "pi_1",
                }
            },
        }
        with mock.patch.object(payments, "refund") as refund:
            for outcome, refunds in (("confirmed", 0), ("ignored", 0), ("refund", 1)):
                refund.reset_mock()
                connection.execute.return_value.scalar_one.return_value = outcome
                marketplace_service.apply_event(connection, event)
                self.assertEqual(refund.call_count, refunds, outcome)
            refund.assert_called_with("pi_1")
            connection.reset_mock()
            event["data"]["object"]["payment_status"] = "unpaid"
            marketplace_service.apply_event(connection, event)
            connection.execute.assert_not_called()


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
        self.admin_sql(
            "INSERT INTO app.marketplace_report (reporter_user_id, coach_profile_id,"
            " reason) VALUES (:user, :coach, 'Asked to meet at his house')",
            user=self.adult_b,
            coach=self.coach_b,
        )
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
        self.admin_sql(
            "INSERT INTO app.coach_document (coach_profile_id, kind, object_key,"
            " content_type, size_bytes, status) VALUES (:p, 'background_check',"
            " 'coach-docs/' || :p || '/x.pdf', 'application/pdf', 10, 'ready')",
            p=str(self.coach),
        )
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
                "SELECT * FROM private.cancel_coach_booking(:id, 0)",
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
        self.admin_sql(
            "INSERT INTO app.coach_document (coach_profile_id, kind, object_key,"
            " content_type, size_bytes, status) VALUES (:p, 'background_check',"
            " 'coach-docs/' || :p || '/b.pdf', 'application/pdf', 10, 'ready')",
            p=str(pending),
        )
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
        booking = self.book(self.adult)
        self.as_(
            self.adult,
            "SELECT private.attach_booking_checkout(:id, 'cs_test_1')",
            id=booking.booking_id,
        )
        confirm = "SELECT private.confirm_booking_payment(:s, 'pi_1')"
        for _ in range(2):
            self.assertEqual(self.as_(None, confirm, s="cs_test_1")[0][0], "confirmed")
        self.assertEqual(self.as_(None, confirm, s="cs_unknown")[0][0], "refund")
        slot = self.admin_sql(
            "SELECT status FROM app.coach_slot WHERE id = :id", id=self.slot
        )
        self.assertEqual(slot[0].status, "booked")
        # Player cancels inside 24 h of a 48 h slot? No: 48 h out, full refund
        # is the API's call; the function clamps whatever it is given.
        cancelled = self.as_(
            self.adult,
            "SELECT * FROM private.cancel_coach_booking(:id, 999999)",
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
        self.assertEqual(self.as_(None, confirm, s="cs_test_1")[0][0], "ignored")

    def test_price_and_fee_match_the_rate(self) -> None:
        booking = self.book(self.adult)
        # 4000 cents an hour for 90 minutes.
        self.assertEqual((booking.price_cents, booking.platform_fee_cents), (6000, 600))
        self.assertEqual(payments.platform_fee(booking.price_cents), 600)
