// TEMP until OpenAPI regen at integration: replace every type below with the
// generated `components["schemas"][...]` aliases from lib/api.ts and delete
// this file. Shapes follow docs/projects/project-08-player-practice-ai-coach.md.

export type PracticeVideoStatus = "uploading" | "ready" | "deleted";

export type PracticeVideo = {
  id: string;
  title: string | null;
  status: PracticeVideoStatus;
  content_type: string;
  size_bytes: number;
  duration_ms: number | null;
  created_at: string;
  upload_completed_at: string | null;
  expires_at: string | null;
};

/** Detail adds a short-lived signed GET for the player's own object. */
export type PracticeVideoDetail = PracticeVideo & {
  url: string | null;
  expires_in: number | null;
};

export type PracticeUploadStartRequest = {
  title: string | null;
  content_type: string;
  size_bytes: number;
  duration_ms: number | null;
};

/** One presigned PUT; bytes go browser to storage, never through Next/FastAPI. */
export type PracticeUploadStart = {
  id: string;
  upload_url: string;
  expires_in: number;
};

export type PracticeDrill = { title: string; why: string; how: string };

export type AiCoachFeedback = {
  id: string;
  practice_video_id: string;
  development_goal_id: string | null;
  model: string;
  body: string;
  drills: PracticeDrill[];
  created_at: string;
};

type Spread = { p10: number; p50: number; p90: number };

/** Aggregate movement summary produced on the device (W2 pose/analyze.ts). */
export type PracticeFeatures = {
  frames_analyzed: number;
  fps: number;
  duration_ms: number;
  knee_flexion_deg: Spread;
  hip_flexion_deg: Spread;
  trunk_lean_deg: Spread;
  head_turns: number;
  head_turns_per_min: number;
  stance_width_ratio: { p50: number };
  visibility_mean: number;
};
