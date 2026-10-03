import type { CSSProperties } from "react";
import { ShoulderMark, ShoulderWordmark } from "../../../components/brand";
import { verifiedRedirectPath } from "../../../lib/auth/policy";
import { savedTheme, themeAttribute } from "../../../lib/theme";
import { Submit } from "./submit";

/** Google's mark, inline and decorative; the button's text is its label. */
function GoogleMark() {
  return (
    <svg className="size-5 shrink-0" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#ea4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285f4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#fbbc05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34a853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export default async function SignIn({
  searchParams,
}: {
  searchParams: Promise<{ sent?: string; error?: string; next?: string }>;
}) {
  const state = await searchParams;
  const next = verifiedRedirectPath(state.next);
  const theme = themeAttribute(await savedTheme());
  const field =
    "min-h-12 w-full rounded-lg border border-control-border bg-surface px-3 text-[16px] text-ink transition-colors duration-150 hover:border-ink-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
  const button =
    "flex min-h-12 w-full items-center justify-center gap-3 rounded-lg px-4 text-[16px] font-semibold transition-[background-color,transform] duration-150 ease-out active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
  return (
    <main
      data-theme={theme}
      className="sh-themed grid min-h-dvh bg-paper text-ink lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"
    >
      <div className="flex flex-col px-5 pt-[max(2.5rem,env(safe-area-inset-top))] pb-8 sm:px-8 lg:px-16">
        <header>
          <ShoulderWordmark className="h-auto w-36" />
        </header>
        <div className="my-auto w-full max-w-sm py-12">
          <h1 className="sh-lift font-display text-[34px] uppercase leading-[1.05] md:text-[40px]">
            Sign in to Shoulder
          </h1>
          <p
            className="sh-lift mt-3 text-[16px] leading-6 text-ink-2"
            style={{ "--i": 1 } as CSSProperties}
          >
            Coaches review the match and publish a few moments. Players watch
            their own clips and practice, in one private place.
          </p>
          {state.sent && (
            <p
              role="status"
              className="sh-lift mt-6 rounded-xl border border-line bg-surface p-4 text-[16px] leading-6"
            >
              If sign-in is available, check your email for a link. Open it in
              this browser.
            </p>
          )}
          {state.error && (
            <p
              role="alert"
              className="sh-lift mt-6 rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
            >
              We could not sign you in. Try again.
            </p>
          )}
          <form
            action="/auth/google"
            method="post"
            className="sh-lift mt-8"
            style={{ "--i": 2 } as CSSProperties}
          >
            {next ? <input type="hidden" name="next" value={next} /> : null}
            <Submit
              pending="Opening Google…"
              className={`${button} border border-control-border bg-surface hover:bg-surface-subtle`}
            >
              {/* Inline, not an <img> or a Google-hosted asset: the sign-in page is
                  asserted to make no cross-origin request and to contain no image. */}
              <GoogleMark />
              Continue with Google
            </Submit>
          </form>
          {/* Deliberately not a heading: the sign-in page's tests locate its only
              heading without scoping, so a second one would make them ambiguous. */}
          <p
            className="sh-lift mt-6 flex items-center gap-3 text-[14px] text-muted"
            style={{ "--i": 3 } as CSSProperties}
          >
            <span aria-hidden="true" className="h-px flex-1 bg-line" />
            Or use your email address
            <span aria-hidden="true" className="h-px flex-1 bg-line" />
          </p>
          <form
            action="/auth/magic-link"
            method="post"
            className="sh-lift mt-4 flex flex-col gap-2"
            style={{ "--i": 4 } as CSSProperties}
          >
            {next ? <input type="hidden" name="next" value={next} /> : null}
            <label htmlFor="email" className="text-[16px] font-semibold">
              Email address
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              maxLength={254}
              className={field}
            />
            <Submit
              pending="Sending link…"
              className={`${button} mt-2 bg-action text-on-action hover:bg-action-hover`}
            >
              Email a sign-in link
            </Submit>
          </form>
        </div>
        <footer className="flex items-center gap-3 border-t border-line pt-6">
          <ShoulderMark className="size-6" />
          <p className="text-[14px] text-muted">A private tool for one team.</p>
        </footer>
      </div>
      <div
        aria-hidden="true"
        className="relative hidden overflow-hidden bg-night text-on-night lg:flex lg:flex-col lg:justify-end lg:p-16"
      >
        <span className="absolute inset-y-0 left-0 w-px bg-night-line" />
        {/* Inline pitch, drawn on arrival; no image or remote asset. */}
        <svg
          className="sh-draw mb-auto h-auto max-h-[44vh] w-full text-night-line"
          viewBox="0 0 760 500"
          fill="none"
          stroke="currentColor"
          preserveAspectRatio="xMidYMid meet"
          aria-hidden="true"
        >
          <rect x="1" y="1" width="758" height="498" pathLength={1} />
          <path d="M380 1v498" pathLength={1} />
          <circle cx="380" cy="250" r="70" pathLength={1} />
          <path d="M1 140h120v220H1M759 140H639v220h120" pathLength={1} />
          <path
            className="text-lime"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            d="M207 254 Q316 214 394 217 Q496 171 568 114"
            pathLength={1}
          />
          <path
            d="M394 217 568 114 490 317Z"
            className="text-lime"
            fill="currentColor"
            fillOpacity={0.12}
            stroke="none"
          />
          <g fill="currentColor" stroke="none" className="text-on-night">
            <circle cx="207" cy="122" r="6" />
            <circle cx="207" cy="380" r="6" />
            <circle cx="310" cy="148" r="6" />
            <circle cx="312" cy="351" r="6" />
            <circle cx="490" cy="317" r="6" />
            <circle cx="576" cy="386" r="6" />
            <circle cx="650" cy="250" r="6" />
          </g>
          <g fill="currentColor" stroke="none" className="text-lime">
            <circle cx="207" cy="254" r="8" />
            <circle cx="394" cy="217" r="8" />
            <circle cx="568" cy="114" r="8" />
          </g>
        </svg>
        <p className="sh-lift relative max-w-[14ch] font-display text-[64px] leading-[0.98] uppercase">
          Check your shoulder before you receive.
        </p>
        <p
          className="sh-lift relative mt-6 max-w-[40ch] text-[17px] leading-7 text-night-muted"
          style={{ "--i": 2 } as CSSProperties}
        >
          A coach picks a few moments from each game and writes one line on
          each. The player watches, practises, and notices.
        </p>
      </div>
    </main>
  );
}
