import { type NextRequest, NextResponse } from "next/server";
import { authError, routeAuth } from "./lib/auth/route";
import { verifiedToken } from "./lib/auth/server";

export async function proxy(request: NextRequest) {
  const auth = routeAuth(request);
  try {
    const token = await verifiedToken(auth.client);
    if (!token) auth.clear();
    // Forward refreshed cookies to this request's render/handler AND the browser.
    return auth.finish(NextResponse.next({ request }));
  } catch {
    auth.clear();
    return auth.finish(authError(503));
  }
}

export const config = {
  matcher: ["/auth/session", "/api/auth/identity", "/api/me"],
};
