import { Check, FileText } from "lucide-react";
import type { ReactNode } from "react";
import { When } from "../client";
import { bookingStatusLabel, dollars, formatLabel } from "../format";
import { adultOnly } from "../gate";
import { StatusChip } from "../parts";
import { read } from "../server";
import type { CoachBooking, CoachProfile, CoachSlot } from "../types";
import {
  emptyBox,
  errorBox,
  focus,
  lead,
  pageTitle,
  panel,
  sectionTitle,
} from "../ui";
import {
  DocumentUpload,
  ProfileForm,
  SlotAgenda,
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
  n,
  title,
  state,
  children,
}: {
  id: Step;
  n: number;
  title: string;
  state: StepState;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={`scroll-mt-40 rounded-2xl border p-5 md:p-6 ${
        state === "current"
          ? "border-line-strong bg-surface"
          : "border-line bg-surface"
      }`}
    >
      <h2
        id={`${id}-title`}
        className={`${sectionTitle} flex flex-wrap items-center gap-3`}
      >
        <StepDot n={n} state={state} />
        {title}
        {state === "done" ? (
          <span className="inline-flex min-h-7 items-center gap-1 rounded-full bg-action-soft px-2.5 text-[13px] font-semibold text-ink">
            <Check size={14} strokeWidth={2.5} aria-hidden="true" />
            Done
          </span>
        ) : state === "current" && id !== "bookings" ? (
          <span className="inline-flex min-h-7 items-center rounded-md border border-signal/50 px-2.5 text-[13px] font-medium text-signal">
            Next step
          </span>
        ) : null}
      </h2>
      <div className="mt-4 md:pl-11">{children}</div>
    </section>
  );
}

function StepDot({ n, state }: { n: number; state: StepState }) {
  return (
    <span
      aria-hidden="true"
      className={`flex size-8 shrink-0 items-center justify-center rounded-full border text-[14px] font-semibold tabular-nums ${
        state === "done"
          ? "border-signal bg-signal-soft text-ink"
          : state === "current"
            ? "border-action bg-action text-on-action"
            : "border-control-border text-muted"
      }`}
    >
      {state === "done" ? <Check size={15} strokeWidth={2.5} /> : n}
    </span>
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
  const done = STEPS.slice(0, -1).filter(([k]) => stateOf(k) === "done").length;
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
        <div className="mt-8 grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-12">
          <nav
            aria-label="Setup steps"
            className="lg:sticky lg:top-40 lg:self-start"
          >
            <p className="text-[14px] font-semibold text-ink-2 tabular-nums">
              {done} of {STEPS.length - 1} steps done
            </p>
            <ol
              aria-hidden="true"
              className="mt-2 grid grid-cols-5 gap-1.5 lg:hidden"
            >
              {STEPS.slice(0, -1).map(([key]) => (
                <li
                  key={key}
                  className={`h-1.5 rounded-full ${
                    stateOf(key) === "done"
                      ? "bg-ink"
                      : stateOf(key) === "current"
                        ? "bg-action"
                        : "bg-line-strong"
                  }`}
                />
              ))}
            </ol>
            <ol className="mt-3 flex gap-1 overflow-x-auto pb-1 lg:mt-4 lg:flex-col lg:gap-0 lg:overflow-visible">
              {STEPS.map(([key, name], i) => {
                const state = stateOf(key);
                return (
                  <li
                    key={key}
                    className="relative shrink-0 lg:pb-2 lg:last:pb-0 lg:[&:not(:last-child)]:before:absolute lg:[&:not(:last-child)]:before:top-10 lg:[&:not(:last-child)]:before:bottom-0 lg:[&:not(:last-child)]:before:left-[23px] lg:[&:not(:last-child)]:before:w-px lg:[&:not(:last-child)]:before:bg-line-strong"
                  >
                    <a
                      href={`#${key}`}
                      aria-current={state === "current" ? "step" : undefined}
                      className={`flex min-h-11 items-center gap-3 rounded-lg px-2 text-[15px] hover:bg-surface-subtle ${focus} ${
                        state === "current"
                          ? "font-semibold text-ink"
                          : state === "done"
                            ? "text-ink-2"
                            : "text-muted"
                      }`}
                    >
                      <StepDot n={i + 1} state={state} />
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

          <div className="sh-stagger min-w-0 max-w-[760px] space-y-4">
            <Section
              id="profile"
              n={1}
              title="Your profile"
              state={stateOf("profile")}
            >
              <ProfileForm profile={profile} />
            </Section>

            <Section
              id="document"
              n={2}
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
              n={3}
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

            <Section
              id="payouts"
              n={4}
              title="Payouts"
              state={stateOf("payouts")}
            >
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

            <Section
              id="slots"
              n={5}
              title="Open times"
              state={stateOf("slots")}
            >
              {live && profile ? (
                <div className="space-y-8">
                  <SlotForm formats={profile.formats} />
                  {slots?.data === null ? (
                    <p role="alert" className={errorBox}>
                      Your times couldn&apos;t load. Try again in a moment.
                    </p>
                  ) : (
                    <SlotAgenda slots={slots?.data ?? []} />
                  )}
                </div>
              ) : (
                <p className="text-[16px] text-muted">
                  Available once payouts are set up.
                </p>
              )}
            </Section>

            <Section
              id="bookings"
              n={6}
              title="Bookings"
              state={stateOf("bookings")}
            >
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
    <ul className="space-y-3">
      {[...bookings]
        .sort((a, b) => b.starts_at.localeCompare(a.starts_at))
        .map((b) => (
          <li key={b.id} className="rounded-xl border border-line p-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <When
                iso={b.starts_at}
                className="text-[16px] font-semibold tabular-nums"
              />
              <StatusChip
                status={b.status}
                label={bookingStatusLabel[b.status].replace(
                  "You cancelled",
                  "Player cancelled",
                )}
              />
            </div>
            <p className="mt-1 text-[16px] leading-6">
              {b.player_first_name}
              <span className="text-ink-2">
                {", "}
                {formatLabel[b.format]}
                {b.venue ? `, ${b.venue}` : ""}
              </span>
            </p>
            <p className="text-[14px] text-muted tabular-nums">
              {dollars(b.price_cents - b.platform_fee_cents)} to you after the
              10% fee
            </p>
            {b.note ? (
              <p className="mt-2 max-w-[60ch] rounded-lg bg-surface-subtle px-3 py-2 text-[15px] leading-6 text-ink-2">
                <span className="font-semibold text-ink">Note:</span> {b.note}
              </p>
            ) : null}
          </li>
        ))}
    </ul>
  );
}
