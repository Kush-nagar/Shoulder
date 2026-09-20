import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchMe } from "../../../lib/api";
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
  const me = await fetchMe(token);
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
  return (
    <main className="mx-auto max-w-md px-5 py-16">
      <h1 className="text-2xl font-semibold">You’re signed in.</h1>
      <p className="mt-4">
        Your identity is verified. Team access is not available yet.
      </p>
      <form action="/auth/sign-out" method="post" className="mt-6">
        <button type="submit" className="rounded border border-line p-3">
          Sign out
        </button>
      </form>
    </main>
  );
}
