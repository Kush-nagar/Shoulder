"use client";

import { Check, Flag, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { dayKey, dayLabel, send, timeLabel, useInBrowser } from "./client";
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
    <form
      onSubmit={(event) => void submit(event)}
      className="mt-6 max-w-[420px]"
    >
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
          className={`${field} w-32 flex-none tabular-nums`}
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

/** Pick an open slot, add an optional note, then pay on Stripe Checkout. */
export function BookForm({
  slots,
  rateCents,
}: {
  slots: OpenSlot[];
  rateCents: number;
}) {
  const ready = useInBrowser();
  const [slotId, setSlotId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!slots.length) {
    return (
      <p className="text-[16px] leading-6 text-ink-2">
        No open times right now. Coaches add times each week, so check back
        soon.
      </p>
    );
  }

  const days: { key: string; first: string; slots: OpenSlot[] }[] = [];
  for (const slot of [...slots].sort((a, b) =>
    a.starts_at.localeCompare(b.starts_at),
  )) {
    const key = ready ? dayKey(slot.starts_at) : slot.starts_at.slice(0, 10);
    const day = days.at(-1);
    if (day?.key === key) day.slots.push(slot);
    else days.push({ key, first: slot.starts_at, slots: [slot] });
  }
  const chosen = slots.find((slot) => slot.id === slotId) ?? null;
  const price = chosen
    ? Math.round(
        (rateCents * minutesBetween(chosen.starts_at, chosen.ends_at)) / 60,
      )
    : null;

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
    setError(
      reply.status === 409
        ? "Someone else is booking that time. Pick another one."
        : reply.status === 403
          ? "This coach isn't taking bookings right now."
          : reply.status === 0
            ? OFFLINE
            : "The booking didn't start. You weren't charged. Try again.",
    );
  }

  return (
    <form onSubmit={(event) => void book(event)} className="space-y-6">
      <fieldset disabled={busy}>
        <legend className="sr-only">Choose a time</legend>
        <div className="space-y-5">
          {days.map((day) => (
            <div key={day.key}>
              <p className="text-[15px] font-semibold text-ink-2">
                {ready ? dayLabel(day.first) : " "}
              </p>
              <ul className="mt-2 grid grid-cols-1 gap-2 min-[420px]:grid-cols-2">
                {day.slots.map((slot) => (
                  <li key={slot.id}>
                    <label
                      className={`flex min-h-14 cursor-pointer flex-col justify-center rounded-lg border border-control-border bg-surface px-4 py-2 transition-colors duration-150 ease-out hover:bg-surface-subtle has-[:checked]:border-ink has-[:checked]:bg-ink has-[:checked]:text-paper has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus`}
                    >
                      <input
                        type="radio"
                        name="slot"
                        value={slot.id}
                        checked={slotId === slot.id}
                        onChange={() => setSlotId(slot.id)}
                        className="sr-only"
                      />
                      <span className="text-[16px] font-semibold tabular-nums">
                        {ready
                          ? `${timeLabel(slot.starts_at)} to ${timeLabel(slot.ends_at)}`
                          : " "}
                      </span>
                      <span className="text-[14px] leading-5 opacity-80">
                        {minutesBetween(slot.starts_at, slot.ends_at)} min,{" "}
                        {formatLabel[slot.format]}
                        {slot.venue ? `, ${slot.venue}` : ""}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </fieldset>

      <div className="space-y-2">
        <label htmlFor="booking-note" className={label}>
          Note for the coach{" "}
          <span className="font-normal text-muted">(optional)</span>
        </label>
        <textarea
          id="booking-note"
          value={note}
          maxLength={280}
          rows={3}
          disabled={busy}
          onChange={(event) => setNote(event.target.value)}
          aria-describedby="booking-note-hint"
          className={`${field} py-2 leading-6`}
        />
        <p id="booking-note-hint" className={hint}>
          What you&apos;d like to work on. Don&apos;t include phone numbers or
          addresses. {280 - note.length} characters left.
        </p>
      </div>

      {error ? (
        <p role="alert" className={errorBox}>
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="submit"
          disabled={!chosen || busy}
          className={primaryButton}
        >
          {busy
            ? "Opening checkout…"
            : price === null
              ? "Book and pay"
              : `Book and pay ${dollars(price)}`}
        </button>
        <p className={hint}>
          You pay on Stripe. Test mode: use a Stripe test card, no real charge.
        </p>
      </div>
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
