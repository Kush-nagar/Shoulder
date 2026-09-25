"use client";

import { Check, ExternalLink } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { send } from "../../coaching/client";
import type {
  CoachStatus,
  Decision,
  ReviewDocumentUrl,
} from "../../coaching/types";
import {
  field,
  fieldError,
  focus,
  hint,
  label,
  primaryButton,
  secondaryButton,
  toggleChip,
} from "../../coaching/ui";

const OFFLINE = "Shoulder couldn't be reached. Nothing changed. Try again.";

const allowed: Record<CoachStatus, Decision[]> = {
  draft: [],
  pending_review: ["approve", "reject"],
  rejected: ["approve"],
  verified: ["suspend"],
  suspended: ["reinstate"],
};

const names: Record<Decision, string> = {
  approve: "Approve",
  reject: "Reject",
  suspend: "Suspend",
  reinstate: "Reinstate",
};

/** Every decision needs a note; it goes to the audit log and, for reject and suspend, the coach. */
export function DecisionForm({
  id,
  status,
}: {
  id: string;
  status: CoachStatus;
}) {
  const router = useRouter();
  const options = allowed[status];
  const [decision, setDecision] = useState<Decision | null>(options[0] ?? null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!options.length)
    return (
      <p className={hint}>
        No decision is available until the coach sends the profile for review.
      </p>
    );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!decision) return;
    setBusy(true);
    setError(null);
    const reply = await send(
      `/api/admin/coach-reviews/${id}/decision`,
      "POST",
      {
        decision,
        note: note.trim(),
      },
    );
    setBusy(false);
    if (reply.status >= 200 && reply.status < 300) {
      setNote("");
      router.refresh();
    } else
      setError(
        reply.status === 409
          ? "The profile changed since this page loaded. Reload and check again."
          : reply.status === 0
            ? OFFLINE
            : "The decision wasn't saved. Try again.",
      );
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <fieldset disabled={busy}>
        <legend className={label}>Decision</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {options.map((option) => (
            <label key={option} className={toggleChip}>
              <input
                type="radio"
                name="decision"
                className="sr-only"
                checked={decision === option}
                onChange={() => setDecision(option)}
              />
              {names[option]}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="space-y-2">
        <label htmlFor="decision-note" className={label}>
          Note
        </label>
        <textarea
          id="decision-note"
          required
          minLength={3}
          maxLength={500}
          rows={4}
          value={note}
          disabled={busy}
          onChange={(event) => setNote(event.target.value)}
          aria-describedby="decision-note-hint"
          className={`${field} py-2 leading-6`}
        />
        <p id="decision-note-hint" className={hint}>
          Required. Recorded in the audit log. The coach sees it when you reject
          or suspend. {500 - note.length} characters left.
        </p>
      </div>
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={busy || !decision || note.trim().length < 3}
        className={primaryButton}
      >
        {busy ? "Saving…" : decision ? `${names[decision]} coach` : "Save"}
      </button>
    </form>
  );
}

/** Signs one document URL on click (each open is audited) and opens it in a new tab. */
export function OpenDocument({
  profileId,
  documentId,
}: {
  profileId: string;
  documentId: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function open() {
    // Opened synchronously so the popup blocker allows it; filled once signed.
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    setBusy(true);
    setError(null);
    const reply = await send<ReviewDocumentUrl>(
      `/api/admin/coach-reviews/${profileId}/documents/${documentId}/url`,
      "GET",
    );
    setBusy(false);
    const url = reply.data?.url;
    if (tab && url?.startsWith("https://")) tab.location.href = url;
    else {
      tab?.close();
      setError(
        reply.status === 0 ? OFFLINE : "The document didn't open. Try again.",
      );
    }
  }
  return (
    <div className="space-y-1 text-right">
      <button
        type="button"
        onClick={() => void open()}
        disabled={busy}
        className={`inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-[15px] font-semibold text-action underline-offset-4 hover:underline ${focus}`}
      >
        {busy ? "Opening…" : "Open"}
        <ExternalLink size={16} strokeWidth={2} aria-hidden="true" />
        <span className="sr-only">(opens in a new tab)</span>
      </button>
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function ResolveReport({ id }: { id: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function resolve() {
    setBusy(true);
    setError(null);
    const reply = await send(`/api/admin/reports/${id}/resolve`, "POST");
    setBusy(false);
    if (reply.status >= 200 && reply.status < 300) router.refresh();
    else setError(reply.status === 0 ? OFFLINE : "Not resolved. Try again.");
  }
  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => void resolve()}
        disabled={busy}
        className={secondaryButton}
      >
        <Check size={18} strokeWidth={2} aria-hidden="true" />
        {busy ? "Resolving…" : "Mark resolved"}
      </button>
      {error ? (
        <p role="alert" className={fieldError}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
