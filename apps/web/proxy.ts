import { type NextRequest, NextResponse } from "next/server";
import { authError, routeAuth } from "./lib/auth/route";
import { verifiedToken } from "./lib/auth/server";

export async function proxy(request: NextRequest) {
  let auth: ReturnType<typeof routeAuth>;
  try {
    auth = routeAuth(request);
  } catch {
    // Auth is not configured (e.g. the CI smoke server): no session can exist,
    // so there is nothing to refresh. Pages still enforce their own access.
    return NextResponse.next();
  }
  try {
    const token = await verifiedToken(auth.client);
    if (!token) auth.clear();
    // Forward refreshed cookies to this request's render/handler AND the browser.
    // Layouts get the requested path so a shell-level sign-in redirect can
    // return here (ADR 0024); always overwritten, and sanitised where read.
    const headers = new Headers(request.headers);
    headers.set(
      "x-shoulder-path",
      `${request.nextUrl.pathname}${request.nextUrl.search}`,
    );
    return auth.finish(NextResponse.next({ request: { headers } }));
  } catch {
    auth.clear();
    return auth.finish(authError(503));
  }
}

// Every route that reads a verified session must be listed, or a refreshed
// token is never written back and the session expires silently mid-use.
export const config = {
  matcher: [
    "/",
    "/coach/:path*",
    "/player/:path*",
    "/auth/session",
    "/api/auth/identity",
    "/api/me",
    "/api/player/:path*",
    "/coaching/:path*",
    "/admin/:path*",
    "/api/coaching/:path*",
    "/api/admin/:path*",
  ],
};
