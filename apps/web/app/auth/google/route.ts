import { type NextRequest, NextResponse } from "next/server";
import {
  authConfig,
  validOrigin,
  verifiedRedirectPath,
} from "../../../lib/auth/policy";
import { authError, routeAuth } from "../../../lib/auth/route";

export async function POST(request: NextRequest) {
  const config = authConfig(process.env);
  if (!validOrigin(request.headers, config.origin)) return authError(403);
  const auth = routeAuth(request);
  try {
    // Unlike the magic link there is no required field, so a body-less POST is
    // a valid start rather than a failure; `next` stays optional either way.
    const body = await request.formData().catch(() => null);
    const next = verifiedRedirectPath(body?.get("next"));
    // Google returns to the same PKCE callback the magic link uses; the
    // callback route already verifies host, code shape, and exchange result.
    const callback = new URL("/auth/callback", config.origin);
    if (next) callback.searchParams.set("next", next);
    const { data, error } = await auth.client.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: callback.toString(),
        // Redirect from this route so the code verifier is written by finish().
        skipBrowserRedirect: true,
      },
    });
    if (error || !data?.url) {
      auth.discardWrites();
      return auth.finish(
        NextResponse.redirect(`${config.origin}/auth/sign-in?error=1`, 303),
      );
    }
    // finish() carries the pending PKCE verifier cookie; without it the
    // callback exchange has nothing to verify the returned code against.
    return auth.finish(NextResponse.redirect(data.url, 303));
  } catch {
    // An unsuccessful start must not replace an existing pending flow.
    auth.discardWrites();
    return auth.finish(
      NextResponse.redirect(`${config.origin}/auth/sign-in?error=1`, 303),
    );
  }
}
