import { type NextRequest, NextResponse } from "next/server";
import { authConfig, validOrigin } from "../../../lib/auth/policy";
import { authError, routeAuth } from "../../../lib/auth/route";

export async function POST(request: NextRequest) {
  const config = authConfig(process.env);
  if (!validOrigin(request.headers, config.origin)) return authError(403);
  const auth = routeAuth(request);
  try {
    const { error } = await auth.client.auth.signOut({ scope: "local" });
    auth.clear();
    if (error) return auth.finish(authError(503));
    return auth.finish(
      NextResponse.redirect(`${config.origin}/auth/sign-in`, 303),
    );
  } catch {
    auth.clear();
    return auth.finish(authError(503));
  }
}
