import { type NextRequest, NextResponse } from "next/server";
import { authConfig, validOrigin } from "../../../lib/auth/policy";
import { authError, routeAuth } from "../../../lib/auth/route";

export async function POST(request: NextRequest) {
  const config = authConfig(process.env);
  if (!validOrigin(request.headers, config.origin)) return authError(403);
  const auth = routeAuth(request);
  try {
    const body = await request.formData();
    const email = body.get("email");
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
    const { error } = await auth.client.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${config.origin}/auth/callback`,
      },
    });
    if (error) auth.discardWrites();
    return auth.finish(
      NextResponse.redirect(`${config.origin}/auth/sign-in?sent=1`, 303),
    );
  } catch {
    auth.discardWrites();
    return auth.finish(authError(503));
  }
}
