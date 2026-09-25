"""Coach marketplace endpoints (Block 10M). All 404 unless `MARKETPLACE_ENABLED=on`.

Adults only: an account without an 18+ birth-year attestation cannot browse,
view, or book a coach. Stripe runs in test mode (see `payments`).
"""

from collections.abc import Callable
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError
from starlette.concurrency import run_in_threadpool

from services.api import marketplace_service as service
from services.api import payments, storage
from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.practice_routes import BoundedBodyRoute
from services.api.problems import Problem
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import (
    AdminDocumentUrl,
    AgeAttestation,
    AgeAttestationUpdate,
    BookingCheckout,
    BookingCreate,
    CoachBooking,
    CoachDecisionRequest,
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
    CoachSpecialty,
    MarketplaceCoach,
    MarketplaceCoachDetail,
    MarketplaceReport,
    MarketplaceReportCreate,
    PlayerBooking,
    ReportStatus,
    StripeOnboarding,
)
from services.api.video import storage_unavailable

T = TypeVar("T")
User = Annotated[str, Depends(authenticated_identity)]


def require_enabled() -> None:
    if not service.enabled():
        raise Problem(404, "Not found.")


class WebhookRoute(BoundedBodyRoute):
    # Stripe events run to a few kilobytes; nothing legitimate is near this.
    max_bytes = 256 * 1024


GATED = [Depends(require_enabled)]
router = APIRouter(prefix="/v1", route_class=BoundedBodyRoute, dependencies=GATED)
webhook_router = APIRouter(prefix="/v1", route_class=WebhookRoute, dependencies=GATED)


def run(user_id: str, work: Callable[[Connection], T]) -> T:
    """One transaction as the user; provider failures roll it back."""
    try:
        with user_transaction(user_id) as connection:
            return work(connection)
    except storage.StorageError:
        raise storage_unavailable() from None
    except payments.PaymentsUnavailable:
        raise Problem(
            502, "Payments are unavailable right now. Try again later."
        ) from None
    except DBAPIError:
        raise unavailable() from None


# -- age attestation ----


@router.get("/me/age-attestation", response_model=AgeAttestation, dependencies=PRIVATE)
def read_age(user_id: User) -> AgeAttestation:
    return run(user_id, service.read_attestation)


@router.put("/me/age-attestation", response_model=AgeAttestation, dependencies=PRIVATE)
def put_age(body: AgeAttestationUpdate, user_id: User) -> AgeAttestation:
    return run(user_id, lambda c: service.attest(c, body.birth_year))


# -- coach self ----


@router.get("/coach-profile", response_model=CoachProfile, dependencies=PRIVATE)
def read_coach_profile(user_id: User) -> CoachProfile:
    return run(user_id, service.read_profile)


@router.put("/coach-profile", response_model=CoachProfile, dependencies=PRIVATE)
def put_coach_profile(body: CoachProfileUpdate, user_id: User) -> CoachProfile:
    return run(user_id, lambda c: service.save_profile(c, body))


@router.post(
    "/coach-profile/documents",
    response_model=CoachDocumentUpload,
    status_code=201,
    dependencies=PRIVATE,
)
def create_coach_document(
    body: CoachDocumentCreate, user_id: User
) -> CoachDocumentUpload:
    return run(user_id, lambda c: service.create_document(c, body))


@router.post(
    "/coach-profile/documents/{document_id}/complete",
    response_model=CoachDocument,
    dependencies=PRIVATE,
)
def complete_coach_document(document_id: UUID, user_id: User) -> CoachDocument:
    document = run(user_id, lambda c: service.complete_document(c, document_id))
    if document is None:
        raise Problem(
            422,
            "The uploaded file does not match what was declared.",
            "upload-mismatch",
        )
    return document


@router.post("/coach-profile/submit", response_model=CoachProfile, dependencies=PRIVATE)
def submit_coach_profile(user_id: User) -> CoachProfile:
    return run(user_id, service.submit_profile)


@router.post(
    "/coach-profile/stripe/onboarding",
    response_model=StripeOnboarding,
    dependencies=PRIVATE,
)
def coach_stripe_onboarding(user_id: User) -> StripeOnboarding:
    return StripeOnboarding(url=run(user_id, service.stripe_onboarding))


@router.get(
    "/coach-profile/slots", response_model=list[CoachSlot], dependencies=PRIVATE
)
def list_coach_slots(user_id: User) -> list[CoachSlot]:
    return run(user_id, service.list_slots)


@router.post(
    "/coach-profile/slots",
    response_model=CoachSlot,
    status_code=201,
    dependencies=PRIVATE,
)
def create_coach_slot(body: CoachSlotCreate, user_id: User) -> CoachSlot:
    return run(user_id, lambda c: service.create_slot(c, body))


