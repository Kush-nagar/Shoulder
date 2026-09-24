import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchMe, joinDemo } from "../../../lib/api";
import { verifiedRedirectPath } from "../../../lib/auth/policy";
import { createAuthClient, verifiedToken } from "../../../lib/auth/server";

export const dynamic = "force-dynamic";

export default async function Session({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const store = await cookies();
  const client = createAuthClient({ getAll: () => store.getAll() });
  const token = await verifiedToken(client);
  if (!token) redirect("/auth/sign-in");
  // A waking API can miss the first call; retry before showing any fallback.
  let me = await fetchMe(token);
  for (let attempt = 0; !me && attempt < 3; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    me = await fetchMe(token);
  }
  const next = verifiedRedirectPath((await searchParams).next);
  if (next?.startsWith("/coach/") && me?.roles.includes("coach")) {
    redirect(next);
  }
  if (
    next?.startsWith("/player/") &&
    me?.roles.includes("player") &&
    me.player
  ) {
    redirect(next);
  }
  if (me?.roles.includes("coach")) redirect("/coach/roster");
  if (me?.roles.includes("player") && me.player) redirect("/player");
  // Public demo only: a team-less account becomes a synthetic demo player.
  if (me && !me.roles.length && !me.player && (await joinDemo(token))) {
    redirect(next?.startsWith("/player/") ? next : "/player");
  }
  return (
    <main className="mx-auto max-w-md px-5 py-16">
      <h1 className="text-2xl font-semibold">You’re signed in.</h1>
      <p className="mt-4">
        {me
          ? "Your identity is verified. Team access is not available yet."
          : "Shoulder is taking longer than usual to load your space. Try again in a moment."}
      </p>
      {me ? null : (
        <a
          href="/auth/session"
          className="mt-6 inline-block rounded border border-line p-3"
        >
          Try again
        </a>
      )}
      <form action="/auth/sign-out" method="post" className="mt-6">
        <button type="submit" className="rounded border border-line p-3">
          Sign out
        </button>
      </form>
    </main>
  );
}
