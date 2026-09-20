export const REFLECTION_DRAFT_PREFIX = "shoulder:player-reflection:";

export type PendingReflectionSave = {
  idempotencyKey: string;
  requestCreatedAt: string;
  intent: "create" | "edit";
  expectedReflectionId: string | null;
  expectedEtag: string | null;
  text: string;
};

export type ReflectionDraft = {
  text: string;
  pending?: PendingReflectionSave;
  pendingDelete?: {
    idempotencyKey: string;
    requestCreatedAt: string;
    expectedReflectionId: string;
    expectedEtag: string;
  };
};

type StorageLike = Pick<
  Storage,
  "length" | "key" | "getItem" | "setItem" | "removeItem"
>;

export function reflectionDraftKey(playerId: string, judgmentId: string) {
  return `${REFLECTION_DRAFT_PREFIX}${playerId}:${judgmentId}`;
}

function pendingSave(value: unknown): value is PendingReflectionSave {
  if (!value || typeof value !== "object") return false;
  const pending = value as Partial<PendingReflectionSave>;
  return (
    typeof pending.idempotencyKey === "string" &&
    typeof pending.requestCreatedAt === "string" &&
    (pending.intent === "create" || pending.intent === "edit") &&
    (pending.expectedReflectionId === null ||
      typeof pending.expectedReflectionId === "string") &&
    (pending.expectedEtag === null ||
      typeof pending.expectedEtag === "string") &&
    typeof pending.text === "string"
  );
}

function pendingDelete(
  value: unknown,
): value is NonNullable<ReflectionDraft["pendingDelete"]> {
  if (!value || typeof value !== "object") return false;
  const pending = value as Partial<
    NonNullable<ReflectionDraft["pendingDelete"]>
  >;
  return (
    typeof pending.idempotencyKey === "string" &&
    typeof pending.requestCreatedAt === "string" &&
    typeof pending.expectedReflectionId === "string" &&
    typeof pending.expectedEtag === "string"
  );
}

export function restoreReflectionDraft(
  raw: string | null,
): ReflectionDraft | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<ReflectionDraft>;
    if (!value || typeof value.text !== "string") return null;
    if (value.pending !== undefined && !pendingSave(value.pending)) return null;
    if (
      value.pendingDelete !== undefined &&
      !pendingDelete(value.pendingDelete)
    )
      return null;
    return {
      text: value.text,
      ...(value.pending ? { pending: value.pending } : {}),
      ...(value.pendingDelete ? { pendingDelete: value.pendingDelete } : {}),
    };
  } catch {
    return null;
  }
}

export function serializeReflectionDraft(draft: ReflectionDraft) {
  return JSON.stringify(draft);
}

export function clearReflectionDraft(
  storage: StorageLike,
  playerId: string,
  judgmentId: string,
) {
  storage.removeItem(reflectionDraftKey(playerId, judgmentId));
}

export function clearAllReflectionDrafts(storage: StorageLike) {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(REFLECTION_DRAFT_PREFIX)) keys.push(key);
  }
  for (const key of keys) storage.removeItem(key);
}
