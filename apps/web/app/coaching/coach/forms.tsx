"use client";

import { ExternalLink, FileUp, Send, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";
import { formatBytes } from "../../../lib/upload";
import { dayKey, dayParts, send, timeLabel, useInBrowser } from "../client";
import {
  formatLabel,
  minutesBetween,
  specialtyLabel,
  stripeUrl,
} from "../format";
import {
  type CoachProfile,
  type CoachSlot,
  type DocumentUploadStart,
  FORMATS,
  type Format,
  SPECIALTIES,
  type Specialty,
  type StripeOnboarding,
} from "../types";
import {
  errorBox,
  field,
  fieldError,
  hint,
  label,
  primaryButton,
  quietDanger,
  secondaryButton,
  toggleChip,
} from "../ui";

const OFFLINE =
  "Shoulder couldn't be reached. Check your connection and try again.";
const ok = (status: number) => status >= 200 && status < 300;

export function ProfileForm({ profile }: { profile: CoachProfile | null }) {
  const router = useRouter();
  const [name, setName] = useState(profile?.display_name ?? "");
  const [city, setCity] = useState(profile?.city ?? "");
  const [bio, setBio] = useState(profile?.bio ?? "");
  const [rate, setRate] = useState(
    profile ? String(Math.round(profile.rate_cents / 100)) : "",
  );
  const [specialties, setSpecialties] = useState<Specialty[]>(
    profile?.specialties ?? [],
  );
  const [formats, setFormats] = useState<Format[]>(profile?.formats ?? []);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value)
      ? list.filter((v) => v !== value)
      : [...list, value];
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!specialties.length || !formats.length) {
      setMessage({
        ok: false,
        text: "Pick at least one specialty and one session type.",
      });
      return;
    }
    setBusy(true);
    setMessage(null);
    const reply = await send("/api/coaching/coach-profile", "PUT", {
      display_name: name.trim(),
      city: city.trim(),
      bio: bio.trim(),
      rate_cents: Math.round(Number(rate) * 100),
      specialties,
      formats,
    });
    setBusy(false);
    if (ok(reply.status)) {
      setMessage({ ok: true, text: "Profile saved." });
      router.refresh();
    } else
      setMessage({
        ok: false,
        text:
          reply.status === 422
            ? "Some details aren't accepted. Check each field's limits and try again."
            : reply.status === 0
              ? OFFLINE
              : "Nothing was saved. Try again.",
      });
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-7">
      <fieldset disabled={busy} className="space-y-7">
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2">
            <label htmlFor="coach-name" className={label}>
              Name shown to players
            </label>
            <input
              id="coach-name"
              value={name}
              required
              minLength={2}
              maxLength={60}
              autoComplete="name"
              onChange={(e) => setName(e.target.value)}
              className={field}
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="coach-city" className={label}>
              City
            </label>
            <input
              id="coach-city"
              value={city}
              required
              minLength={2}
              maxLength={80}
              autoComplete="address-level2"
              onChange={(e) => setCity(e.target.value)}
              className={field}
            />
          </div>
        </div>

        <fieldset>
          <legend className={label}>Specialties</legend>
          <p className={`${hint} mt-1`}>Pick 1 to 5.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {SPECIALTIES.map((s) => (
              <label key={s} className={toggleChip}>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={specialties.includes(s)}
                  disabled={!specialties.includes(s) && specialties.length >= 5}
                  onChange={() => setSpecialties(toggle(specialties, s))}
                />
                {specialtyLabel[s]}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-5 sm:grid-cols-2">
          <fieldset>
            <legend className={label}>Session types</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {FORMATS.map((f) => (
                <label key={f} className={toggleChip}>
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={formats.includes(f)}
                    onChange={() => setFormats(toggle(formats, f))}
                  />
                  {formatLabel[f]}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="space-y-2">
            <label htmlFor="coach-rate" className={label}>
              Rate per hour, in US dollars
            </label>
            <div className="relative w-40">
              <span
                aria-hidden="true"
                className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-[16px] text-muted"
              >
                $
              </span>
              <input
                id="coach-rate"
                type="number"
                inputMode="numeric"
                min={10}
                max={500}
                step={1}
                required
                value={rate}
                onChange={(e) => setRate(e.target.value)}
                aria-describedby="coach-rate-hint"
                className={`${field} pl-7 tabular-nums`}
              />
            </div>
            <p id="coach-rate-hint" className={hint}>
              $10 to $500. Shoulder keeps 10%.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          <label htmlFor="coach-bio" className={label}>
            About you
          </label>
          <textarea
            id="coach-bio"
            value={bio}
            maxLength={600}
            rows={5}
            required
            onChange={(e) => setBio(e.target.value)}
            aria-describedby="coach-bio-hint"
            className={`${field} py-2 leading-6`}
          />
          <p id="coach-bio-hint" className={`${hint} tabular-nums`}>
            Your coaching experience and how you run a session. No phone
            numbers, emails or social handles. {600 - bio.length} characters
            left.
          </p>
        </div>
      </fieldset>

      {profile?.status === "verified" ? (
        <p className={hint}>
          Changing your rate, specialties or bio sends your profile back for a
          quick review. You&apos;re hidden from players until it&apos;s done.
        </p>
      ) : null}
      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={message.ok ? "text-[16px] font-semibold" : fieldError}
        >
          {message.text}
        </p>
      ) : null}
      <button type="submit" disabled={busy} className={primaryButton}>
        {busy ? "Saving…" : profile ? "Save profile" : "Create profile"}
      </button>
    </form>
  );
}

const DOC_TYPES = new Set(["application/pdf", "image/jpeg", "image/png"]);
const DOC_MAX = 10 * 1024 * 1024;

function put(
  url: string,
  file: File,
  onProgress: (loaded: number) => void,
): Promise<void> {
  // XHR, not fetch: fetch cannot report upload progress.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", file.type);
    xhr.upload.onprogress = (event) => onProgress(event.loaded);
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error("put"));
    xhr.onerror = () => reject(new Error("put"));
    xhr.send(file);
  });
}

