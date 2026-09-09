import "server-only";
import type { components } from "@shoulder/contracts";
import { cache } from "react";
import { authConfig } from "./auth/policy";

export type Me = components["schemas"]["Me"];

type Schema = components["schemas"];

// The enum is inlined by the generator; derive it rather than restate it.
export type GoalStatus = Schema["GoalSummary"]["status"];
export type TeamSummary = Schema["TeamSummary"];
export type GoalSummary = Schema["GoalSummary"];
export type RosterPlayer = Schema["RosterPlayer"];
export type Goal = Schema["Goal"];
export type BulkResult = Schema["BulkResult"];
export type InviteResult = Schema["InviteResult"];

/** Status plus parsed body. Problem details stay server-side; callers map status. */
/**
 * Status, parsed body, and the RFC 9457 `type` slug when the call failed.
 *
 * The slug is the machine-readable half of the problem document. Without it a
 * caller can only guess which of several 4xx causes applied and will describe
 * the wrong one to the coach.
 */
export type ApiReply<T> = {
  status: number;
  data: T | null;
  problem: string | null;
};

async function request<T>(
  token: string,
  path: string,
  init?: RequestInit,
): Promise<ApiReply<T>> {
  try {
    const response = await fetch(`${authConfig(process.env).apiUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
      },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    if (response.ok) {
      return {
        status: response.status,
        data: (await response.json().catch(() => null)) as T,
        problem: null,
      };
    }
    const body = (await response.json().catch(() => null)) as {
      type?: string;
    } | null;
    return {
      status: response.status,
      data: null,
      problem: body?.type?.split("/").pop() ?? null,
    };
  } catch {
    // A missing profile or an unavailable API grants no product access.
    return { status: 0, data: null, problem: null };
  }
}

/** Read database-derived identity through the fixed FastAPI endpoint. */
export async function fetchMe(token: string): Promise<Me | null> {
  return (await request<Me>(token, "/v1/me")).data;
}

/**
 * Teams the caller belongs to. Deduplicated across a shell and its page.
 *
 * Null means the call failed; an empty array means the caller belongs to no
 * team. Collapsing the two would show an outage as "no team yet".
 */
export const fetchTeams = cache(
  async (token: string): Promise<TeamSummary[] | null> =>
    (await request<TeamSummary[]>(token, "/v1/teams")).data,
);

/** Null means absent or hidden by row-level security; both are not-found. */
export async function fetchRoster(
  token: string,
  teamId: string,
  includeArchived = false,
): Promise<RosterPlayer[] | null> {
  const query = includeArchived ? "?include_archived=true" : "";
  return (
    await request<RosterPlayer[]>(token, `/v1/teams/${teamId}/players${query}`)
  ).data;
}

export async function fetchGoals(
  token: string,
  playerId: string,
): Promise<Goal[] | null> {
  return (await request<Goal[]>(token, `/v1/players/${playerId}/goals`)).data;
}

export function apiWrite<T>(
  token: string,
  path: string,
  method: "POST" | "PATCH",
  body: unknown,
): Promise<ApiReply<T>> {
  return request<T>(token, path, { method, body: JSON.stringify(body) });
}
