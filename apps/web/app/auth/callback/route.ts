import { type NextRequest, NextResponse } from "next/server";
import { authConfig } from "../../../lib/auth/policy";
import { routeAuth } from "../../../lib/auth/route";
import { verifiedToken } from "../../../lib/auth/server";

export async function GET(request: NextRequest) {
  const config = authConfig(process.env);
  const auth = routeAuth(request);
  const codes = request.nextUrl.searchParams.getAll("code");
  const flows = request.nextUrl.searchParams.getAll("sb_flow_id");
  try {
    if (
      request.headers.get("host") !== new URL(config.origin).host ||
      codes.length !== 1 ||
      !codes[0] ||
      codes[0].length > 2048 ||
      flows.length > 1 ||
      (flows.length === 1 && !/^[A-Za-z0-9_-]{8,64}$/.test(flows[0])) ||
      request.nextUrl.searchParams.has("error")
    )
      throw new Error("Invalid callback");
    const { error } = await auth.client.auth.exchangeCodeForSession(
      codes[0],
      flows.length ? { flowId: flows[0] } : undefined,
    );
    if (error || !(await verifiedToken(auth.client)))
      throw new Error("Invalid callback");
    // A fixed destination prevents open redirects and premature role routing.
    return auth.finish(
      NextResponse.redirect(`${config.origin}/auth/session`, 303),
    );
  } catch {
    // A failed top-level callback must not let an external link sign out an
    // existing session, and an unverified exchange must not reach the browser.
    auth.discardWrites();
    return auth.finish(
      NextResponse.redirect(`${config.origin}/auth/sign-in?error=1`, 303),
    );
  }
}
