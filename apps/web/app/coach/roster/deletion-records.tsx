"use client";

import { useActionState } from "react";
import type { DeletionStatus } from "../../../lib/api";
import { componentTitle, metadata, panel, secondary } from "../ui";
import { confirmBackupExpiry } from "./actions";

type RecordItem = DeletionStatus & { backup_confirmation_due: boolean };

const statusCopy: Record<string, string> = {
  pending: "Cleanup queued",
  running: "Cleanup running",
  awaiting_backup: "Active systems cleared; backup expiry not yet verified",
  completed: "Deletion complete",
  unresolved: "Deletion needs operator attention",
};

function BackupConfirmation({ record }: { record: RecordItem }) {
  const [state, submit, pending] = useActionState(confirmBackupExpiry, {
    message: "",
  });
  if (record.status !== "awaiting_backup") return null;
  return (
    <form action={submit} className="mt-3">
      <input type="hidden" name="manifest_id" value={record.id} />
      <button
        type="submit"
        disabled={pending || !record.backup_confirmation_due}
        className={secondary}
      >
        {pending ? "Confirming…" : "Confirm actual backup expiry"}
      </button>
      {state.message ? (
        <p
          role={state.ok ? "status" : "alert"}
          className="mt-2 text-[15px] font-medium"
        >
          {state.message}
        </p>
      ) : null}
    </form>
  );
}

export function DeletionRecords({ records }: { records: RecordItem[] }) {
  if (records.length === 0) return null;
  return (
    <section
      className="mt-8 border-t border-line pt-5"
      aria-labelledby="deletion-title"
    >
      <h2 id="deletion-title" className={componentTitle}>
        Deletion operations
      </h2>
      <ul className="mt-3 space-y-3">
        {records.map((record) => (
          <li key={record.id} className={`${panel} max-w-170 p-4`}>
            <p className="text-[15px] font-medium">
              {statusCopy[record.status]}
            </p>
            <p className={`${metadata} mt-1`}>
              Requested {record.requested_at.slice(0, 10)} · backup deadline{" "}
              {record.backup_expires_at.slice(0, 10)}
            </p>
            {record.status === "unresolved" ? (
              <p
                role="alert"
                className="mt-2 text-[15px] leading-[1.5] text-error"
              >
                Cleanup is not complete. An operator must resolve the failed
                step; no completion is being claimed.
              </p>
            ) : null}
            <BackupConfirmation record={record} />
          </li>
        ))}
      </ul>
    </section>
  );
}
