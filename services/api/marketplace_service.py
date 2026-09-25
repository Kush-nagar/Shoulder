"""Coach marketplace data access and flow (Block 10M; adults only, test mode).

Every query runs as the verified user under row-level security. State
transitions that matter (submit, verify, book, confirm, cancel, expire) are
definer functions in migration 0020 that authorize the caller themselves and
lock slot before booking. Stripe is reached only through `payments`, and a
Stripe call made inside an open transaction rolls that transaction back when it
fails, so the database never records a payment step that did not happen.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection, CursorResult, text
from sqlalchemy.exc import DBAPIError

from services.api import payments, storage
from services.api.problems import Problem
from services.api.routes import sqlstate
from services.api.schemas import (
    AdminDocument,
    AgeAttestation,
    BookingCheckout,
    BookingCreate,
    CoachBooking,
    CoachDecision,
    CoachDocument,
    CoachDocumentCreate,
    CoachDocumentUpload,
    CoachProfile,
    CoachProfileStatus,
    CoachProfileUpdate,
    CoachReview,
    CoachReviewSummary,
    CoachSlot,
    CoachSlotCreate,
    MarketplaceCoach,
    MarketplaceCoachDetail,
    MarketplaceReport,
    MarketplaceReportCreate,
    PlayerBooking,
    PublicSlot,
    ReportStatus,
)

FULL_REFUND_NOTICE = timedelta(hours=24)
DECISIONS: dict[CoachDecision, str] = {
    "approve": "verified",
    "reject": "rejected",
    "suspend": "suspended",
    "reinstate": "verified",
}
PROFILE_COLUMNS = """
    id, user_id, display_name, bio, specialties, city, formats, rate_cents,
    status, review_note, verified_at, stripe_account_id, charges_enabled,
    created_at, updated_at
