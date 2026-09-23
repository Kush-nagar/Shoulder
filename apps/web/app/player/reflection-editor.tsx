"use client";

import { useEffect, useState } from "react";
import type { PlayerReflection } from "../../lib/api";
import {
  clearReflectionDraft,
  type PendingReflectionSave,
  type ReflectionDraft,
  reflectionDraftKey,
  restoreReflectionDraft,
  serializeReflectionDraft,
} from "../../lib/reflection-drafts";

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const action = `inline-flex min-h-11 items-center justify-center rounded-lg border border-line-strong px-4 text-[16px] font-semibold disabled:cursor-not-allowed disabled:opacity-45 ${focus}`;

function newSave(
  text: string,
  reflection: PlayerReflection | null,
): PendingReflectionSave {
  return {
    idempotencyKey: crypto.randomUUID(),
    requestCreatedAt: new Date().toISOString(),
    intent: reflection ? "edit" : "create",
    expectedReflectionId: reflection?.id ?? null,
    expectedEtag: reflection?.etag ?? null,
    text,
  };
}

function sameSave(
  pending: PendingReflectionSave | undefined,
  text: string,
  reflection: PlayerReflection | null,
) {
  return (
    pending?.text === text &&
    pending.intent === (reflection ? "edit" : "create") &&
    pending.expectedReflectionId === (reflection?.id ?? null) &&
    pending.expectedEtag === (reflection?.etag ?? null) &&
    Date.now() - Date.parse(pending.requestCreatedAt) < 7 * 24 * 60 * 60 * 1000
  );
}

