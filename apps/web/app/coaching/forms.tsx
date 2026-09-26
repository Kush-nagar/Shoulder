"use client";

import {
  CalendarX,
  Check,
  Clock,
  Flag,
  Receipt,
  RotateCcw,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  dateTimeLabel,
  dayKey,
  dayLabel,
  dayParts,
  send,
  timeLabel,
  useInBrowser,
} from "./client";
import {
  dollars,
  formatLabel,
  minutesBetween,
  refundIfCancelled,
  stripeUrl,
} from "./format";
import type { BookingStart, BookingStatus, OpenSlot } from "./types";
import {
  errorBox,
  field,
  fieldError,
  focus,
  hint,
  label,
  primaryButton,
  quietDanger,
  secondaryButton,
  successBox,
} from "./ui";

const OFFLINE =
  "Shoulder couldn't be reached. Check your connection and try again.";

/** Birth year only. The API refuses to lower an age once recorded. */
export function AgeForm() {
  const router = useRouter();
  const [year, setYear] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const max = new Date().getFullYear();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const reply = await send("/api/coaching/age-attestation", "PUT", {
      birth_year: Number(year),
    });
    setSaving(false);
    if (reply.status >= 200 && reply.status < 300) router.refresh();
    else if (reply.status === 409 || reply.status === 422)
      setError(
        "That year can't be saved. A birth year can't be changed to a later one once it's recorded.",
      );
    else
      setError(reply.status === 0 ? OFFLINE : "Nothing was saved. Try again.");
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="mt-6">
      <label htmlFor="birth-year" className={label}>
        Year you were born
      </label>
      <p id="birth-year-hint" className={`${hint} mt-1`}>
        Only the year is kept. It can&apos;t be changed to a later year.
      </p>
      <div className="mt-2 flex flex-wrap gap-3">
        <input
          id="birth-year"
          inputMode="numeric"
          type="number"
          min={1900}
          max={max}
          required
          value={year}
          onChange={(event) => setYear(event.target.value)}
          aria-describedby="birth-year-hint"
          aria-invalid={error ? true : undefined}
          className={`${field} min-w-0 flex-1 basis-32 tabular-nums`}
        />
        <button
          type="submit"
          disabled={saving || !year}
          className={primaryButton}
        >
          {saving ? "Saving…" : "Continue"}
        </button>
      </div>
      {error ? (
        <p role="alert" className={`${fieldError} mt-2`}>
          {error}
        </p>
      ) : null}
    </form>
  );
}

const PAYMENTS_SOON = "Booking opens soon — payments are being set up.";
const DAY_MS = 86_400_000;

/**
 * Pick a day, then a time (Calendly/Cal.com: only days with open times),
 * add an optional note, then pay on Stripe Checkout. Below 1024 px the
 * summary and button stick to the bottom of the screen (Airbnb's bar).
 */
