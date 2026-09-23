import { ShoulderMark, ShoulderWordmark } from "../../../components/brand";
import { verifiedRedirectPath } from "../../../lib/auth/policy";

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
  return (
    <main className="mx-auto max-w-md px-5 py-16">
      <header className="mb-10">
        <ShoulderWordmark className="h-auto w-44" />
      </header>
      <h1 className="text-2xl font-semibold">Sign in to Shoulder</h1>
      {state.sent && (
        <p role="status" className="mt-4">
          If sign-in is available, check your email for a link. Open it in this
          browser.
        </p>
      )}
      {state.error && (
        <p role="alert" className="mt-4">
          We could not sign you in. Try again.
        </p>
      )}
      <form action="/auth/google" method="post" className="mt-6">
        {next ? <input type="hidden" name="next" value={next} /> : null}
        <button
          type="submit"
          className="flex w-full items-center justify-center gap-3 rounded border border-line p-3 font-semibold"
        >
          {/* Inline, not an <img> or a Google-hosted asset: the sign-in page is
              asserted to make no cross-origin request and to contain no image. */}
          <GoogleMark />
          Continue with Google
        </button>
      </form>
      {/* Deliberately not a heading: the sign-in page's tests locate its only
          heading without scoping, so a second one would make them ambiguous. */}
      <p className="mt-6 text-sm text-muted">Or use your email address.</p>
      <form
        action="/auth/magic-link"
        method="post"
        className="mt-3 flex flex-col gap-3"
      >
        {next ? <input type="hidden" name="next" value={next} /> : null}
        <label htmlFor="email">Email address</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          maxLength={254}
          className="rounded border border-line p-3"
        />
        <button
          type="submit"
          className="rounded border border-line p-3 font-semibold"
        >
          Email a sign-in link
        </button>
      </form>
      <footer className="mt-12 flex items-center gap-3 border-t border-line pt-6">
        <ShoulderMark className="size-6" />
        <p className="text-sm text-muted">A private tool for one team.</p>
      </footer>
    </main>
  );
}
