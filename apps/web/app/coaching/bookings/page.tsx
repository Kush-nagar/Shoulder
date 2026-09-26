import { Check, Info, Laptop, MapPin } from "lucide-react";
import Link from "next/link";
import { When } from "../client";
import { bookingStatusLabel, dollars, formatLabel } from "../format";
import { CancelBooking, ReportForm } from "../forms";
import { adultOnly } from "../gate";
import { Monogram, StatusChip } from "../parts";
import { read } from "../server";
import type { PlayerBooking } from "../types";
import {
  emptyBox,
  errorBox,
  focus,
  pageTitle,
  primaryButton,
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
  const Where = booking.format === "online" ? Laptop : MapPin;
  return (
    <li className="rounded-2xl border border-line bg-surface p-4 md:p-5">
      <div className="flex items-start gap-4">
        <Monogram
          name={booking.coach_display_name}
          size="size-12 text-[20px]"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <When
              iso={booking.starts_at}
              className="text-[17px] font-semibold tabular-nums"
            />
            <StatusChip
              status={booking.status}
              label={bookingStatusLabel[booking.status]}
            />
          </div>
          <Link
            href={`/coaching/coaches/${booking.coach_profile_id}`}
            className={`mt-0.5 inline-block rounded font-display text-[22px] leading-[1.15] underline-offset-4 hover:underline ${focus}`}
          >
            {booking.coach_display_name}
          </Link>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[15px] leading-6 text-ink-2">
            <span className="inline-flex items-center gap-1.5">
              <Where size={16} strokeWidth={2} aria-hidden="true" />
              {formatLabel[booking.format]}
              {booking.venue ? `, ${booking.venue}` : ""}
            </span>
            <span className="tabular-nums">
              {dollars(booking.price_cents)}
              {booking.refund_cents > 0
                ? `, ${dollars(booking.refund_cents)} refunded`
                : ""}
            </span>
          </p>
          {booking.note ? (
            <p className="mt-2 max-w-[60ch] rounded-lg bg-surface-subtle px-3 py-2 text-[15px] leading-6 text-ink-2">
              <span className="font-semibold text-ink">Your note:</span>{" "}
              {booking.note}
            </p>
          ) : null}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-start gap-x-6 gap-y-2 border-t border-line pt-3 md:pl-16">
        {upcoming ? <CancelBooking booking={booking} /> : null}
        <ReportForm coachId={booking.coach_profile_id} bookingId={booking.id} />
      </div>
    </li>
  );
}

export default async function BookingsPage({
  searchParams,
}: {
  searchParams: Promise<{ checkout?: string; tab?: string }>;
}) {
  const gate = await adultOnly("/coaching/bookings");
  if (!gate.token) return gate.blocked;
  const { checkout, tab } = await searchParams;
  const bookings = await read<PlayerBooking[]>(gate.token, "/v1/me/bookings");
  const now = Date.now();
  const all = [...(bookings.data ?? [])].sort((a, b) =>
    a.starts_at.localeCompare(b.starts_at),
  );
  const upcoming = all.filter(
    (b) => LIVE.has(b.status) && Date.parse(b.ends_at) > now,
  );
  const past = all.filter((b) => !upcoming.includes(b)).reverse();
  const showPast = tab === "past";
  const shown = showPast ? past : upcoming;

  const tabClass = (on: boolean) =>
    `relative inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-[15px] transition-colors duration-150 ${focus} ${
      on ? "font-semibold text-ink" : "text-ink-2 hover:text-ink"
    }`;
  const count = (n: number, on: boolean) => (
    <span
      className={`inline-flex min-w-6 items-center justify-center rounded-full px-1.5 text-[12px] font-semibold tabular-nums ${
        on ? "bg-ink text-paper" : "bg-surface-subtle text-ink-2"
      }`}
    >
      {n}
    </span>
  );

  return (
    <div className="max-w-[860px]">
      <h1 className={`${pageTitle} md:text-[40px]`}>Your bookings</h1>

      {checkout === "success" ? (
        <p
          role="status"
          className={`${successBox} sh-rise mt-6 flex items-start gap-3`}
        >
          <Check
            size={20}
            strokeWidth={2.5}
            aria-hidden="true"
            className="mt-0.5 shrink-0 text-action"
          />
          <span>
            <span className="block font-semibold">Payment received.</span>
            Your booking shows as confirmed once Stripe tells us, usually within
            a minute. Refresh if it still says waiting.
          </span>
        </p>
      ) : checkout === "cancelled" ? (
        <p
          role="status"
          className="sh-rise mt-6 flex items-start gap-3 rounded-xl border border-line-strong bg-surface-subtle p-4 text-[16px] leading-6"
        >
          <Info
            size={20}
            strokeWidth={2}
            aria-hidden="true"
            className="mt-0.5 shrink-0"
          />
          <span>
            <span className="block font-semibold">Checkout cancelled.</span>
            You weren&apos;t charged. The time is held for 15 minutes, then it
            opens up again.
          </span>
        </p>
      ) : null}

      {bookings.data === null ? (
        <p role="alert" className={`${errorBox} mt-8`}>
          Your bookings couldn&apos;t load. Try again in a moment.
        </p>
      ) : (
        <>
          <nav aria-label="Bookings" className="mt-8 border-b border-line">
            <ul className="-mb-px flex gap-1">
              {(
                [
                  [false, "Upcoming", upcoming.length, "/coaching/bookings"],
                  [
                    true,
                    "Past and cancelled",
                    past.length,
                    "/coaching/bookings?tab=past",
                  ],
                ] as const
              ).map(([isPast, name, n, href]) => {
                const on = isPast === showPast;
                return (
                  <li key={name}>
                    <Link
                      href={href}
                      scroll={false}
                      aria-current={on ? "page" : undefined}
                      className={tabClass(on)}
                    >
                      {on ? (
                        <span
                          aria-hidden="true"
                          className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-action"
                        />
                      ) : null}
                      {name}
                      {count(n, on)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <h2 className="sr-only">
            {showPast ? "Past and cancelled" : "Upcoming"}
          </h2>
          {shown.length ? (
            <ul className="sh-stagger mt-5 space-y-3">
              {shown.map((b) => (
                <Row key={b.id} booking={b} upcoming={!showPast} />
              ))}
            </ul>
          ) : (
            <div className={`${emptyBox} mt-5`}>
              <p className="text-[17px] font-semibold">
                {showPast ? "No past sessions yet." : "Nothing booked yet."}
              </p>
              <p className="mt-1 text-[16px] leading-6 text-ink-2">
                {showPast
                  ? "Finished and cancelled sessions show here."
                  : "Find a coach and pick a time that works for you."}
              </p>
              {showPast ? null : (
                <Link href="/coaching" className={`${primaryButton} mt-4`}>
                  Find a coach
                </Link>
              )}
            </div>
          )}
        </>
      )}

      <p className="mt-10 max-w-[60ch] text-[14px] leading-5 text-muted">
        Cancel more than 24 hours before a session for a full refund. If the
        coach cancels, you always get a full refund.
      </p>
    </div>
  );
}
