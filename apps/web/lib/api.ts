import "server-only";
import type { components } from "@shoulder/contracts";
import { authConfig } from "./auth/policy";

export type Me = components["schemas"]["Me"];

/** Read database-derived identity through the fixed FastAPI endpoint. */
export async function fetchMe(token: string): Promise<Me | null> {
  try {
    const response = await fetch(`${authConfig(process.env).apiUrl}/v1/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    // A missing profile or an unavailable API grants no product access.
    return response.ok ? ((await response.json()) as Me) : null;
  } catch {
    return null;
  }
}
