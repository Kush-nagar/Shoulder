import type { BookingStatus, Format, Specialty } from "./types";

export const specialtyLabel: Record<Specialty, string> = {
  scanning: "Scanning",
  first_touch: "First touch",
  passing: "Passing",
  finishing: "Finishing",
  dribbling: "Dribbling",
  defending: "Defending",
  goalkeeping: "Goalkeeping",
  fitness: "Fitness",
  tactics: "Tactics",
};

export const formatLabel: Record<Format, string> = {
  in_person: "In person",
  online: "Online",
};

export const bookingStatusLabel: Record<BookingStatus, string> = {
  pending_payment: "Waiting for payment",
  confirmed: "Confirmed",
  cancelled_by_player: "You cancelled",
  cancelled_by_coach: "Coach cancelled",
  expired: "Payment not finished",
  completed: "Done",
};

/** "$45" or "$45.50". */
export function dollars(cents: number): string {
  return `$${(cents / 100).toFixed(cents % 100 ? 2 : 0)}`;
}

export function minutesBetween(start: string, end: string): number {
  return Math.round((Date.parse(end) - Date.parse(start)) / 60000);
}

const DAY = 24 * 60 * 60 * 1000;

/**
 * Refund the player gets for cancelling now (owner decision, Block 10M):
 * full refund more than 24 hours before the start, nothing after. Nothing was
 * charged while payment is still pending.
 */
export function refundIfCancelled(
  booking: { status: BookingStatus; starts_at: string; price_cents: number },
  now: number,
): number | null {
  if (booking.status === "pending_payment") return null;
  return Date.parse(booking.starts_at) - now > DAY ? booking.price_cents : 0;
}

/**
 * Checkout and Connect onboarding links come from the API; only an https
 * Stripe page may receive the browser.
 */
export function stripeUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      (url.hostname === "stripe.com" || url.hostname.endsWith(".stripe.com"))
      ? url.href
      : null;
  } catch {
    return null;
  }
}