export function BookForm({
  slots,
  rateCents,
}: {
  slots: OpenSlot[];
  rateCents: number;
}) {
  const ready = useInBrowser();
  const [dayChoice, setDayChoice] = useState<string | null>(null);
  const [slotId, setSlotId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ soon: boolean; text: string } | null>(
    null,
  );

  if (!slots.length) {
    return (
      <div className="rounded-xl bg-surface-subtle p-4">
        <p className="flex items-center gap-2 text-[16px] font-semibold">
          <CalendarX size={18} strokeWidth={2} aria-hidden="true" />
          No open times right now
        </p>
        <p className="mt-1 text-[15px] leading-6 text-ink-2">
          Coaches add times each week, so check back soon.
        </p>
      </div>
    );
  }

  const days: { key: string; first: string; slots: OpenSlot[] }[] = [];
  for (const slot of [...slots].sort((a, b) =>
    a.starts_at.localeCompare(b.starts_at),
  )) {
    const key = ready ? dayKey(slot.starts_at) : slot.starts_at.slice(0, 10);
    const last = days.at(-1);
    if (last?.key === key) last.slots.push(slot);
    else days.push({ key, first: slot.starts_at, slots: [slot] });
  }
  const day = days.find((d) => d.key === dayChoice) ?? days[0];
  const chosen = slots.find((slot) => slot.id === slotId) ?? null;
  const minutes = chosen ? minutesBetween(chosen.starts_at, chosen.ends_at) : 0;
  const price = chosen ? Math.round((rateCents * minutes) / 60) : null;

  async function book(event: FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    setBusy(true);
    setError(null);
    const reply = await send<BookingStart>("/api/coaching/bookings", "POST", {
      slot_id: chosen.id,
      note: note.trim() || null,
    });
    const target = stripeUrl(reply.data?.checkout_url);
    if (reply.status >= 200 && reply.status < 300 && target) {
      window.location.assign(target);
      return;
    }
    setBusy(false);
    if (reply.problem === "payments-unavailable") {
      setError({ soon: true, text: PAYMENTS_SOON });
      return;
    }
    setError({
      soon: false,
      text:
        reply.status === 409
          ? "Someone else is booking that time. Pick another one."
          : reply.status === 403
            ? "This coach isn't taking bookings right now."
            : reply.status === 0
              ? OFFLINE
              : "The booking didn't start. You weren't charged. Try again.",
    });
  }

  const payNote =
    "You pay on Stripe. Test mode: use a Stripe test card, no real charge.";

  return (
    <form onSubmit={(event) => void book(event)}>
      <fieldset disabled={busy} className="min-w-0">
        <legend className="text-[15px] font-semibold">Pick a day</legend>
        <ul className="-mx-1 mt-2 flex gap-2 overflow-x-auto px-1 pt-1 pb-2">
          {days.map((d) => {
            const parts = ready ? dayParts(d.first) : null;
            const on = d.key === day?.key;
            return (
              <li key={d.key} className="shrink-0">
                <label
                  className={`relative flex w-[68px] cursor-pointer flex-col items-center rounded-xl border py-2.5 transition-[background-color,border-color,color,transform] duration-150 ease-out active:scale-[0.97] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus ${
                    on
                      ? "border-ink bg-ink text-paper"
                      : "border-line-strong bg-surface hover:border-control-border"
                  }`}
                >
                  <input
                    type="radio"
                    name="day"
                    value={d.key}
                    checked={on}
                    onChange={() => {
                      setDayChoice(d.key);
                      setSlotId(null);
                    }}
                    className="sr-only"
                  />
                  <span className="text-[12px] font-semibold opacity-75">
                    {parts ? `${parts.weekday}` : " "}
                  </span>
                  <span className="font-display text-[26px] leading-[1.05] tabular-nums">
                    {parts?.day ?? " "}
                  </span>
                  <span className="text-[12px] opacity-75">
                    {parts?.month ?? " "}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      </fieldset>

      <fieldset disabled={busy} className="mt-4 min-w-0">
        <legend className="text-[15px] font-semibold">
          {ready && day ? dayLabel(day.first) : "Choose a time"}
        </legend>
        <ul className="mt-2 grid grid-cols-2 gap-2">
          {day?.slots.map((slot) => (
            <li key={slot.id}>
              <label className="relative flex min-h-14 cursor-pointer flex-col justify-center rounded-xl border border-line-strong bg-surface px-3.5 py-2 transition-[background-color,border-color,color,transform] duration-150 ease-out hover:border-control-border active:scale-[0.98] has-[:checked]:border-action has-[:checked]:bg-action has-[:checked]:text-on-action has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus">
                <input
                  type="radio"
                  name="slot"
                  value={slot.id}
                  checked={slotId === slot.id}
                  onChange={() => setSlotId(slot.id)}
                  className="sr-only"
                />
                <span className="text-[16px] font-semibold tabular-nums">
                  {ready ? timeLabel(slot.starts_at) : " "}
                </span>
                <span className="text-[13px] leading-5 opacity-80">
                  {minutesBetween(slot.starts_at, slot.ends_at)} min,{" "}
                  {formatLabel[slot.format]}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </fieldset>

      <div className="mt-6 space-y-2">
        <label
          htmlFor="booking-note"
          className="block text-[15px] font-semibold"
        >
          Note for the coach{" "}
          <span className="font-normal text-muted">(optional)</span>
        </label>
        <textarea
          id="booking-note"
          value={note}
          maxLength={280}
          rows={2}
          disabled={busy}
          onChange={(event) => setNote(event.target.value)}
          aria-describedby="booking-note-hint"
          className={`${field} py-2 leading-6`}
        />
        <p id="booking-note-hint" className={`${hint} tabular-nums`}>
          What you&apos;d like to work on. No phone numbers or addresses.{" "}
          {280 - note.length} characters left.
        </p>
      </div>

      <ul className="mt-6 space-y-3 border-t border-line pt-5 text-[14px] leading-5 text-ink-2">
        <li className="flex gap-3">
          <Receipt
            size={18}
            strokeWidth={2}
            aria-hidden="true"
            className="shrink-0 text-muted"
          />
          <span>
            No booking fee for you.{" "}
            {price !== null
              ? `The coach receives ${dollars(price - Math.round(price * 0.1))} after Shoulder's 10%.`
              : "Shoulder keeps 10% of the price from the coach's share."}
          </span>
        </li>
        <li className="flex gap-3">
          <RotateCcw
            size={18}
            strokeWidth={2}
            aria-hidden="true"
            className="shrink-0 text-muted"
          />
          <span>
            {chosen && ready
              ? `Full refund if you cancel before ${dateTimeLabel(new Date(Date.parse(chosen.starts_at) - DAY_MS).toISOString())}.`
              : "Full refund if you cancel more than 24 hours before."}{" "}
            If the coach cancels, you always get a full refund.
          </span>
        </li>
      </ul>

      {error ? (
        <p
          role="alert"
          className={`mt-5 flex items-start gap-2 ${
            error.soon
              ? "rounded-xl border border-line-strong bg-surface-subtle p-4 text-[16px] font-semibold leading-6 text-ink"
              : errorBox
          }`}
        >
          {error.soon ? (
            <Clock
              size={20}
              strokeWidth={2}
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-action"
            />
          ) : null}
          {error.text}
        </p>
      ) : null}

      <div className="sticky bottom-0 z-10 -mx-5 mt-5 border-t border-line bg-surface/95 px-5 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur-md max-md:[.sh-shell_&]:bottom-[calc(64px+env(safe-area-inset-bottom))] max-md:[.sh-shell_&]:pb-3 md:-mx-6 md:px-6 lg:static lg:mx-0 lg:border-t-0 lg:bg-transparent lg:px-0 lg:pt-0 lg:pb-0 lg:backdrop-blur-none">
        <div className="flex items-center gap-4">
          <p className="min-w-0 flex-1" aria-live="polite">
            {chosen && ready ? (
              <>
                <span className="block text-[20px] font-semibold leading-tight tabular-nums">
                  {dollars(price ?? 0)}
                </span>
                <span className="block truncate text-[13px] text-ink-2">
                  {dateTimeLabel(chosen.starts_at)}, {minutes} min
                  {chosen.venue ? `, ${chosen.venue}` : ""}
                </span>
              </>
            ) : (
              <>
                <span className="block text-[20px] font-semibold leading-tight tabular-nums">
                  {dollars(rateCents)}
                  <span className="text-[14px] font-normal text-ink-2">
                    {" "}
                    / hour
                  </span>
                </span>
                <span className="block text-[13px] text-muted">
                  Pick a time to see the price
                </span>
              </>
            )}
          </p>
          <span className="lg:hidden">
            <button
              type="submit"
              disabled={!chosen || busy}
              className={primaryButton}
            >
              {busy ? "Opening…" : "Book and pay"}
            </button>
          </span>
        </div>
        <div className="mt-4 hidden lg:block">
          <button
            type="submit"
            disabled={!chosen || busy}
            className={`${primaryButton} w-full`}
          >
            {busy
              ? "Opening checkout…"
              : price === null
                ? "Book and pay"
                : `Book and pay ${dollars(price)}`}
          </button>
          <p className={`${hint} mt-2`}>{payNote}</p>
        </div>
      </div>
      <p className={`${hint} mt-3 lg:hidden`}>{payNote}</p>
    </form>
  );
}

function refundSentence(
  booking: { status: BookingStatus; starts_at: string; price_cents: number },
  now: number,
): string {
  const refund = refundIfCancelled(booking, now);
  if (refund === null) return "You haven't paid yet, so nothing is charged.";
  if (refund > 0)
    return `It's more than 24 hours away, so you get a full refund of ${dollars(refund)}.`;
  return "It starts within 24 hours, so there's no refund.";
}

/** Cancel with an inline confirmation that opens on the safe choice. */
export function CancelBooking({
  booking,
}: {
  booking: {
    id: string;
    status: BookingStatus;
    starts_at: string;
    price_cents: number;
  };
}) {
  const router = useRouter();
  const keepRef = useRef<HTMLButtonElement>(null);
  const [now, setNow] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (now !== null) keepRef.current?.focus();
  }, [now]);

  async function cancel() {
    setBusy(true);
    setError(null);
    const reply = await send(
      `/api/coaching/bookings/${booking.id}/cancel`,
      "POST",
    );
    setBusy(false);
    if (reply.status >= 200 && reply.status < 300) {
      setNow(null);
      router.refresh();
    } else
      setError(
        reply.status === 0 ? OFFLINE : "The booking is still on. Try again.",
      );
  }

  if (now === null) {
    return (
      <button
        type="button"
        onClick={() => setNow(Date.now())}
        className={quietDanger}
      >
        <X size={18} strokeWidth={2} aria-hidden="true" />
        Cancel booking
      </button>
    );
  }
  const titleId = `cancel-${booking.id}`;
  return (
    <div
      role="alertdialog"
      aria-labelledby={titleId}
      aria-describedby={`${titleId}-body`}
      className="rounded-xl border border-line-strong bg-surface-subtle p-4 md:p-5"
    >
      <h3 id={titleId} className="text-[17px] font-semibold">
        Cancel this session?
      </h3>
      <p
        id={`${titleId}-body`}
        className="mt-1 text-[16px] leading-6 text-ink-2"
      >
        {refundSentence(booking, now)} The time opens up for other players.
      </p>
      {error ? (
        <p role="alert" className={`${fieldError} mt-2`}>
          {error}
        </p>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void cancel()}
          disabled={busy}
          className={secondaryButton}
        >
          {busy ? "Cancelling…" : "Cancel session"}
        </button>
        <button
          type="button"
          ref={keepRef}
          onClick={() => setNow(null)}
          disabled={busy}
          className={primaryButton}
        >
          Keep it
        </button>
      </div>
    </div>
  );
}

/** Report a concern about a coach. An open report pauses new bookings. */
export function ReportForm({
  coachId,
  bookingId,
}: {
  coachId: string;
  bookingId: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = `report-${bookingId ?? coachId}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const reply = await send("/api/coaching/reports", "POST", {
      coach_profile_id: coachId,
      booking_id: bookingId,
      reason: reason.trim(),
    });
    setBusy(false);
    if (reply.status >= 200 && reply.status < 300) setSent(true);
    else
      setError(
        reply.status === 409
          ? "You already have an open report about this coach. We're looking at it."
          : reply.status === 429
            ? "You've sent several reports today. Try again tomorrow."
            : reply.status === 0
              ? OFFLINE
              : "The report wasn't sent. Try again.",
      );
  }

  if (sent) {
    return (
      <p role="status" className={`${successBox} flex items-start gap-2`}>
        <Check
          size={20}
          strokeWidth={2}
          aria-hidden="true"
          className="mt-0.5 shrink-0"
        />
        Report sent. The Shoulder team reads every report. This coach can&apos;t
        take new bookings while it&apos;s open.
      </p>
    );
  }
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`${quietDanger} hover:text-ink`}
      >
        <Flag size={18} strokeWidth={2} aria-hidden="true" />
        Report a concern
      </button>
    );
  }
  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="max-w-[560px] space-y-2"
    >
      <label htmlFor={id} className={label}>
        What happened?
      </label>
      <p id={`${id}-hint`} className={hint}>
        10 to 1,000 characters. Only the Shoulder team sees this, not the coach.
        If someone is in danger, call 911.
      </p>
      <textarea
        id={id}
        value={reason}
        minLength={10}
        maxLength={1000}
        rows={4}
        required
        disabled={busy}
        onChange={(event) => setReason(event.target.value)}
        aria-describedby={`${id}-hint`}
        className={`${field} py-2 leading-6`}
      />
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-3 pt-1">
        <button
          type="submit"
          disabled={busy || reason.trim().length < 10}
          className={primaryButton}
        >
          {busy ? "Sending…" : "Send report"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          disabled={busy}
          className={`${secondaryButton} ${focus}`}
        >
          Not now
        </button>
      </div>
    </form>
  );
}