export function ReflectionEditor({
  playerId,
  judgmentId,
  initialReflection,
  evidenceAvailable,
  onSkip,
  onDelete,
  onChange,
}: {
  playerId: string;
  judgmentId: string;
  initialReflection: PlayerReflection | null;
  evidenceAvailable: boolean;
  onSkip?: () => void;
  onDelete?: () => void;
  onChange?: (reflection: PlayerReflection | null) => void;
}) {
  const [reflection, setReflection] = useState<PlayerReflection | null>(
    initialReflection,
  );
  const [draft, setDraft] = useState(initialReflection?.text ?? "");
  const [cached, setCached] = useState<ReflectionDraft | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const key = reflectionDraftKey(playerId, judgmentId);

  useEffect(() => {
    const restored = restoreReflectionDraft(window.localStorage.getItem(key));
    setReflection(initialReflection);
    // A missing active row after a queued delete means deletion won. Never
    // refill the textarea with text that was meant to be permanently removed.
    if (!initialReflection && restored?.pendingDelete) {
      window.localStorage.removeItem(key);
      setCached(null);
      setDraft("");
      return;
    }
    if (restored) {
      setCached(restored);
      setDraft(restored.text);
      return;
    }
    setCached(null);
    setDraft(initialReflection?.text ?? "");
  }, [initialReflection, key]);

  function persist(value: ReflectionDraft) {
    setCached(value);
    window.localStorage.setItem(key, serializeReflectionDraft(value));
  }

  function changeText(value: string) {
    setDraft(value);
    setStatus(null);
    persist({ text: value });
  }

  async function save() {
    if (!draft.trim() || draft.length > 1000) return;
    setSaving(true);
    setStatus("Saving…");
    const pending = sameSave(cached?.pending, draft, reflection)
      ? (cached?.pending as PendingReflectionSave)
      : newSave(draft, reflection);
    persist({ text: draft, pending });
    try {
      const response = await fetch(
        `/api/player/judgments/${judgmentId}/reflection`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": pending.idempotencyKey,
          },
          body: JSON.stringify({
            intent: pending.intent,
            text: pending.text,
            expected_reflection_id: pending.expectedReflectionId,
            expected_etag: pending.expectedEtag,
            request_created_at: pending.requestCreatedAt,
          }),
          cache: "no-store",
        },
      );
      if (!response.ok) {
        if (response.status === 409) {
          setStatus("This reflection changed. Reload before saving again.");
        } else if (response.status === 422) {
          persist({ text: draft });
          setStatus("Check the reflection length, then try again.");
        } else {
          setStatus("Could not save. Your text remains on this device.");
        }
        return;
      }
      const saved = (await response.json()) as PlayerReflection;
      setReflection(saved);
      setDraft(saved.text);
      setCached(null);
      clearReflectionDraft(window.localStorage, playerId, judgmentId);
      setStatus("Reflection saved.");
      onChange?.(saved);
    } catch {
      setStatus("Could not save. Your text remains on this device.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!reflection) return;
    setSaving(true);
    setStatus("Deleting…");
    const pendingDelete = cached?.pendingDelete;
    const reusable =
      pendingDelete?.expectedReflectionId === reflection.id &&
      pendingDelete.expectedEtag === reflection.etag
        ? pendingDelete
        : {
            idempotencyKey: crypto.randomUUID(),
            requestCreatedAt: new Date().toISOString(),
            expectedReflectionId: reflection.id,
            expectedEtag: reflection.etag,
          };
    persist({ text: draft, pendingDelete: reusable });
    try {
      const response = await fetch(
        `/api/player/judgments/${judgmentId}/reflection`,
        {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": reusable.idempotencyKey,
          },
          body: JSON.stringify({
            expected_reflection_id: reusable.expectedReflectionId,
            expected_etag: reusable.expectedEtag,
            request_created_at: reusable.requestCreatedAt,
          }),
          cache: "no-store",
        },
      );
      if (!response.ok) {
        setStatus(
          response.status === 409
            ? "This reflection changed. Reload before deleting it."
            : "Could not delete. Your reflection remains available.",
        );
        return;
      }
      clearReflectionDraft(window.localStorage, playerId, judgmentId);
      setCached(null);
      setDraft("");
      setReflection(null);
      setConfirmDelete(false);
      setStatus("Reflection deleted.");
      onChange?.(null);
      onDelete?.();
    } catch {
      setStatus("Could not delete. Your reflection remains available.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      aria-label="Your reflection"
      className="mt-6 rounded-[14px] border border-line bg-surface p-4"
    >
      {!evidenceAvailable ? (
        <p className="mb-3 text-[14px] font-semibold text-muted">
          Clip unavailable
        </p>
      ) : null}
      {reflection?.is_for_earlier_version ? (
        <p className="mb-3 text-[14px] leading-5 text-muted">
          Written for an earlier version of this clip
        </p>
      ) : null}
      <label
        htmlFor={`reflection-${judgmentId}`}
        className="text-[16px] font-semibold"
      >
        What did you notice?{" "}
        <span className="font-normal text-muted">(optional)</span>
      </label>
      <textarea
        id={`reflection-${judgmentId}`}
        value={draft}
        maxLength={1000}
        rows={4}
        disabled={!reflection && !evidenceAvailable}
        onChange={(event) => changeText(event.target.value)}
        className={`mt-2 block w-full resize-y rounded-lg border border-line-strong bg-paper p-3 text-[16px] leading-6 transition-colors duration-150 hover:border-ink-2 disabled:opacity-60 ${focus}`}
      />
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || !draft.trim() || draft.length > 1000}
          className={`${action} bg-action text-white hover:bg-action-hover`}
        >
          Save reflection
        </button>
        {onSkip ? (
          <button type="button" onClick={onSkip} className={action}>
            Skip for now
          </button>
        ) : null}
        {reflection ? (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            disabled={saving}
            className={`${action} text-error`}
          >
            Delete
          </button>
        ) : null}
      </div>
      {status ? (
        <p aria-live="polite" className="mt-3 text-[14px] leading-5 text-muted">
          {status}
        </p>
      ) : null}
      {confirmDelete ? (
        <div
          role="alertdialog"
          aria-labelledby={`delete-title-${judgmentId}`}
          className="mt-4 rounded-lg border border-error bg-error-soft p-4"
        >
          <h3 id={`delete-title-${judgmentId}`} className="font-semibold">
            Permanently delete this reflection?
          </h3>
          <p className="mt-2 text-[14px] leading-5">
            Shoulder removes the active copy. Backups may retain it for up to 30
            days, and copies outside Shoulder cannot be recalled.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => void remove()}
              disabled={saving}
              className={`${action} bg-error text-white`}
            >
              Delete permanently
            </button>
            <button
              type="button"
              onClick={() => setConfirmDelete(false)}
              disabled={saving}
              className={action}
            >
              Keep reflection
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
