import { Check, FileText } from "lucide-react";
import type { ReactNode } from "react";
import { When } from "../client";
import {
  bookingStatusLabel,
  dollars,
  formatLabel,
  minutesBetween,
} from "../format";
import { adultOnly } from "../gate";
import { read } from "../server";
import type { CoachBooking, CoachProfile, CoachSlot } from "../types";
import {
  emptyBox,
  errorBox,
  lead,
  pageTitle,
  panel,
  sectionTitle,
} from "../ui";
import {
  CancelSlot,
  DocumentUpload,
  ProfileForm,
  SlotForm,
  StripeButton,
  SubmitForReview,
} from "./forms";

type StepState = "done" | "current" | "todo";

const STEPS = [
  ["profile", "Your profile"],
  ["document", "Background check"],
  ["review", "Review by Shoulder"],
  ["payouts", "Payouts"],
  ["slots", "Open times"],
  ["bookings", "Bookings"],
] as const;
type Step = (typeof STEPS)[number][0];

function currentStep(profile: CoachProfile | null, hasDoc: boolean): Step {
  if (!profile) return "profile";
  if (profile.status === "draft" || profile.status === "rejected")
    return hasDoc ? "review" : "document";
  if (profile.status !== "verified") return "review";
  if (!profile.charges_enabled) return "payouts";
  return "slots";
}

