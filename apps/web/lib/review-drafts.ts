import type { components } from "@shoulder/contracts";

type Judgment = components["schemas"]["Judgment"];

export type DraftScope = {
  videoId: string;
  playerId: string;
  goalId: string | null;
};

export type DraftContent = {
  clipStartMs: number;
  clipEndMs: number | null;
  verdict: Judgment["verdict"] | null;
  commentText: string;
};

export type SyncedDraft = DraftContent & { version: number };

export type ReviewDraft = DraftContent & {
  localId: string;
  observationId: string | null;
  judgmentId: string | null;
  position: number;
  version: number | null;
  synced: SyncedDraft | null;
  saveState:
    | "pending"
    | "saving"
    | "saved"
    | "offline"
    | "attention"
    | "conflict";
  conflict: SyncedDraft | null;
};

type StoredDrafts = {
  schema: 1;
  scope: DraftScope;
  drafts: ReviewDraft[];
};

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const verdicts = new Set(["applied", "opportunity", "not_relevant"]);
const saveStates = new Set([
  "pending",
  "saving",
  "saved",
  "offline",
  "attention",
  "conflict",
]);

function isUuidOrNull(value: unknown): boolean {
  return (
    value === null || (typeof value === "string" && uuidPattern.test(value))
  );
}

function isSnapshot(value: unknown): value is SyncedDraft {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<SyncedDraft>;
  return Boolean(
    Number.isInteger(item.clipStartMs) &&
      (item.clipStartMs ?? -1) >= 0 &&
      Number.isInteger(item.clipEndMs) &&
      (item.clipEndMs ?? 0) > (item.clipStartMs ?? -1) &&
      verdicts.has(item.verdict ?? "") &&
      typeof item.commentText === "string" &&
      item.commentText.length <= 400 &&
      Number.isInteger(item.version) &&
      (item.version ?? 0) > 0,
  );
}

function isDraft(value: unknown): value is ReviewDraft {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<ReviewDraft>;
  const boundsAreValid =
    Number.isInteger(item.clipStartMs) &&
    (item.clipStartMs ?? -1) >= 0 &&
    (item.clipEndMs === null ||
      (Number.isInteger(item.clipEndMs) &&
        (item.clipEndMs ?? 0) > (item.clipStartMs ?? -1)));
  return Boolean(
    typeof item.localId === "string" &&
      uuidPattern.test(item.localId) &&
      isUuidOrNull(item.observationId) &&
      isUuidOrNull(item.judgmentId) &&
      Number.isInteger(item.position) &&
      (item.position ?? -1) >= 0 &&
      boundsAreValid &&
      (item.verdict === null || verdicts.has(item.verdict ?? "")) &&
      typeof item.commentText === "string" &&
      item.commentText.length <= 400 &&
      (item.version === null ||
        (Number.isInteger(item.version) && (item.version ?? 0) > 0)) &&
      (item.synced === null || isSnapshot(item.synced)) &&
      typeof item.saveState === "string" &&
      saveStates.has(item.saveState) &&
      (item.conflict === null || isSnapshot(item.conflict)),
  );
}

export function draftStorageKey(scope: DraftScope): string {
  return `shoulder:review-drafts:v1:${scope.videoId}:${scope.playerId}`;
}

export function serializeDrafts(
  scope: DraftScope,
  drafts: ReviewDraft[],
): string {
  return JSON.stringify({ schema: 1, scope, drafts } satisfies StoredDrafts);
}

export function restoreDrafts(
  value: string | null,
  scope: DraftScope,
): ReviewDraft[] {
  if (!value) return [];
  try {
    const stored = JSON.parse(value) as Partial<StoredDrafts>;
    if (
      stored.schema !== 1 ||
      stored.scope?.videoId !== scope.videoId ||
      stored.scope?.playerId !== scope.playerId ||
      stored.scope?.goalId !== scope.goalId ||
      !Array.isArray(stored.drafts) ||
      !stored.drafts.every(isDraft)
    ) {
      return [];
    }
    return stored.drafts as ReviewDraft[];
  } catch {
    return [];
  }
}

export function contentMatches(
  draft: DraftContent,
  synced: DraftContent | null,
): boolean {
  return Boolean(
    synced &&
      draft.clipStartMs === synced.clipStartMs &&
      draft.clipEndMs === synced.clipEndMs &&
      draft.verdict === synced.verdict &&
      draft.commentText === synced.commentText,
  );
}