"""
DOCUMENT_COLUMNS = "id, kind, content_type, size_bytes, status, uploaded_at, object_key"
SLOT_COLUMNS = "id, starts_at, ends_at, format, venue, status"
# Admins read every profile, so the name resolves for them; a reporting player
# cannot read coach_profile rows and gets null.
REPORT_COLUMNS = (
    "id, coach_profile_id, booking_id, reason, status, created_at,"
    " (SELECT c.display_name FROM app.coach_profile c"
    " WHERE c.id = marketplace_report.coach_profile_id) AS coach_display_name"
)

ADULTS_ONLY = Problem(
    403,
    "The coach marketplace is an 18+ pilot. Confirm your birth year first.",
    "adult-attestation-required",
)
NO_PROFILE = Problem(404, "You have no coach profile yet.")


def enabled() -> bool:
    return os.environ.get("MARKETPLACE_ENABLED", "").strip().lower() == "on"


def refund_for(
    price_cents: int,
    starts_at: datetime,
    now: datetime,
    by: Literal["player", "coach"],
) -> int:
    """Coach cancels: full. Player cancels more than 24 h ahead: full; else none."""
    if by == "coach" or starts_at - now > FULL_REFUND_NOTICE:
        return price_cents
    return 0


def _execute(
    connection: Connection,
    sql: str,
    params: dict[str, Any] | None = None,
    refusals: dict[str, Problem] | None = None,
) -> CursorResult[Any]:
    """Run one statement, turning a deliberate SQLSTATE into its problem."""
    try:
        return connection.execute(text(sql), params or {})
    except DBAPIError as error:
        problem = (refusals or {}).get(sqlstate(error) or "")
        if problem is not None:
            raise problem from None
        raise


def expire_holds(connection: Connection) -> None:
    """Lazy half of hold expiry; the retention sweep is the other half."""
    connection.execute(text("SELECT private.expire_marketplace_holds()"))


def require_adult(connection: Connection) -> None:
    if not connection.execute(text("SELECT private.is_adult()")).scalar_one():
        raise ADULTS_ONLY


def require_admin(connection: Connection) -> None:
    if not connection.execute(text("SELECT private.is_platform_admin()")).scalar_one():
        raise Problem(404, "Not found.")


# -- age attestation ----


def read_attestation(connection: Connection) -> AgeAttestation:
    row = connection.execute(
        text("""
            SELECT birth_year, private.is_adult() AS adult FROM app.age_attestation
            WHERE user_id = private.current_user_id()
        """)
    ).one_or_none()
    if row is None:
        raise Problem(404, "No birth year has been confirmed.")
    return AgeAttestation(birth_year=row.birth_year, adult=row.adult)


def attest(connection: Connection, birth_year: int) -> AgeAttestation:
    if birth_year > datetime.now().year:
        raise Problem(422, "One or more fields are invalid.")
    _execute(
        connection,
        "SELECT private.attest_age(:year)",
        {"year": birth_year},
        {"55000": Problem(409, "A confirmed birth year cannot be made earlier.")},
    )
    return read_attestation(connection)


# -- coach profile ----


def own_profile(connection: Connection) -> Any:
    return connection.execute(
        text(
            f"SELECT {PROFILE_COLUMNS} FROM app.coach_profile"
            " WHERE user_id = private.current_user_id()"
        )
    ).one_or_none()


def require_profile(connection: Connection) -> Any:
    profile = own_profile(connection)
    if profile is None:
        raise NO_PROFILE
    return profile


def document_model(row: Any) -> CoachDocument:
    return CoachDocument(
        id=row.id,
        kind=row.kind,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        status=row.status,
        uploaded_at=row.uploaded_at,
    )


def documents(connection: Connection, profile_id: UUID) -> list[Any]:
    return list(
        connection.execute(
            text(
                f"SELECT {DOCUMENT_COLUMNS} FROM app.coach_document"
                " WHERE coach_profile_id = :id ORDER BY created_at, id"
            ),
            {"id": str(profile_id)},
        ).all()
    )


def profile_model(connection: Connection, row: Any) -> CoachProfile:
    return CoachProfile(
        id=row.id,
        display_name=row.display_name,
        bio=row.bio,
        specialties=row.specialties,
        city=row.city,
        formats=row.formats,
        rate_cents=row.rate_cents,
        status=row.status,
        review_note=row.review_note,
        verified_at=row.verified_at,
        stripe_connected=row.stripe_account_id is not None,
        charges_enabled=row.charges_enabled,
        documents=[document_model(doc) for doc in documents(connection, row.id)],
    )


def read_profile(connection: Connection) -> CoachProfile:
    return profile_model(connection, require_profile(connection))


def save_profile(connection: Connection, body: CoachProfileUpdate) -> CoachProfile:
    """Create or edit. A verified coach who changes rate, specialties or bio
    returns to review (enforced by a trigger, not here)."""
    values = body.model_dump()
    if own_profile(connection) is None:
        require_adult(connection)
        connection.execute(
            text("""
                INSERT INTO app.coach_profile (
                    user_id, display_name, bio, specialties, city, formats, rate_cents
                ) VALUES (
                    private.current_user_id(), :display_name, :bio, :specialties,
                    :city, :formats, :rate_cents
                )
            """),
            values,
        )
    else:
        connection.execute(
            text("""
                UPDATE app.coach_profile SET
                    display_name = :display_name, bio = :bio,
                    specialties = :specialties, city = :city, formats = :formats,
                    rate_cents = :rate_cents
                WHERE user_id = private.current_user_id()
            """),
            values,
        )
    return read_profile(connection)


def create_document(
    connection: Connection, body: CoachDocumentCreate
) -> CoachDocumentUpload:
    profile = require_profile(connection)
    document_id = UUID(
        str(connection.execute(text("SELECT gen_random_uuid()")).scalar_one())
    )
    key = storage.coach_doc_key(profile.id, document_id, body.content_type)
    connection.execute(
        text("""
            INSERT INTO app.coach_document (
                id, coach_profile_id, kind, object_key, content_type, size_bytes
            ) VALUES (:id, :profile, :kind, :key, :content_type, :size)
        """),
        {
            "id": str(document_id),
            "profile": str(profile.id),
            "kind": body.kind,
            "key": key,
            "content_type": body.content_type,
            "size": body.size_bytes,
        },
    )
    return CoachDocumentUpload(
        id=document_id,
        upload_url=storage.sign_put(key, body.content_type, body.size_bytes),
        content_type=body.content_type,
        expires_in_seconds=storage.PART_URL_SECONDS,
    )


def complete_document(
    connection: Connection, document_id: UUID
) -> CoachDocument | None:
    """HEAD-verify what arrived. A mismatch keeps nothing and returns None."""
    profile = require_profile(connection)
    row = connection.execute(
        text(
            f"SELECT {DOCUMENT_COLUMNS} FROM app.coach_document"
            " WHERE id = :id AND coach_profile_id = :profile FOR UPDATE"
        ),
        {"id": str(document_id), "profile": str(profile.id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That document is not available.")
    if row.status == "ready":
        return document_model(row)
    stored = storage.head_media(row.object_key)
    if stored is None:
        raise Problem(409, "The upload has not arrived yet.", "upload-incomplete")
    if stored != (row.size_bytes, row.content_type):
        storage.delete_object(row.object_key)
        connection.execute(
            text("DELETE FROM app.coach_document WHERE id = :id"), {"id": str(row.id)}
        )
        return None
    ready = connection.execute(
        text(
            "UPDATE app.coach_document SET status = 'ready', uploaded_at = now()"
            f" WHERE id = :id RETURNING {DOCUMENT_COLUMNS}"
        ),
        {"id": str(row.id)},
    ).one()
    return document_model(ready)


def submit_profile(connection: Connection) -> CoachProfile:
    profile = require_profile(connection)
    _execute(
        connection,
        "SELECT private.set_coach_profile_status(:id, 'pending_review', NULL)",
        {"id": str(profile.id)},
        {
            "23514": Problem(409, "Upload a background check before submitting."),
            "55000": Problem(409, "This profile is not a draft."),
        },
    )
    return read_profile(connection)


def stripe_onboarding(connection: Connection) -> str:
    profile = require_profile(connection)
    if profile.status != "verified":
        raise Problem(409, "Payments open once your profile is verified.")
    account = profile.stripe_account_id
    if account is None:
        account = payments.create_express_account(profile.id)
        connection.execute(
            text(
                "UPDATE app.coach_profile SET stripe_account_id = :account"
                " WHERE id = :id AND stripe_account_id IS NULL"
            ),
            {"account": account, "id": str(profile.id)},
        )
    return payments.account_link(account)


# -- slots ----


def slot_model(row: Any) -> CoachSlot:
    return CoachSlot.model_validate(row._mapping)


def list_slots(connection: Connection) -> list[CoachSlot]:
    profile = require_profile(connection)
    expire_holds(connection)
    rows = connection.execute(
        text(
            f"SELECT {SLOT_COLUMNS} FROM app.coach_slot WHERE coach_profile_id = :id"
            " AND starts_at > now() ORDER BY starts_at, id"
        ),
        {"id": str(profile.id)},
    ).all()
    return [slot_model(row) for row in rows]


def create_slot(connection: Connection, body: CoachSlotCreate) -> CoachSlot:
    profile = require_profile(connection)
    if profile.status != "verified" or not profile.charges_enabled:
        raise Problem(409, "Slots open once you are verified and Stripe is ready.")
    if body.format not in profile.formats:
        raise Problem(422, "That format is not on your profile.")
    if body.starts_at <= datetime.now(body.starts_at.tzinfo):
        raise Problem(422, "A slot must start in the future.")
    row = connection.execute(
        text(f"""
            INSERT INTO app.coach_slot (
                coach_profile_id, starts_at, ends_at, format, venue
            ) VALUES (:profile, :starts_at, :ends_at, :format, :venue)
            RETURNING {SLOT_COLUMNS}
        """),
        {"profile": str(profile.id), **body.model_dump()},
    ).one()
    return slot_model(row)


def cancel_booking(
    connection: Connection, booking_id: UUID, refund_cents: int
) -> tuple[str, int]:
    """Definer cancel, then the Stripe refund inside the same transaction."""
    row = _execute(
        connection,
        "SELECT status, refund_cents, stripe_payment_intent_id"
        " FROM private.cancel_coach_booking(:id, :refund)",
        {"id": str(booking_id), "refund": refund_cents},
        {
            "P0002": Problem(404, "That booking is not available."),
            "55000": Problem(409, "That booking can no longer be cancelled."),
        },
    ).one()
    if row.refund_cents > 0 and row.stripe_payment_intent_id:
        payments.refund(row.stripe_payment_intent_id, row.refund_cents)
    return str(row.status), int(row.refund_cents)


def delete_slot(connection: Connection, slot_id: UUID) -> None:
    """Open: withdrawn. Held or booked: the booking is cancelled, full refund."""
    profile = require_profile(connection)
    expire_holds(connection)
    slot = connection.execute(
        text(
            "SELECT id, status FROM app.coach_slot"
            " WHERE id = :id AND coach_profile_id = :profile"
        ),
        {"id": str(slot_id), "profile": str(profile.id)},
    ).one_or_none()
    if slot is None:
        raise Problem(404, "That slot is not available.")
    if slot.status == "open":
        connection.execute(
            text(
                "UPDATE app.coach_slot SET status = 'cancelled'"
                " WHERE id = :id AND status = 'open'"
            ),
            {"id": str(slot_id)},
        )
    elif slot.status in ("held", "booked"):
        booking = connection.execute(
            text("SELECT id, price_cents FROM app.coach_booking WHERE slot_id = :id"),
            {"id": str(slot_id)},
        ).one()
        cancel_booking(connection, booking.id, booking.price_cents)


def coach_bookings(connection: Connection) -> list[CoachBooking]:
    require_profile(connection)
    expire_holds(connection)
    rows = connection.execute(text("SELECT * FROM private.coach_booking_list()")).all()
    return [CoachBooking.model_validate(row._mapping) for row in rows]


# -- admin ----


def review_queue(
    connection: Connection, status: CoachProfileStatus
) -> list[CoachReviewSummary]:
    require_admin(connection)
    rows = connection.execute(
        text("""
            SELECT id, display_name, city, status, created_at, updated_at
            FROM app.coach_profile WHERE status = :status ORDER BY updated_at, id
        """),
        {"status": status},
    ).all()
    return [CoachReviewSummary.model_validate(row._mapping) for row in rows]


def review_detail(connection: Connection, profile_id: UUID) -> CoachReview:
    """Profile plus 60-second signed URLs; every signed document is audited."""
    require_admin(connection)
    row = connection.execute(
        text(f"SELECT {PROFILE_COLUMNS} FROM app.coach_profile WHERE id = :id"),
        {"id": str(profile_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That coach profile is not available.")
    reports = connection.execute(
        text(
            "SELECT count(*) FROM app.marketplace_report"
            " WHERE coach_profile_id = :id AND status = 'open'"
        ),
        {"id": str(profile_id)},
    ).scalar_one()
    signed: list[AdminDocument] = []
    for doc in documents(connection, profile_id):
        url = None
        if doc.status == "ready":
            url = storage.sign_get(doc.object_key, storage.COACH_DOC_GET_URL_SECONDS)
            connection.execute(
                text(
                    "SELECT private.write_marketplace_audit("
                    "'coach_document.viewed', 'coach_document', :id, NULL)"
                ),
                {"id": str(doc.id)},
            )
        signed.append(
            AdminDocument(
                **document_model(doc).model_dump(),
                url=url,
                url_expires_in_seconds=(
                    storage.COACH_DOC_GET_URL_SECONDS if url else None
                ),
            )
        )
    return CoachReview(
        id=row.id,
        display_name=row.display_name,
        bio=row.bio,
        specialties=row.specialties,
        city=row.city,
        formats=row.formats,
        rate_cents=row.rate_cents,
        status=row.status,
        review_note=row.review_note,
        verified_at=row.verified_at,
        charges_enabled=row.charges_enabled,
        open_reports=reports,
        documents=signed,
    )


def decide(
    connection: Connection,
    profile_id: UUID,
    decision: CoachDecision,
    note: str | None,
) -> CoachReviewSummary:
    require_admin(connection)
    _execute(
        connection,
        "SELECT private.set_coach_profile_status(:id, :status, :note)",
        {"id": str(profile_id), "status": DECISIONS[decision], "note": note},
        {
            "P0002": Problem(404, "That coach profile is not available."),
            "55000": Problem(409, "That decision does not apply to this profile."),
        },
    )
    row = connection.execute(
        text("""
            SELECT id, display_name, city, status, created_at, updated_at
            FROM app.coach_profile WHERE id = :id
        """),
        {"id": str(profile_id)},
    ).one()
    return CoachReviewSummary.model_validate(row._mapping)


def admin_reports(
    connection: Connection, status: ReportStatus
) -> list[MarketplaceReport]:
    require_admin(connection)
    rows = connection.execute(
        text(
            f"SELECT {REPORT_COLUMNS} FROM app.marketplace_report"
            " WHERE status = :status ORDER BY created_at, id"
        ),
        {"status": status},
    ).all()
    return [MarketplaceReport.model_validate(row._mapping) for row in rows]


def resolve_report(connection: Connection, report_id: UUID) -> MarketplaceReport:
    require_admin(connection)
    connection.execute(
        text(
            "UPDATE app.marketplace_report SET status = 'resolved'"
            " WHERE id = :id AND status = 'open'"
        ),
        {"id": str(report_id)},
    )
    row = connection.execute(
        text(f"SELECT {REPORT_COLUMNS} FROM app.marketplace_report WHERE id = :id"),
        {"id": str(report_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That report is not available.")
    return MarketplaceReport.model_validate(row._mapping)


# -- adults: browse, book, cancel, report ----


def browse(
    connection: Connection, specialty: str | None, city: str | None
) -> list[MarketplaceCoach]:
    require_adult(connection)
    rows = connection.execute(
        text(
            "SELECT id, display_name, bio, specialties, city, formats, rate_cents"
            " FROM private.marketplace_coaches(:specialty, :city)"
        ),
        {"specialty": specialty, "city": city},
    ).all()
    return [MarketplaceCoach.model_validate(row._mapping) for row in rows]


def coach_detail(connection: Connection, profile_id: UUID) -> MarketplaceCoachDetail:
    require_adult(connection)
    expire_holds(connection)
    row = connection.execute(
        text(
            "SELECT id, display_name, bio, specialties, city, formats, rate_cents"
            " FROM private.marketplace_coaches(NULL, NULL) WHERE id = :id"
        ),
        {"id": str(profile_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That coach is not available.")
    slots = connection.execute(
        text("SELECT * FROM private.marketplace_coach_slots(:id)"),
        {"id": str(profile_id)},
    ).all()
    return MarketplaceCoachDetail(
        **MarketplaceCoach.model_validate(row._mapping).model_dump(),
        slots=[PublicSlot.model_validate(slot._mapping) for slot in slots],
    )


def book(connection: Connection, body: BookingCreate) -> BookingCheckout:
    """Hold the slot, open Stripe Checkout, remember the session: all or none."""
    require_adult(connection)
    hold = _execute(
        connection,
        "SELECT * FROM private.book_coach_slot(:slot, :note)",
        {"slot": str(body.slot_id), "note": body.note},
        {
            "42501": Problem(403, "You cannot book this slot."),
            "P0002": Problem(404, "That slot is not available."),
            "23505": Problem(409, "Someone else has just booked that slot."),
        },
    ).one()
    session_id, url = payments.create_checkout_session(
        booking_id=hold.booking_id,
        price_cents=hold.price_cents,
        destination_account=hold.stripe_account_id,
        description=f"Coaching session with {hold.coach_display_name}",
    )
    connection.execute(
        text("SELECT private.attach_booking_checkout(:id, :session)"),
        {"id": str(hold.booking_id), "session": session_id},
    )
    return BookingCheckout(booking_id=hold.booking_id, checkout_url=url)


def player_bookings(connection: Connection) -> list[PlayerBooking]:
    require_adult(connection)
    expire_holds(connection)
    rows = connection.execute(text("SELECT * FROM private.player_booking_list()")).all()
    return [PlayerBooking.model_validate(row._mapping) for row in rows]


def player_cancel(connection: Connection, booking_id: UUID) -> PlayerBooking:
    expire_holds(connection)
    row = connection.execute(
        text(
            "SELECT id, price_cents, starts_at FROM private.player_booking_list()"
            " WHERE id = :id"
        ),
        {"id": str(booking_id)},
    ).one_or_none()
    if row is None:
        raise Problem(404, "That booking is not available.")
    now = connection.execute(text("SELECT now()")).scalar_one()
    cancel_booking(
        connection,
        booking_id,
        refund_for(row.price_cents, row.starts_at, now, "player"),
    )
    updated = connection.execute(
        text("SELECT * FROM private.player_booking_list() WHERE id = :id"),
        {"id": str(booking_id)},
    ).one()
    return PlayerBooking.model_validate(updated._mapping)


def report(connection: Connection, body: MarketplaceReportCreate) -> MarketplaceReport:
    require_adult(connection)
    row = _execute(
        connection,
        f"""
            INSERT INTO app.marketplace_report (
                reporter_user_id, coach_profile_id, booking_id, reason
            ) VALUES (private.current_user_id(), :coach, :booking, :reason)
            RETURNING {REPORT_COLUMNS}
        """,
        {
            "coach": str(body.coach_profile_id),
            "booking": str(body.booking_id) if body.booking_id else None,
            "reason": body.reason,
        },
        {
            "42501": Problem(422, "That booking is not one of yours with this coach."),
            "23503": Problem(404, "That coach is not available."),
        },
    ).one()
    return MarketplaceReport.model_validate(row._mapping)


# -- Stripe webhook ----


def apply_event(connection: Connection, event: dict[str, Any]) -> None:
    """Idempotent by state: replaying any event changes nothing twice, and a
    refund's idempotency key is its payment intent and amount."""
    kind = event.get("type")
    obj = event.get("data", {}).get("object", {})
    if kind == "checkout.session.completed":
        if obj.get("payment_status") != "paid" or not obj.get("payment_intent"):
            return
        outcome = connection.execute(
            text("SELECT private.confirm_booking_payment(:session, :intent)"),
            {"session": obj["id"], "intent": obj["payment_intent"]},
        ).scalar_one()
        if outcome == "refund":
            payments.refund(obj["payment_intent"])
    elif kind == "checkout.session.expired":
        connection.execute(
            text("SELECT private.expire_booking_checkout(:session)"),
            {"session": obj["id"]},
        )
    elif kind == "account.updated":
        connection.execute(
            text("SELECT private.set_coach_charges_enabled(:account, :enabled)"),
            {"account": obj["id"], "enabled": bool(obj.get("charges_enabled"))},
        )