function Section({
  id,
  title,
  state,
  children,
}: {
  id: Step;
  title: string;
  state: StepState;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="scroll-mt-40 border-t border-line py-8 first:border-t-0 first:pt-0"
    >
      <h2
        id={`${id}-title`}
        className={`${sectionTitle} flex items-center gap-3`}
      >
        {title}
        {state === "done" ? (
          <span className="inline-flex min-h-7 items-center gap-1 rounded-full bg-action-soft px-2.5 text-[13px] font-semibold text-ink">
            <Check size={14} strokeWidth={2.5} aria-hidden="true" />
            Done
          </span>
        ) : null}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function StatusPanel({ profile }: { profile: CoachProfile }) {
  const copy: Record<CoachProfile["status"], [string, string]> = {
    draft: [
      "Not sent yet",
      "Upload your background-check document, then send your profile for review.",
    ],
    pending_review: [
      "Waiting for review",
      "The Shoulder team is checking your document. This usually takes a few days. You'll see the result here.",
    ],
    rejected: [
      "Changes needed",
      "Your profile wasn't approved yet. Read the note, fix what it asks, then send it again.",
    ],
    verified: [
      "Verified",
      "Your background check is confirmed. Players can find you once payouts are set up and you add open times.",
    ],
    suspended: [
      "Paused",
      "Your listing is hidden and new bookings are off while the Shoulder team looks into something. Existing bookings are unchanged unless we contact you.",
    ],
  };
  const [heading, body] = copy[profile.status];
  return (
    <div className={`${panel} p-5`} role="status">
      <p className="text-[17px] font-semibold">{heading}</p>
      <p className="mt-1 max-w-[60ch] text-[16px] leading-6 text-ink-2">
        {body}
      </p>
      {profile.review_note &&
      (profile.status === "rejected" || profile.status === "suspended") ? (
        <blockquote className="mt-4 rounded-lg bg-surface-subtle p-4 text-[16px] leading-6">
          <p className="text-[13px] font-semibold text-muted">
            Note from the Shoulder team
          </p>
          <p className="mt-1 whitespace-pre-line">{profile.review_note}</p>
        </blockquote>
      ) : null}
    </div>
  );
}

export default async function CoachOnboardingPage() {
  const gate = await adultOnly("/coaching/coach");
  if (!gate.token) return gate.blocked;
  const token = gate.token;
  const reply = await read<CoachProfile>(token, "/v1/coach-profile");
  const failed = reply.data === null && reply.status !== 404;
  const profile = reply.data;
  const docs = profile?.documents ?? [];
  const hasDoc = docs.some(
    (d) => d.kind === "background_check" && d.status === "ready",
  );
  const step = currentStep(profile, hasDoc);
  const index = STEPS.findIndex(([key]) => key === step);
  const stateOf = (key: Step): StepState => {
    const at = STEPS.findIndex(([k]) => k === key);
    if (key === "bookings" && step === "slots") return "current";
    return at < index ? "done" : at === index ? "current" : "todo";
  };
  const live = profile?.status === "verified" && profile.charges_enabled;
  const [slots, bookings] = live
    ? await Promise.all([
        read<CoachSlot[]>(token, "/v1/coach-profile/slots"),
        read<CoachBooking[]>(token, "/v1/coach-profile/bookings"),
      ])
    : [null, null];

  return (
    <div>
      <h1 className={pageTitle}>Coach on Shoulder</h1>
      <p className={`${lead} mt-3`}>
        Offer paid 1:1 sessions to adult players. Players only see you after the
        Shoulder team checks your background-check document and you set up
        payouts. During the pilot, payments run in Stripe test mode.
      </p>

      {failed ? (
        <p role="alert" className={`${errorBox} mt-8 max-w-[560px]`}>
          Your coach profile couldn&apos;t load. Try again in a moment.
        </p>
      ) : (
        <div className="mt-10 grid gap-10 lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-14">
          <nav
            aria-label="Setup steps"
            className="lg:sticky lg:top-40 lg:self-start"
          >
            <ol className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:gap-0 lg:overflow-visible">
              {STEPS.map(([key, name], i) => {
                const state = stateOf(key);
                return (
                  <li key={key} className="shrink-0">
                    <a
                      href={`#${key}`}
                      aria-current={state === "current" ? "step" : undefined}
                      className={`flex min-h-11 items-center gap-3 rounded-lg px-2 text-[15px] outline-none hover:bg-surface-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${
                        state === "current"
                          ? "font-semibold text-ink"
                          : state === "done"
                            ? "text-ink-2"
                            : "text-muted"
                      }`}
                    >
                      <span
                        aria-hidden="true"
                        className={`flex size-7 shrink-0 items-center justify-center rounded-full border text-[13px] font-semibold tabular-nums ${
                          state === "done"
                            ? "border-ink bg-ink text-paper"
                            : state === "current"
                              ? "border-action text-action"
                              : "border-control-border"
                        }`}
                      >
                        {state === "done" ? (
                          <Check size={14} strokeWidth={2.5} />
                        ) : (
                          i + 1
                        )}
                      </span>
                      <span className="whitespace-nowrap">
                        {name}
                        <span className="sr-only">
                          {state === "done"
                            ? " (done)"
                            : state === "current"
                              ? " (current step)"
                              : ""}
                        </span>
                      </span>
                    </a>
                  </li>
                );
              })}
            </ol>
          </nav>

          <div className="min-w-0 max-w-[720px]">
            <Section
              id="profile"
              title="Your profile"
              state={stateOf("profile")}
            >
              <ProfileForm profile={profile} />
            </Section>

            <Section
              id="document"
              title="Background check"
              state={stateOf("document")}
            >
              {profile ? (
                <>
                  <p className="mb-4 max-w-[60ch] text-[16px] leading-6 text-ink-2">
                    Upload the certificate from your background-check provider.
                    Only the Shoulder team sees it. It&apos;s never shown to
                    players.
                  </p>
                  {docs.length ? (
                    <ul className="mb-5 space-y-2">
                      {docs.map((d) => (
                        <li
                          key={d.id}
                          className="flex items-center gap-3 text-[15px]"
                        >
                          <FileText
                            size={18}
                            strokeWidth={2}
                            aria-hidden="true"
                            className="text-muted"
                          />
                          <span>
                            {d.kind === "background_check"
                              ? "Background check"
                              : d.kind === "id"
                                ? "ID"
                                : "Certification"}
                            <span className="text-muted">
                              {", "}
                              {d.status === "ready"
                                ? "uploaded"
                                : "upload not finished"}
                            </span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {profile.status === "draft" ||
                  profile.status === "rejected" ? (
                    <DocumentUpload />
                  ) : null}
                </>
              ) : (
                <p className="text-[16px] text-muted">
                  Save your profile first.
                </p>
              )}
            </Section>

            <Section
              id="review"
              title="Review by Shoulder"
              state={stateOf("review")}
            >
              {profile ? (
                <div className="space-y-4">
                  <StatusPanel profile={profile} />
                  {(profile.status === "draft" ||
                    profile.status === "rejected") &&
                  hasDoc ? (
                    <SubmitForReview />
                  ) : null}
                </div>
              ) : (
                <p className="text-[16px] text-muted">
                  Save your profile first.
                </p>
              )}
            </Section>

            <Section id="payouts" title="Payouts" state={stateOf("payouts")}>
              {profile?.status === "verified" ? (
                profile.charges_enabled ? (
                  <p className="text-[16px] leading-6 text-ink-2">
                    Stripe is set up. Payments go to your Stripe account, minus
                    Shoulder&apos;s 10%.
                  </p>
                ) : (
                  <div className="space-y-3">
                    <p className="max-w-[60ch] text-[16px] leading-6 text-ink-2">
                      Stripe handles identity and tax details for payouts. You
                      leave Shoulder to finish it, then come back here. In test
                      mode, use Stripe&apos;s test details.
                    </p>
                    <StripeButton />
                  </div>
                )
              ) : (
                <p className="text-[16px] text-muted">
                  Available once you&apos;re verified.
                </p>
              )}
            </Section>

            <Section id="slots" title="Open times" state={stateOf("slots")}>
              {live && profile ? (
                <div className="space-y-8">
                  <SlotForm formats={profile.formats} />
                  {slots?.data === null ? (
                    <p role="alert" className={errorBox}>
                      Your times couldn&apos;t load. Try again in a moment.
                    </p>
                  ) : (
                    <SlotList slots={slots?.data ?? []} />
                  )}
                </div>
              ) : (
                <p className="text-[16px] text-muted">
                  Available once payouts are set up.
                </p>
              )}
            </Section>

            <Section id="bookings" title="Bookings" state={stateOf("bookings")}>
              {live ? (
                bookings?.data === null ? (
                  <p role="alert" className={errorBox}>
                    Your bookings couldn&apos;t load. Try again in a moment.
                  </p>
                ) : (
                  <BookingList bookings={bookings?.data ?? []} />
                )
              ) : (
                <p className="text-[16px] text-muted">
                  Bookings show here once players can find you.
                </p>
              )}
            </Section>
          </div>
        </div>
      )}
    </div>
  );
}

function SlotList({ slots }: { slots: CoachSlot[] }) {
  const shown = slots
    .filter((s) => s.status !== "cancelled")
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  if (!shown.length)
    return (
      <div className={emptyBox}>
        <p className="text-[16px] font-semibold">No open times yet.</p>
        <p className="mt-1 text-[16px] leading-6 text-ink-2">
          Add a time above and players can book it.
        </p>
      </div>
    );
  return (
    <ul className="divide-y divide-line border-y border-line">
      {shown.map((slot) => (
        <li
          key={slot.id}
          className="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
        >
          <div className="min-w-0">
            <When
              iso={slot.starts_at}
              className="block text-[16px] font-semibold tabular-nums"
            />
            <p className="text-[15px] leading-6 text-ink-2">
              {minutesBetween(slot.starts_at, slot.ends_at)} min,{" "}
              {formatLabel[slot.format]}
              {slot.venue ? `, ${slot.venue}` : ""}
            </p>
            <p className="text-[14px] text-muted">
              {slot.status === "open"
                ? "Open"
                : slot.status === "held"
                  ? "Someone is paying now"
                  : "Booked"}
            </p>
          </div>
          {slot.status !== "held" ? (
            <CancelSlot id={slot.id} booked={slot.status === "booked"} />
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function BookingList({ bookings }: { bookings: CoachBooking[] }) {
  if (!bookings.length)
    return (
      <div className={emptyBox}>
        <p className="text-[16px] font-semibold">No bookings yet.</p>
        <p className="mt-1 text-[16px] leading-6 text-ink-2">
          When a player books and pays, it shows here.
        </p>
      </div>
    );
  return (
    <ul className="divide-y divide-line border-y border-line">
      {[...bookings]
        .sort((a, b) => b.starts_at.localeCompare(a.starts_at))
        .map((b) => (
          <li key={b.id} className="py-4">
            <When
              iso={b.starts_at}
              className="block text-[16px] font-semibold tabular-nums"
            />
            <p className="text-[16px] leading-6">
              {b.player_first_name}
              <span className="text-ink-2">
                {", "}
                {formatLabel[b.format]}
                {b.venue ? `, ${b.venue}` : ""}
              </span>
            </p>
            <p className="text-[14px] text-muted tabular-nums">
              {bookingStatusLabel[b.status].replace(
                "You cancelled",
                "Player cancelled",
              )}
              , {dollars(b.price_cents - b.platform_fee_cents)} to you after the
              10% fee
            </p>
            {b.note ? (
              <p className="mt-1 max-w-[60ch] text-[15px] leading-6 text-ink-2">
                Note: {b.note}
              </p>
            ) : null}
          </li>
        ))}
    </ul>
  );
}
