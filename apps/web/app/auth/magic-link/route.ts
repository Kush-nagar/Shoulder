import { type NextRequest, NextResponse } from "next/server";
import {
  authConfig,
  verifiedRedirectPath,
  validOrigin,
} from "../../../lib/auth/policy";
import { authError, routeAuth } from "../../../lib/auth/route";

export async function POST(request: NextRequest) {
  const config = authConfig(process.env);
  if (!validOrigin(request.headers, config.origin)) return authError(403);
  const auth = routeAuth(request);
  try {
    const body = await request.formData();
    const email = body.get("email");
    const next = verifiedRedirectPath(body.get("next"));
    if (
      typeof email !== "string" ||
      email.length > 254 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
    ) {
      return auth.finish(
        NextResponse.json(
          { error: "Enter a valid email address" },
          { status: 400 },
        ),
      );
    }
    // Supabase enforces recipient cooldown and project email rate limits.
    // Do not forward caller-supplied IP headers or expose account existence/errors.
    const callback = new URL("/auth/callback", config.origin);
    if (next) callback.searchParams.set("next", next);
    const { error } = await auth.client.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: callback.toString(),
      },
    });
    if (error) auth.discardWrites();
    const submitted = new URL("/auth/sign-in", config.origin);
    submitted.searchParams.set("sent", "1");
    if (next) submitted.searchParams.set("next", next);
    return auth.finish(NextResponse.redirect(submitted, 303));
  } catch {
    auth.discardWrites();
    return auth.finish(authError(503));
  }
}
