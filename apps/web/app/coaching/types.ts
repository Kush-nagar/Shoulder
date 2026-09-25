// TEMP until OpenAPI regen at integration.
// Hand-written against the frozen Block 10M API table in
// docs/projects/project-10-coach-marketplace.md. Response field names that the
// table does not spell out are assumptions; replace this whole file with
// `components["schemas"]` from @shoulder/contracts once M1 lands and
// `pnpm contracts` regenerates the types.

export const SPECIALTIES = [
  "scanning",
  "first_touch",
  "passing",
  "finishing",
  "dribbling",
  "defending",
  "goalkeeping",
  "fitness",
  "tactics",
] as const;
export type Specialty = (typeof SPECIALTIES)[number];

export const FORMATS = ["in_person", "online"] as const;
export type Format = (typeof FORMATS)[number];

export type CoachStatus =
  | "draft"
  | "pending_review"
  | "verified"
  | "suspended"
  | "rejected";

export type BookingStatus =
  | "pending_payment"
  | "confirmed"
  | "cancelled_by_player"
  | "cancelled_by_coach"
  | "expired"
  | "completed";

/** GET/PUT /v1/me/age-attestation */
export type AgeAttestation = { birth_year: number; adult: boolean };

/** Public columns from GET /v1/marketplace/coaches */
export type MarketplaceCoach = {
  id: string;
  display_name: string;
  bio: string;
  specialties: Specialty[];
  city: string;
  formats: Format[];
  rate_cents: number;
};

export type OpenSlot = {
  id: string;
  starts_at: string;
  ends_at: string;
  format: Format;
  venue: string | null;
};

/** GET /v1/marketplace/coaches/{id} */
export type MarketplaceCoachDetail = MarketplaceCoach & { slots: OpenSlot[] };

/** POST /v1/marketplace/bookings */
export type BookingStart = { booking_id: string; checkout_url: string };

/** GET /v1/me/bookings */
export type PlayerBooking = {
  id: string;
  status: BookingStatus;
  coach_profile_id: string;
  coach_display_name: string;
  starts_at: string;
  ends_at: string;
  format: Format;
  venue: string | null;
  price_cents: number;
  refund_cents: number;
  note: string | null;
};

export type CoachDocument = {
  id: string;
  kind: "background_check" | "id" | "certification";
  content_type: "application/pdf" | "image/jpeg" | "image/png";
  size_bytes: number;
  uploaded_at: string;
  status: "uploading" | "ready";
};

/** GET/PUT /v1/coach-profile (documents assumed embedded on GET) */
export type CoachProfile = {
  id: string;
  display_name: string;
  bio: string;
  specialties: Specialty[];
  city: string;
  formats: Format[];
  rate_cents: number;
  status: CoachStatus;
  review_note: string | null;
  charges_enabled: boolean;
  documents?: CoachDocument[];
};

export type CoachProfileInput = Pick<
  CoachProfile,
  "display_name" | "bio" | "specialties" | "city" | "formats" | "rate_cents"
>;

/** POST /v1/coach-profile/documents */
export type DocumentUploadStart = { id: string; upload_url: string };

/** POST /v1/coach-profile/stripe/onboarding */
export type StripeOnboarding = { url: string };

/** GET/POST /v1/coach-profile/slots */
export type CoachSlot = OpenSlot & {
  status: "open" | "held" | "booked" | "cancelled";
};
export type SlotInput = {
  starts_at: string;
  ends_at: string;
  format: Format;
  venue: string | null;
};

/** GET /v1/coach-profile/bookings: player shown by first name only. */
export type CoachBooking = {
  id: string;
  status: BookingStatus;
  player_first_name: string;
  starts_at: string;
  ends_at: string;
  format: Format;
  venue: string | null;
  price_cents: number;
  platform_fee_cents: number;
  note: string | null;
};

/** GET /v1/admin/coach-reviews?status= */
export type CoachReviewSummary = {
  id: string;
  display_name: string;
  city: string;
  status: CoachStatus;
  updated_at: string;
};

export type ReviewDocument = CoachDocument & { url: string };

/** GET /v1/admin/coach-reviews/{id} */
export type CoachReviewDetail = Omit<CoachProfile, "documents"> & {
  updated_at: string;
  documents: ReviewDocument[];
};

export type Decision = "approve" | "reject" | "suspend" | "reinstate";

/** GET /v1/admin/reports */
export type MarketplaceReport = {
  id: string;
  coach_profile_id: string;
  coach_display_name: string;
  booking_id: string | null;
  reason: string;
  status: "open" | "resolved";
  created_at: string;
};
