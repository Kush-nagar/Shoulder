import "server-only";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { fetchMe } from "../../lib/api";
import { authConfig, verifiedRedirectPath } from "../../lib/auth/policy";
import { createAuthClient, verifiedToken } from "../../lib/auth/server";
import { marketplaceEnabled } from "../../lib/marketplace";
import type { AgeAttestation } from "./types";

export type Read<T> = { status: number; data: T | null };

/** One GET against the API as the signed-in user. Status 503 = unreachable. */
export async function read<T>(token: string, path: string): Promise<Read<T>> {
  try {
    const response = await fetch(`${authConfig(process.env).apiUrl}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return { status: response.status, data: null };
    return { status: response.status, data: (await response.json()) as T };
  } catch {
    return { status: 503, data: null };
  }
}

const verified = cache(async () => {
  const store = await cookies();
  const client = createAuthClient({ getAll: () => store.getAll() });
  try {
    return await verifiedToken(client);
  } catch {
    return null;
  }
});

/**
 * Any signed-in account may open marketplace pages; the API decides what each
 * one may see (adult attestation, coach profile owner, platform admin).
 */
export async function requireSignedIn(destination: string): Promise<string> {
  if (!marketplaceEnabled()) notFound();
  const token = await verified();
  if (!token) {
    const next = verifiedRedirectPath(destination);
    redirect(
      next ? `/auth/sign-in?next=${encodeURIComponent(next)}` : "/auth/sign-in",
    );
  }
  return token;
}

export const readAge = cache((token: string) =>
  read<AgeAttestation>(token, "/v1/me/age-attestation"),
);

/** The signed-in player's `me`, or null for anyone else. No demo join here. */
export const playerMe = cache(async () => {
  const token = await verified();
  if (!token) return null;
  const me = await fetchMe(token);
  return me?.roles.includes("player") && me.player ? me : null;
});

/**
 * Whether the account has a Google identity. Only these users see "Use my
 * Google birthday": for anyone else a Google flow could sign them into a
 * different or new account. Reads the already verified token's claims.
 */
export function hasGoogleIdentity(token: string): boolean {
  try {
    const claims = JSON.parse(
      Buffer.from(token.split(".")[1] ?? "", "base64url").toString(),
    ) as { app_metadata?: { providers?: unknown } };
    const providers = claims.app_metadata?.providers;
    return Array.isArray(providers) && providers.includes("google");
  } catch {
    return false;
  }
}
