import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchMe } from "../lib/api";
import { createAuthClient, verifiedToken } from "../lib/auth/server";

export const dynamic = "force-dynamic";

export default async function Home() {
  const store = await cookies();
  // Proxy owns refresh writes before this read-only server component.
  const client = createAuthClient({ getAll: () => store.getAll() });
  let token: string | null = null;
  try {
    token = await verifiedToken(client);
  } catch {
    token = null;
  }
  if (!token) redirect("/auth/sign-in");
  // Roles come from team membership in the database, never from the route,
  // a cookie, a query parameter, or client state. No role and an unavailable
  // API both land on the neutral signed-in page, which grants nothing.
  const me = await fetchMe(token);
  if (me?.roles.includes("coach")) redirect("/coach/roster");
  if (me?.roles.includes("player") && me.player) redirect("/player");
  redirect("/auth/session");
}