/** Background-check certificate: presigned PUT, then a HEAD-verified complete. */
export function DocumentUpload() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [loaded, setLoaded] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function choose(picked: File | undefined) {
    setError(null);
    setFile(null);
    if (!picked) return;
    if (!DOC_TYPES.has(picked.type)) {
      setError("Choose a PDF, JPEG or PNG file.");
      return;
    }
    if (picked.size < 1 || picked.size > DOC_MAX) {
      setError("This file is over 10 MB. Save a smaller copy and try again.");
      return;
    }
    setFile(picked);
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setLoaded(0);
    try {
      const start = await send<DocumentUploadStart>(
        "/api/coaching/coach-profile/documents",
        "POST",
        {
          kind: "background_check",
          content_type: file.type,
          size_bytes: file.size,
        },
      );
      if (!ok(start.status) || !start.data) throw new Error("start");
      await put(start.data.upload_url, file, setLoaded);
      const done = await send(
        `/api/coaching/coach-profile/documents/${start.data.id}/complete`,
        "POST",
      );
      if (!ok(done.status)) throw new Error("complete");
      setFile(null);
      if (input.current) input.current.value = "";
      router.refresh();
    } catch {
      setError("The upload stopped. Nothing was sent for review. Try again.");
    }
    setBusy(false);
  }

  const percent = file ? Math.round((loaded / file.size) * 100) : 0;
  return (
    <form onSubmit={(event) => void upload(event)} className="space-y-4">
      <div className="rounded-xl border border-line p-4 md:p-5">
        <label className="relative inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-control-border bg-surface px-4 text-[16px] font-semibold transition-[background-color,transform] duration-150 ease-out hover:bg-surface-subtle active:scale-[0.98] has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-45 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus">
          <FileUp size={20} strokeWidth={2} aria-hidden="true" />
          Choose a file
          <input
            ref={input}
            type="file"
            accept="application/pdf,image/jpeg,image/png"
            disabled={busy}
            className="sr-only"
            onChange={(e) => choose(e.target.files?.[0])}
          />
        </label>
        <p className={`${hint} mt-3`}>PDF, JPEG or PNG. Up to 10 MB.</p>
        {file ? (
          <p className="mt-3 rounded-lg bg-surface-subtle px-4 py-3 text-[15px] leading-6">
            <span className="block truncate font-semibold">{file.name}</span>
            <span className="text-muted tabular-nums">
              {formatBytes(file.size)}
            </span>
          </p>
        ) : null}
      </div>
      {busy ? (
        <div aria-live="polite" className="space-y-2">
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="h-2 overflow-hidden rounded-full bg-surface-subtle"
          >
            <div
              className="h-full origin-left rounded-full bg-action transition-transform duration-200 ease-out motion-reduce:transition-none"
              style={{ transform: `scaleX(${percent / 100})` }}
            />
          </div>
          <p className="text-[15px] text-ink-2 tabular-nums">
            Uploading {formatBytes(loaded)} of {formatBytes(file?.size ?? 0)}.
          </p>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className={errorBox}>
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={!file || busy} className={primaryButton}>
        {busy ? "Uploading…" : "Upload document"}
      </button>
    </form>
  );
}

/** One POST, then refresh. Used for submit-for-review. */
export function SubmitForReview() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit() {
    setBusy(true);
    setError(null);
    const reply = await send("/api/coaching/coach-profile/submit", "POST");
    setBusy(false);
    if (ok(reply.status)) router.refresh();
    else
      setError(
        reply.status === 409 || reply.status === 422
          ? "Upload your background-check document first."
          : reply.status === 0
            ? OFFLINE
            : "It wasn't sent. Try again.",
      );
  }
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => void submit()}
        disabled={busy}
        className={primaryButton}
      >
        <Send size={18} strokeWidth={2} aria-hidden="true" />
        {busy ? "Sending…" : "Send for review"}
      </button>
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function StripeButton() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function start() {
    setBusy(true);
    setError(null);
    const reply = await send<StripeOnboarding>(
      "/api/coaching/coach-profile/stripe",
      "POST",
    );
    const target = stripeUrl(reply.data?.url);
    if (ok(reply.status) && target) {
      window.location.assign(target);
      return;
    }
    setBusy(false);
    setError(reply.status === 0 ? OFFLINE : "Stripe didn't open. Try again.");
  }
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => void start()}
        disabled={busy}
        className={primaryButton}
      >
        <ExternalLink size={18} strokeWidth={2} aria-hidden="true" />
        {busy ? "Opening Stripe…" : "Set up payouts with Stripe"}
      </button>
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

