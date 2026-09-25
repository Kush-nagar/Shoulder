import "server-only";
import type { components } from "@shoulder/contracts";
import { authConfig } from "../../../lib/auth/policy";

type Schema = components["schemas"];
export type TrainingSession = Schema["TrainingSession"];
export type SessionSummary = Schema["SessionSummary"];

type Read<T> = { status: number; data: T | null };

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

export function fetchSessions(token: string) {
  return read<TrainingSession[]>(token, "/v1/player/sessions");
}

export function fetchSession(token: string, id: string) {
  return read<TrainingSession>(
    token,
    `/v1/player/sessions/${encodeURIComponent(id)}`,
  );
}

export function fetchSessionSummary(token: string, weeks: number) {
  return read<SessionSummary>(
    token,
    `/v1/player/sessions/summary?weeks=${weeks}`,
  );
}
