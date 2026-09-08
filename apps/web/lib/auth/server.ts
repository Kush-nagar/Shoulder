import "server-only";
import { type CookieMethodsServer, createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { authConfig, validClaims } from "./policy";

export const cookieName = "shoulder-auth";

export function createAuthClient(cookies: CookieMethodsServer) {
  const config = authConfig(process.env);
  return createServerClient(config.supabaseUrl, config.key, {
    cookieOptions: {
      name: cookieName,
      httpOnly: true,
      secure: config.secure,
      sameSite: "lax",
      path: "/",
    },
    cookies,
  });
}

export async function verifiedToken(
  client: SupabaseClient,
): Promise<string | null> {
  const { data: sessionData, error: sessionError } =
    await client.auth.getSession();
  // Use only the token, never the unverified embedded user. getSession may refresh.
  const token = sessionData.session?.access_token;
  if (sessionError || !token) return null;
  const { data, error } = await client.auth.getClaims(token);
  if (
    error ||
    !data ||
    !["ES256", "RS256"].includes(data.header.alg) ||
    !validClaims(data.claims, authConfig(process.env).supabaseUrl)
  )
    return null;
  // Cryptographic validity alone outlives logout. Auth also checks session_id
  // existence, so copied cookies from a revoked session cannot restore access.
  const { data: current, error: currentError } =
    await client.auth.getUser(token);
  if (currentError || current.user?.id !== data.claims.sub) return null;
  return token;
}
