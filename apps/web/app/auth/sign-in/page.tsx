import { ShoulderMark, ShoulderWordmark } from "../../../components/brand";
import { verifiedRedirectPath } from "../../../lib/auth/policy";

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
          This link could not sign you in. Request a new link.
        </p>
      )}
      <form
        action="/auth/magic-link"
        method="post"
        className="mt-6 flex flex-col gap-3"
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
