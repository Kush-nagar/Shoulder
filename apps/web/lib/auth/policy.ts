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

const UUID =
  "[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const PLAYER_GOAL = new RegExp(`^/player/goals/(${UUID})$`, "i");
const COACH_GAME = new RegExp(`^/coach/games/${UUID}$`, "i");
const COACH_PLAYER = new RegExp(`^/coach/players/${UUID}$`, "i");
const PUBLICATION = new RegExp(`^${UUID}$`, "i");

/**
 * Allow only notification destinations owned by Shoulder. Callers receive a
 * canonical relative path, never a URL or a caller-selected arbitrary route.
 */
export function verifiedRedirectPath(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    value.length > 300 ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\")
  ) {
    return null;
  }
  let parsed: URL;
  try {
    parsed = new URL(value, "https://shoulder.invalid");
  } catch {
    return null;
  }
  if (parsed.origin !== "https://shoulder.invalid" || parsed.hash) return null;
  if (COACH_GAME.test(parsed.pathname) || COACH_PLAYER.test(parsed.pathname)) {
    return parsed.search ? null : parsed.pathname;
  }
  if (!PLAYER_GOAL.test(parsed.pathname)) return null;
  const keys = [...parsed.searchParams.keys()];
  if (keys.length === 0) return parsed.pathname;
  const publications = parsed.searchParams.getAll("publication");
  if (
    keys.length !== 1 ||
    keys[0] !== "publication" ||
    publications.length !== 1 ||
    !PUBLICATION.test(publications[0])
  ) {
    return null;
  }
  return `${parsed.pathname}?publication=${publications[0]}`;
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
