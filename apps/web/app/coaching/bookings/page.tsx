import { Check, Info } from "lucide-react";
import Link from "next/link";
import { When } from "../client";
import { bookingStatusLabel, dollars, formatLabel } from "../format";
import { CancelBooking, ReportForm } from "../forms";
import { adultOnly } from "../gate";
import { read } from "../server";
import type { PlayerBooking } from "../types";
import {
  emptyBox,
  errorBox,
  pageTitle,
  primaryButton,
  sectionTitle,
  successBox,
} from "../ui";

const LIVE = new Set(["pending_payment", "confirmed"]);

function Row({
  booking,
  upcoming,
}: {
  booking: PlayerBooking;
  upcoming: boolean;
}) {
  return (
    <li className="grid gap-4 py-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-8">
      <div className="min-w-0">
        <When
          iso={booking.starts_at}
          className="block text-[17px] font-semibold tabular-nums"
        />
        <Link
          href={`/coaching/coaches/${booking.coach_profile_id}`}
          className="mt-0.5 inline-block font-display text-[24px] leading-[1.15] underline-offset-4 hover:underline"
        >
          {booking.coach_display_name}
        </Link>
        <p className="mt-1 text-[15px] leading-6 text-ink-2">
          {formatLabel[booking.format]}
          {booking.venue ? `, ${booking.venue}` : ""}
        </p>
        <p className="mt-1 text-[15px] leading-6 text-ink-2 tabular-nums">
          <span className="font-semibold text-ink">
            {bookingStatusLabel[booking.status]}
          </span>
          {", "}
          {dollars(booking.price_cents)}
          {booking.refund_cents > 0
            ? `, ${dollars(booking.refund_cents)} refunded`
            : ""}
        </p>
        {booking.note ? (
          <p className="mt-2 max-w-[60ch] text-[15px] leading-6 text-muted">
            Your note: {booking.note}
          </p>
        ) : null}
      </div>
      <div className="min-w-0 space-y-2 md:pt-1">
        {upcoming ? <CancelBooking booking={booking} /> : null}
        <ReportForm coachId={booking.coach_profile_id} bookingId={booking.id} />
      </div>
    </li>
  );
}

export default async function BookingsPage({
  searchParams,
}: {
  searchParams: Promise<{ checkout?: string }>;
}) {
  const gate = await adultOnly("/coaching/bookings");
  if (!gate.token) return gate.blocked;
  const { checkout } = await searchParams;
  const bookings = await read<PlayerBooking[]>(gate.token, "/v1/me/bookings");
  const now = Date.now();
  const all = [...(bookings.data ?? [])].sort((a, b) =>
    a.starts_at.localeCompare(b.starts_at),
  );
  const upcoming = all.filter(
    (b) => LIVE.has(b.status) && Date.parse(b.ends_at) > now,
  );
  const past = all.filter((b) => !upcoming.includes(b)).reverse();

  return (
    <div className="max-w-[920px]">
      <h1 className={pageTitle}>Your bookings</h1>

      {checkout === "success" ? (
        <p
          role="status"
          className={`${successBox} mt-6 flex items-start gap-2`}
        >
          <Check
            size={20}
            strokeWidth={2}
            aria-hidden="true"
            className="mt-0.5 shrink-0"
          />
          Payment received. Your booking shows as confirmed once Stripe tells
          us, usually within a minute. Refresh if it still says waiting.
        </p>
      ) : checkout === "cancelled" ? (
        <p
          role="status"
          className="mt-6 flex items-start gap-2 rounded-xl border border-line-strong bg-surface-subtle p-4 text-[16px] leading-6"
        >
          <Info
            size={20}
            strokeWidth={2}
            aria-hidden="true"
            className="mt-0.5 shrink-0"
          />
          Checkout was cancelled and you weren&apos;t charged. The time is held
          for 15 minutes, then it opens up again.
        </p>
      ) : null}

      {bookings.data === null ? (
        <p role="alert" className={`${errorBox} mt-8`}>
          Your bookings couldn&apos;t load. Try again in a moment.
        </p>
      ) : (
        <>
          <section aria-labelledby="upcoming-title" className="mt-8">
            <h2 id="upcoming-title" className={sectionTitle}>
              Upcoming
            </h2>
            {upcoming.length ? (
              <ul className="mt-2 divide-y divide-line border-b border-line">
                {upcoming.map((b) => (
                  <Row key={b.id} booking={b} upcoming />
                ))}
              </ul>
            ) : (
              <div className={`${emptyBox} mt-4`}>
                <p className="text-[16px] font-semibold">Nothing booked yet.</p>
                <p className="mt-1 text-[16px] leading-6 text-ink-2">
                  Find a coach and pick a time that works for you.
                </p>
                <Link href="/coaching" className={`${primaryButton} mt-4`}>
                  Find a coach
                </Link>
              </div>
            )}
          </section>

          {past.length ? (
            <section aria-labelledby="past-title" className="mt-12">
              <h2 id="past-title" className={sectionTitle}>
                Past and cancelled
              </h2>
              <ul className="mt-2 divide-y divide-line border-b border-line">
                {past.map((b) => (
                  <Row key={b.id} booking={b} upcoming={false} />
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}

      <p className="mt-10 max-w-[60ch] text-[14px] leading-5 text-muted">
        Cancel more than 24 hours before a session for a full refund. If the
        coach cancels, you always get a full refund.
      </p>
    </div>
  );
}
