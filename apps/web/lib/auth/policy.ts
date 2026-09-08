// Pure policy helpers; callers supply server-only configuration.
export function authConfig(env: Record<string, string | undefined>) {
  const origin = new URL(env.APP_ORIGIN ?? "");
  if (origin.origin !== env.APP_ORIGIN || origin.username || origin.password) {
    throw new Error("APP_ORIGIN must be an exact origin");
  }
  const localHttp =
    env.AUTH_ALLOW_LOCAL_HTTP === "true" &&
    ["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname);
  if (
    origin.protocol !== "https:" &&
    !(origin.protocol === "http:" && localHttp)
  ) {
    throw new Error("HTTPS is required outside explicit loopback development");
  }
  if (!env.SUPABASE_URL || !env.SUPABASE_PUBLISHABLE_KEY || !env.API_BASE_URL) {
    throw new Error("Authentication configuration is incomplete");
  }
  return {
    origin: origin.origin,
    secure: origin.protocol === "https:",
    supabaseUrl: env.SUPABASE_URL.replace(/\/$/, ""),
    key: env.SUPABASE_PUBLISHABLE_KEY,
    apiUrl: env.API_BASE_URL.replace(/\/$/, ""),
  };
}

export function validOrigin(headers: Headers, origin: string): boolean {
  return (
    headers.get("origin") === origin &&
    headers.get("host") === new URL(origin).host &&
    !["cross-site", "same-site"].includes(headers.get("sec-fetch-site") ?? "")
  );
}

// Call only AFTER getClaims() has cryptographically verified the token.
export function validClaims(
  claims: Record<string, unknown>,
  supabaseUrl: string,
): boolean {
  return (
    typeof claims.sub === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      claims.sub,
    ) &&
    claims.iss === `${supabaseUrl}/auth/v1` &&
    typeof claims.session_id === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      claims.session_id,
    ) &&
    claims.session_id !== "00000000-0000-0000-0000-000000000000" &&
    claims.aud === "authenticated" &&
    typeof claims.exp === "number" &&
    claims.exp > Date.now() / 1000
  );
}
