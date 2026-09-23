import "server-only";
import { authConfig } from "../../../lib/auth/policy";
import type {
  AiCoachFeedback,
  PracticeVideo,
  PracticeVideoDetail,
} from "./types";

// ponytail: lib/api.ts is outside this workstream; move these three readers
// there beside fetchReflections when the generated types land.
type Read<T> = { status: number; data: T | null };

async function read<T>(token: string, path: string): Promise<Read<T>> {
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

export function fetchPracticeVideos(token: string) {
  return read<PracticeVideo[]>(token, "/v1/player/practice-videos");
}

export function fetchPracticeVideo(token: string, id: string) {
  return read<PracticeVideoDetail>(
    token,
    `/v1/player/practice-videos/${encodeURIComponent(id)}`,
  );
}

export function fetchPracticeFeedback(token: string, id: string) {
  return read<AiCoachFeedback[]>(
    token,
    `/v1/player/practice-videos/${encodeURIComponent(id)}/ai-feedback`,
  );
}
