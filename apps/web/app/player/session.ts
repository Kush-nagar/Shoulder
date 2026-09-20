import "server-only";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { fetchMe } from "../../lib/api";
import { verifiedRedirectPath } from "../../lib/auth/policy";
import { createAuthClient, verifiedToken } from "../../lib/auth/server";

/** Player access comes only from the database-derived role and linked row. */
export const playerSession = cache(async () => {
  const store = await cookies();
  const client = createAuthClient({ getAll: () => store.getAll() });
  let token: string | null = null;
  try {
    token = await verifiedToken(client);
  } catch {
    token = null;
  }
  if (!token) return null;
  const me = await fetchMe(token);
  if (!me?.roles.includes("player") || !me.player) {
    return { token, player: null };
  }
  return { token, player: me.player };
});

export async function requirePlayerSession(destination?: string) {
  const session = await playerSession();
  if (!session) {
    const next = verifiedRedirectPath(destination);
    redirect(
      next ? `/auth/sign-in?next=${encodeURIComponent(next)}` : "/auth/sign-in",
    );
  }
  if (!session.player) notFound();
  return {
    token: session.token,
    player: session.player,
  };
}
