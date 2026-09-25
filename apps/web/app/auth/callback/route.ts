import { type NextRequest, NextResponse } from "next/server";
import { authConfig, verifiedRedirectPath } from "../../../lib/auth/policy";
import { routeAuth } from "../../../lib/auth/route";
import { verifiedToken } from "../../../lib/auth/server";
import { birthYearFrom } from "../../../lib/google-birthday";
import { marketplaceEnabled } from "../../../lib/marketplace";

/**
 * Birthday flow outcome for `/coaching?birthday=`. The Google token is used
 * once, server-side, and only the year is sent to the API.
 */
async function attestFromGoogle(
  providerToken: string | null | undefined,
  accessToken: string,
  apiUrl: string,
): Promise<"saved" | "none" | "refused" | "error"> {
  if (!providerToken) return "none";
  let year: number | null;
  try {
    const people = await fetch(
      "https://people.googleapis.com/v1/people/me?personFields=birthdays",
      {
        headers: { Authorization: `Bearer ${providerToken}` },
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(5000),
      },
    );
    year = people.ok ? birthYearFrom(await people.json()) : null;
  } catch {
    year = null;
  }
  if (year === null) return "none";
  try {
    const reply = await fetch(`${apiUrl}/v1/me/age-attestation`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ birth_year: year }),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    if (reply.ok) return "saved";
    return reply.status === 409 || reply.status === 422 ? "refused" : "error";
  } catch {
    return "error";
  }
}

export async function GET(request: NextRequest) {
  const config = authConfig(process.env);
  const auth = routeAuth(request);
  const codes = request.nextUrl.searchParams.getAll("code");
  const flows = request.nextUrl.searchParams.getAll("sb_flow_id");
  const destinations = request.nextUrl.searchParams.getAll("next");
  const next =
    destinations.length === 1 ? verifiedRedirectPath(destinations[0]) : null;
  const purposes = request.nextUrl.searchParams.getAll("purpose");
  const birthday =
    purposes.length === 1 && purposes[0] === "birthday" && marketplaceEnabled();
  try {
    if (
      request.headers.get("host") !== new URL(config.origin).host ||
      codes.length !== 1 ||
      !codes[0] ||
      codes[0].length > 2048 ||
      flows.length > 1 ||
      purposes.length > 1 ||
      (flows.length === 1 && !/^[A-Za-z0-9_-]{8,64}$/.test(flows[0])) ||
      request.nextUrl.searchParams.has("error")
    )
      throw new Error("Invalid callback");
    const { data, error } = await auth.client.auth.exchangeCodeForSession(
      codes[0],
      flows.length ? { flowId: flows[0] } : undefined,
    );
    const token = error ? null : await verifiedToken(auth.client);
    if (!token) throw new Error("Invalid callback");
    if (birthday) {
      const outcome = await attestFromGoogle(
        data.session?.provider_token,
        token,
        config.apiUrl,
      );
      // Re-save the session without the Google tokens so the cookie never
      // keeps them. setSession rebuilds it from the Supabase tokens only.
      if (data.session)
        await auth.client.auth.setSession({
          access_token: data.session.access_token,
          refresh_token: data.session.refresh_token,
        });
      const back = new URL("/coaching", config.origin);
      if (outcome !== "saved") back.searchParams.set("birthday", outcome);
      return auth.finish(NextResponse.redirect(back, 303));
    }
    // Session routing verifies the database role before honoring this closed
    // allowlist. No callback value can become an absolute URL.
    const session = new URL("/auth/session", config.origin);
    if (next) session.searchParams.set("next", next);
    return auth.finish(NextResponse.redirect(session, 303));
  } catch {
    // A failed top-level callback must not let an external link sign out an
    // existing session, and an unverified exchange must not reach the browser.
    auth.discardWrites();
    return auth.finish(
      NextResponse.redirect(`${config.origin}/auth/sign-in?error=1`, 303),
    );
  }
}
