import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchMe } from "../lib/api";
import { createAuthClient, verifiedToken } from "../lib/auth/server";
import { MarketingPage } from "./marketing";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Shoulder — See the game take shape",
  description:
    "A coach-led way to turn match film into a few meaningful moments for each player.",
  robots: { index: true, follow: true },
};

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
  if (!token) return <MarketingPage />;
  // Roles come from team membership in the database, never from the route,
  // a cookie, a query parameter, or client state. No role and an unavailable
  // API both land on the neutral signed-in page, which grants nothing.
  const me = await fetchMe(token);
  if (me?.roles.includes("coach")) redirect("/coach/roster");
  if (me?.roles.includes("player") && me.player) redirect("/player");
  redirect("/auth/session");
}
