import { Cake, ChevronDown, UserRoundCheck } from "lucide-react";
import { AgeForm } from "./forms";
import { hasGoogleIdentity, readAge, requireSignedIn } from "./server";
import { errorBox, focus, hint, lead, pageTitle, secondaryButton } from "./ui";

/** Messages after the optional Google birthday flow (`/coaching?birthday=`). */
const birthdayNotices: Record<string, string> = {
  none: "Google didn't share a birth year. Enter it below instead.",
  refused:
    "Your Google birth year can't be saved: a birth year can't be changed to a later one once it's recorded.",
  error:
    "Your Google birthday couldn't be checked. Enter your birth year below.",
};

const reasons = [
  "Paid sessions with independent coaches are new to Shoulder. We're testing them with adults first.",
  "Players under 18 need a parent or guardian involved in every booking and message. That isn't built yet, so under-18 accounts can't browse or book.",
  "Coaches are listed only after the Shoulder team checks their background-check document.",
  "Payments run in Stripe test mode during the pilot. No real money moves.",
];

/**
 * Signed-in token for an attested adult, or the page to show instead: the
 * birth-year form, the under-18 explanation, or an error.
 */
export async function adultOnly(
  destination: string,
  birthday?: string,
): Promise<
  { token: string; blocked: null } | { token: null; blocked: React.ReactNode }
> {
  const token = await requireSignedIn(destination);
  const age = await readAge(token);
  if (age.data?.adult) return { token, blocked: null };
  const notice = birthday ? birthdayNotices[birthday] : undefined;
  if (age.data) {
    return {
      token: null,
      blocked: (
        <Intro title="Coaching is for adults for now">
          {notice ? (
            <p role="status" className={`${errorBox} mt-5`}>
              {notice}
            </p>
          ) : null}
          <p className={`${lead} mt-4`}>
            Your account says you&apos;re under 18, so you can&apos;t browse or
            book coaches in this pilot. Your team coach and your clips on
            Shoulder are unchanged.
          </p>
        </Intro>
      ),
    };
  }
  if (age.status !== 404) {
    return {
      token: null,
      blocked: (
        <Intro title="Train with a coach">
          <p role="alert" className={`${errorBox} mt-5`}>
            Coaching couldn&apos;t load. Try again in a moment.
          </p>
        </Intro>
      ),
    };
  }
  return {
    token: null,
    blocked: (
      <Intro title="Train with a coach">
        <p className={`${lead} mt-2`}>
          Coaching is an adults-only pilot for now, so confirm your birth year
          once to browse and book.
        </p>
        {notice ? (
          <p role="status" className={`${errorBox} mt-5`}>
            {notice}
          </p>
        ) : null}
        <AgeForm />
        {hasGoogleIdentity(token) ? <GoogleBirthday /> : null}
      </Intro>
    ),
  };
}

/**
 * Optional: a separate Google consent for the birthday scope. Only the year is
 * kept. Hidden inside the Capacitor app, where Google runs outside the page.
 */
function GoogleBirthday() {
  return (
    <form action="/auth/google" method="post" data-web-only="" className="mt-5">
      <p
        aria-hidden="true"
        className="flex items-center gap-3 text-[13px] text-muted before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line"
      >
        or
      </p>
      <input type="hidden" name="purpose" value="birthday" />
      <button type="submit" className={`${secondaryButton} mt-4 w-full`}>
        <Cake size={18} strokeWidth={2} aria-hidden="true" />
        Use my Google birthday
      </button>
      <p className={`${hint} mt-2 text-center`}>
        Google asks you to share your birthday. Shoulder keeps only the year.
      </p>
    </form>
  );
}

function Intro({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="sh-rise mx-auto max-w-[520px] md:pt-4">
      <div className="rounded-2xl border border-line bg-surface p-5 min-[375px]:p-6 md:p-8">
        <span
          aria-hidden="true"
          className="flex size-12 items-center justify-center rounded-xl bg-action-soft text-action"
        >
          <UserRoundCheck size={24} strokeWidth={2} />
        </span>
        <h1 className={`${pageTitle} mt-5`}>{title}</h1>
        {children}
      </div>
      <details className="group mt-4 rounded-xl px-1">
        <summary
          className={`flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg px-2 text-[15px] font-semibold text-ink-2 hover:text-ink [&::-webkit-details-marker]:hidden ${focus}`}
        >
          <ChevronDown
            size={18}
            strokeWidth={2}
            aria-hidden="true"
            className="transition-transform duration-200 group-open:rotate-180 motion-reduce:transition-none"
          />
          Why 18 and over
        </summary>
        <ul className="mt-2 space-y-3 px-2 pb-2">
          {reasons.map((line) => (
            <li
              key={line}
              className="border-l-2 border-line-strong pl-4 text-[15px] leading-6 text-ink-2"
            >
              {line}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
