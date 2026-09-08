import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchMe } from "../../../lib/api";
import { createAuthClient, verifiedToken } from "../../../lib/auth/server";

export const dynamic = "force-dynamic";

export default async function Session() {
  const store = await cookies();
  // Proxy owns refresh writes before this read-only server component.
  const client = createAuthClient({ getAll: () => store.getAll() });
  const token = await verifiedToken(client);
  if (!token) redirect("/auth/sign-in");
  // Roles come from team membership in the database, never from the session.
  const me = await fetchMe(token);
  const coach = me?.roles.includes("coach") ?? false;
  const player = me?.roles.includes("player") ?? false;
  return (
    <main className="mx-auto max-w-md px-5 py-16">
      <h1 className="text-2xl font-semibold">You’re signed in.</h1>
      <p className="mt-4">
        {coach
          ? `You coach ${me?.team_ids.length === 1 ? "one team" : `${me?.team_ids.length} teams`}. Roster tools open next.`
          : player
            ? "You’re on a team. Your clips appear here when your coach shares them."
            : "Your identity is verified. Team access is not available yet."}
      </p>
      <form action="/auth/sign-out" method="post" className="mt-6">
        <button type="submit" className="rounded border border-line p-3">
          Sign out
        </button>
      </form>
    </main>
  );
}
