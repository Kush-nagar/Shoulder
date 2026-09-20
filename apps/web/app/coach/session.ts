import "server-only";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { fetchMe } from "../../lib/api";
import { verifiedRedirectPath } from "../../lib/auth/policy";
import { createAuthClient, verifiedToken } from "../../lib/auth/server";

/**
 * Coach access is proven once per request from database-derived roles, never
 * from the route, a cookie, a query parameter, or client state. Cached so the
 * shell and its page resolve the same session without a second lookup.
 */
export const coachSession = cache(
  async (): Promise<{
    token: string;
    coach: boolean;
    userId: string;
  } | null> => {
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
    return {
      token,
      coach: me?.roles.includes("coach") ?? false,
      userId: me?.user_id ?? "",
    };
  },
);

/** Pages call this. Forbidden and absent share the one not-found surface. */
export async function requireCoach(destination?: string): Promise<string> {
  return (await requireCoachSession(destination)).token;
}

/**
 * The same check, for a page that also needs to know which coach.
 *
 * Draft storage is keyed by the author, so the review page cannot make do with
 * "somebody with the coach role": two coaches sharing a browser profile would
 * otherwise share a key, and one could submit the other's unsent text under
 * their own name.
 */
export async function requireCoachSession(destination?: string): Promise<{
  token: string;
  userId: string;
}> {
  const session = await coachSession();
  if (!session) {
    const next = verifiedRedirectPath(destination);
    redirect(
      next ? `/auth/sign-in?next=${encodeURIComponent(next)}` : "/auth/sign-in",
    );
  }
  if (!session.coach) notFound();
  // An identity that resolved a role but no subject is not one drafts may be
  // filed under.
  if (!session.userId) notFound();
  return { token: session.token, userId: session.userId };
}
