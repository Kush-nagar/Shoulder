"use client";

import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { focus, secondaryButton } from "../../ui";

export function DeleteSession({ id }: { id: string }) {
  const router = useRouter();
  const keepRef = useRef<HTMLButtonElement>(null);
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The inline confirmation takes focus when it opens, on the safe choice.
  useEffect(() => {
    if (confirm) keepRef.current?.focus();
  }, [confirm]);

  async function remove() {
    setDeleting(true);
    setError(null);
    try {
      const response = await fetch(`/api/player/sessions/${id}`, {
        method: "DELETE",
        cache: "no-store",
      });
      if (!response.ok && response.status !== 404) throw new Error("delete");
      router.replace("/player/sessions");
      router.refresh();
    } catch {
      setError("Could not delete. Your session is unchanged. Try again.");
      setDeleting(false);
    }
  }

  if (!confirm) {
    return (
      <button
        type="button"
        onClick={() => setConfirm(true)}
        className={`-ml-1 inline-flex min-h-11 items-center gap-2 rounded-lg px-1 text-[16px] font-semibold text-error underline-offset-4 hover:underline ${focus}`}
      >
        <Trash2 size={18} strokeWidth={2} aria-hidden="true" />
        Delete this session
      </button>
    );
  }
  return (
    <div
      role="alertdialog"
      aria-labelledby="delete-session-title"
      aria-describedby="delete-session-body"
      className="max-w-[560px] rounded-xl border border-error bg-error-soft p-4 md:p-5"
    >
      <h2
        id="delete-session-title"
        className="text-[17px] font-semibold text-ink"
      >
        Delete this session?
      </h2>
      <p
        id="delete-session-body"
        className="mt-1 text-[16px] leading-6 text-ink"
      >
        It&apos;s removed now and can&apos;t be recovered.
      </p>
      {error ? (
        <p role="alert" className="mt-2 text-[16px] text-error">
          {error}
        </p>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void remove()}
          disabled={deleting}
          className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-error px-4 text-[16px] font-semibold text-paper transition-transform duration-150 active:scale-[0.98] disabled:opacity-45 ${focus}`}
        >
          <Trash2 size={18} strokeWidth={2} aria-hidden="true" />
          {deleting ? "Deleting…" : "Delete session"}
        </button>
        <button
          type="button"
          ref={keepRef}
          onClick={() => setConfirm(false)}
          disabled={deleting}
          className={secondaryButton}
        >
          Keep session
        </button>
      </div>
    </div>
  );
}