@router.delete("/coach-profile/slots/{slot_id}", status_code=204, dependencies=PRIVATE)
def delete_coach_slot(slot_id: UUID, user_id: User) -> Response:
    run(user_id, lambda c: service.delete_slot(c, slot_id))
    return Response(status_code=204)


@router.get(
    "/coach-profile/bookings", response_model=list[CoachBooking], dependencies=PRIVATE
)
def list_coach_bookings(user_id: User) -> list[CoachBooking]:
    return run(user_id, service.coach_bookings)


# -- platform admin ----


@router.get(
    "/admin/coach-reviews",
    response_model=list[CoachReviewSummary],
    dependencies=PRIVATE,
)
def admin_review_queue(
    user_id: User,
    status: Annotated[CoachProfileStatus, Query()] = "pending_review",
) -> list[CoachReviewSummary]:
    return run(user_id, lambda c: service.review_queue(c, status))


@router.get(
    "/admin/coach-reviews/{profile_id}",
    response_model=CoachReview,
    dependencies=PRIVATE,
)
def admin_review_detail(profile_id: UUID, user_id: User) -> CoachReview:
    return run(user_id, lambda c: service.review_detail(c, profile_id))


@router.get(
    "/admin/coach-reviews/{profile_id}/documents/{document_id}/url",
    response_model=AdminDocumentUrl,
    dependencies=PRIVATE,
)
def admin_document_url(
    profile_id: UUID, document_id: UUID, user_id: User
) -> AdminDocumentUrl:
    return run(
        user_id, lambda c: service.review_document_url(c, profile_id, document_id)
    )


@router.post(
    "/admin/coach-reviews/{profile_id}/decision",
    response_model=CoachReviewSummary,
    dependencies=PRIVATE,
)
def admin_decide(
    profile_id: UUID, body: CoachDecisionRequest, user_id: User
) -> CoachReviewSummary:
    return run(
        user_id, lambda c: service.decide(c, profile_id, body.decision, body.note)
    )


@router.get(
    "/admin/reports", response_model=list[MarketplaceReport], dependencies=PRIVATE
)
def admin_list_reports(
    user_id: User, status: Annotated[ReportStatus, Query()] = "open"
) -> list[MarketplaceReport]:
    return run(user_id, lambda c: service.admin_reports(c, status))


@router.post(
    "/admin/reports/{report_id}/resolve",
    response_model=MarketplaceReport,
    dependencies=PRIVATE,
)
def admin_resolve_report(report_id: UUID, user_id: User) -> MarketplaceReport:
    return run(user_id, lambda c: service.resolve_report(c, report_id))


# -- adults ----


@router.get(
    "/marketplace/coaches", response_model=list[MarketplaceCoach], dependencies=PRIVATE
)
def browse_coaches(
    user_id: User,
    specialty: Annotated[CoachSpecialty | None, Query()] = None,
    city: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
) -> list[MarketplaceCoach]:
    return run(user_id, lambda c: service.browse(c, specialty, city))


@router.get(
    "/marketplace/coaches/{profile_id}",
    response_model=MarketplaceCoachDetail,
    dependencies=PRIVATE,
)
def read_marketplace_coach(profile_id: UUID, user_id: User) -> MarketplaceCoachDetail:
    return run(user_id, lambda c: service.coach_detail(c, profile_id))


@router.post(
    "/marketplace/bookings",
    response_model=BookingCheckout,
    status_code=201,
    dependencies=PRIVATE,
)
def create_booking(body: BookingCreate, user_id: User) -> BookingCheckout:
    return run(user_id, lambda c: service.book(c, body))


@router.get("/me/bookings", response_model=list[PlayerBooking], dependencies=PRIVATE)
def list_my_bookings(user_id: User) -> list[PlayerBooking]:
    return run(user_id, service.player_bookings)


@router.post(
    "/me/bookings/{booking_id}/cancel",
    response_model=PlayerBooking,
    dependencies=PRIVATE,
)
def cancel_my_booking(booking_id: UUID, user_id: User) -> PlayerBooking:
    return run(user_id, lambda c: service.player_cancel(c, booking_id))


@router.post(
    "/marketplace/reports",
    response_model=MarketplaceReport,
    status_code=201,
    dependencies=PRIVATE,
)
def create_report(body: MarketplaceReportCreate, user_id: User) -> MarketplaceReport:
    return run(user_id, lambda c: service.report(c, body))


# -- Stripe ----


@webhook_router.post("/stripe/webhook", status_code=204, include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> Response:
    payload = await request.body()
    try:
        event = payments.verify_webhook(payload, stripe_signature)
    except payments.InvalidWebhook:
        raise Problem(400, "The event could not be verified.") from None
    except payments.PaymentsUnavailable:
        raise unavailable() from None
    # No user identity: the definer functions accept only verified Stripe
    # facts (a session id, a payment intent, an account id).
    await run_in_threadpool(run, "", lambda c: service.apply_event(c, event))
    return Response(status_code=204)