const DURATIONS = [30, 45, 60, 75, 90, 120, 150, 180];

export function SlotForm({ formats }: { formats: Format[] }) {
  const router = useRouter();
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [format, setFormat] = useState<Format>(formats[0] ?? "in_person");
  const [venue, setVenue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const start = new Date(`${date}T${time}`);
    if (Number.isNaN(start.getTime()) || start.getTime() <= Date.now()) {
      setError("Pick a date and time in the future.");
      return;
    }
    setBusy(true);
    setError(null);
    const reply = await send("/api/coaching/coach-profile/slots", "POST", {
      starts_at: start.toISOString(),
      ends_at: new Date(start.getTime() + minutes * 60000).toISOString(),
      format,
      venue: format === "in_person" ? venue.trim() : null,
    });
    setBusy(false);
    if (ok(reply.status)) {
      setTime("");
      router.refresh();
    } else
      setError(
        reply.status === 409
          ? "That overlaps a time you already have."
          : reply.status === 422
            ? "That time isn't accepted. Check the details and try again."
            : reply.status === 0
              ? OFFLINE
              : "The time wasn't added. Try again.",
      );
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-5">
      <fieldset disabled={busy} className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <label htmlFor="slot-date" className={label}>
              Date
            </label>
            <input
              id="slot-date"
              type="date"
              required
              min={today}
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={field}
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="slot-time" className={label}>
              Start
            </label>
            <input
              id="slot-time"
              type="time"
              required
              step={900}
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className={field}
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="slot-length" className={label}>
              Length
            </label>
            <select
              id="slot-length"
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value))}
              className={field}
            >
              {DURATIONS.map((m) => (
                <option key={m} value={m}>
                  {m < 60
                    ? `${m} min`
                    : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`}
                </option>
              ))}
            </select>
          </div>
        </div>
        {formats.length > 1 ? (
          <fieldset>
            <legend className={label}>Session type</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {formats.map((f) => (
                <label key={f} className={toggleChip}>
                  <input
                    type="radio"
                    name="slot-format"
                    className="sr-only"
                    checked={format === f}
                    onChange={() => setFormat(f)}
                  />
                  {formatLabel[f]}
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
        {format === "in_person" ? (
          <div className="space-y-2">
            <label htmlFor="slot-venue" className={label}>
              Public venue
            </label>
            <input
              id="slot-venue"
              required
              maxLength={120}
              value={venue}
              onChange={(e) => setVenue(e.target.value)}
              aria-describedby="slot-venue-hint"
              className={field}
            />
            <p id="slot-venue-hint" className={hint}>
              A public place players can find, like a park field or sports
              centre. Never a home address.
            </p>
          </div>
        ) : null}
      </fieldset>
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={busy} className={primaryButton}>
        {busy ? "Adding…" : "Add time"}
      </button>
    </form>
  );
}

export function CancelSlot({ id, booked }: { id: string; booked: boolean }) {
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function cancel() {
    setBusy(true);
    setError(null);
    const reply = await send(
      `/api/coaching/coach-profile/slots/${id}`,
      "DELETE",
    );
    setBusy(false);
    if (ok(reply.status)) router.refresh();
    else setError(reply.status === 0 ? OFFLINE : "Still on. Try again.");
  }
  if (!confirm)
    return (
      <button
        type="button"
        onClick={() => setConfirm(true)}
        className={quietDanger}
      >
        <X size={18} strokeWidth={2} aria-hidden="true" />
        Cancel
      </button>
    );
  return (
    <div
      role="alertdialog"
      aria-label="Cancel this time?"
      className="space-y-2"
    >
      <p className="text-[15px] leading-6 text-ink-2">
        {booked
          ? "A player has booked this. They get a full refund."
          : "It's removed from your open times."}
      </p>
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void cancel()}
          disabled={busy}
          className={secondaryButton}
        >
          {busy ? "Cancelling…" : booked ? "Cancel and refund" : "Cancel time"}
        </button>
        <button
          type="button"
          onClick={() => setConfirm(false)}
          disabled={busy}
          className={primaryButton}
        >
          Keep it
        </button>
      </div>
    </div>
  );
}

const slotState: Record<CoachSlot["status"], [string, string]> = {
  open: ["Open", "border border-control-border text-ink-2"],
  held: ["Someone is paying now", "bg-surface-subtle text-ink-2"],
  booked: ["Booked", "bg-action-soft text-ink"],
  cancelled: ["Cancelled", "bg-surface-subtle text-muted"],
};

/** Open times as a day-by-day agenda: a date tile, then that day's times. */
export function SlotAgenda({ slots }: { slots: CoachSlot[] }) {
  const ready = useInBrowser();
  const shown = slots
    .filter((s) => s.status !== "cancelled")
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  if (!shown.length)
    return (
      <div className="rounded-xl border border-line px-5 py-8">
        <p className="text-[16px] font-semibold">No open times yet.</p>
        <p className="mt-1 text-[16px] leading-6 text-ink-2">
          Add a time above and players can book it.
        </p>
      </div>
    );
  const days: { key: string; first: string; slots: CoachSlot[] }[] = [];
  for (const slot of shown) {
    const key = ready ? dayKey(slot.starts_at) : slot.starts_at.slice(0, 10);
    const last = days.at(-1);
    if (last?.key === key) last.slots.push(slot);
    else days.push({ key, first: slot.starts_at, slots: [slot] });
  }
  return (
    <ol className="space-y-3">
      {days.map((day) => {
        const parts = ready ? dayParts(day.first) : null;
        return (
          <li
            key={day.key}
            className="grid grid-cols-[56px_minmax(0,1fr)] gap-4 rounded-xl border border-line p-3 md:p-4"
          >
            <span
              aria-hidden="true"
              className="flex h-16 flex-col items-center justify-center rounded-lg bg-surface-subtle"
            >
              <span className="text-[12px] font-semibold text-ink-2">
                {parts?.weekday ?? " "}
              </span>
              <span className="font-display text-[24px] leading-none tabular-nums">
                {parts?.day ?? " "}
              </span>
              <span className="text-[11px] text-muted">
                {parts?.month ?? " "}
              </span>
            </span>
            <ul className="min-w-0 divide-y divide-line">
              {day.slots.map((slot) => {
                const [label, tone] = slotState[slot.status];
                return (
                  <li
                    key={slot.id}
                    className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 py-2 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2">
                        <time
                          dateTime={slot.starts_at}
                          className="text-[16px] font-semibold tabular-nums"
                        >
                          {ready
                            ? `${timeLabel(slot.starts_at)} to ${timeLabel(slot.ends_at)}`
                            : " "}
                        </time>
                        <span
                          className={`inline-flex min-h-6 items-center rounded-full px-2 text-[12px] font-semibold ${tone}`}
                        >
                          {label}
                        </span>
                      </p>
                      <p className="text-[14px] leading-6 text-ink-2">
                        {minutesBetween(slot.starts_at, slot.ends_at)} min,{" "}
                        {formatLabel[slot.format]}
                        {slot.venue ? `, ${slot.venue}` : ""}
                      </p>
                    </div>
                    {slot.status !== "held" ? (
                      <CancelSlot
                        id={slot.id}
                        booked={slot.status === "booked"}
                      />
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </li>
        );
      })}
    </ol>
  );
}
