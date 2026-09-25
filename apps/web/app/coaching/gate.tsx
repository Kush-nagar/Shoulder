import { AgeForm } from "./forms";
import { hasGoogleIdentity, readAge, requireSignedIn } from "./server";
import { errorBox, hint, lead, pageTitle, panel, secondaryButton } from "./ui";

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
            <p role="status" className={`${errorBox} mt-6 max-w-[560px]`}>
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
          <p role="alert" className={`${errorBox} mt-6 max-w-[560px]`}>
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
        <p className={`${lead} mt-4`}>
          Book a paid 1:1 session with an independent coach. First, confirm
          you&apos;re 18 or older.
        </p>
        {notice ? (
          <p role="status" className={`${errorBox} mt-6 max-w-[560px]`}>
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
    <form
      action="/auth/google"
      method="post"
      data-web-only=""
      className="mt-6 max-w-[420px] border-t border-line pt-6"
    >
      <input type="hidden" name="purpose" value="birthday" />
      <button type="submit" className={secondaryButton}>
        Use my Google birthday
      </button>
      <p className={`${hint} mt-2`}>
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
    <div className="grid gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-16">
      <div>
        <h1 className={pageTitle}>{title}</h1>
        {children}
      </div>
      <section aria-labelledby="pilot-title" className={`${panel} p-5 md:p-6`}>
        <h2 id="pilot-title" className="text-[17px] font-semibold">
          Why 18 and over
        </h2>
        <ul className="mt-3 space-y-3">
          {reasons.map((line) => (
            <li
              key={line}
              className="border-l-2 border-line-strong pl-4 text-[16px] leading-6 text-ink-2"
            >
              {line}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
