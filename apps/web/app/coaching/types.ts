import type { components } from "@shoulder/contracts";

// Marketplace types come from the FastAPI OpenAPI document (AGENTS.md).
type Schema = components["schemas"];

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
] as const satisfies readonly Schema["MarketplaceCoach"]["specialties"][number][];
export type Specialty = Schema["MarketplaceCoach"]["specialties"][number];

export const FORMATS = [
  "in_person",
  "online",
] as const satisfies readonly Schema["MarketplaceCoach"]["formats"][number][];
export type Format = Schema["MarketplaceCoach"]["formats"][number];

export type CoachStatus = Schema["CoachProfile"]["status"];
export type BookingStatus = Schema["PlayerBooking"]["status"];
export type AgeAttestation = Schema["AgeAttestation"];
export type MarketplaceCoach = Schema["MarketplaceCoach"];
export type OpenSlot = Schema["PublicSlot"];
export type MarketplaceCoachDetail = Schema["MarketplaceCoachDetail"];
export type BookingStart = Schema["BookingCheckout"];
export type PlayerBooking = Schema["PlayerBooking"];
export type CoachDocument = Schema["CoachDocument"];
export type CoachProfile = Schema["CoachProfile"];
export type CoachProfileInput = Schema["CoachProfileUpdate"];
export type DocumentUploadStart = Schema["CoachDocumentUpload"];
export type StripeOnboarding = Schema["StripeOnboarding"];
export type CoachSlot = Schema["CoachSlot"];
export type SlotInput = Schema["CoachSlotCreate"];
export type CoachBooking = Schema["CoachBooking"];
export type CoachReviewSummary = Schema["CoachReviewSummary"];
export type ReviewDocument = Schema["AdminDocument"];
export type CoachReviewDetail = Schema["CoachReview"];
export type Decision = Schema["CoachDecisionRequest"]["decision"];
export type MarketplaceReport = Schema["MarketplaceReport"];
