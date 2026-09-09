import "server-only";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { fetchMe } from "../../lib/api";
import { createAuthClient, verifiedToken } from "../../lib/auth/server";

/**
 * Coach access is proven once per request from database-derived roles, never
 * from the route, a cookie, a query parameter, or client state. Cached so the
 * shell and its page resolve the same session without a second lookup.
 */
export const coachSession = cache(
  async (): Promise<{ token: string; coach: boolean } | null> => {
    const store = await cookies();
    // Proxy owns refresh writes before this read-only server component.
    const client = createAuthClient({ getAll: () => store.getAll() });
    let token: string | null = null;
    try {
      token = await verifiedToken(client);
    } catch {
      // An unavailable identity service grants no product access.
      token = null;
    }
    if (!token) return null;
    const me = await fetchMe(token);
    return { token, coach: me?.roles.includes("coach") ?? false };
  },
);

/** Pages call this. Forbidden and absent share the one not-found surface. */
export async function requireCoach(): Promise<string> {
  const session = await coachSession();
  if (!session) redirect("/auth/sign-in");
  if (!session.coach) notFound();
  return session.token;
}
