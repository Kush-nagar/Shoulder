"use client";

import { useActionState, useId } from "react";
import { componentTitle, field, label, metadata, panel, primary } from "../ui";
import { confirmRetention } from "./actions";

export function RetentionSetup({ seasonEndAt }: { seasonEndAt: string }) {
  const [state, submit, pending] = useActionState(confirmRetention, {
    message: "",
  });
  const backupId = useId();
  const season = seasonEndAt.slice(0, 10);
  return (
    <section
      className={`${panel} mb-6 max-w-170 p-5`}
      aria-labelledby="retention-title"
    >
      <h2 id="retention-title" className={componentTitle}>
        Confirm retention before uploading footage
      </h2>
      <p className="mt-2 text-[15px] leading-[1.5] text-muted">
        The season cutoff is {season}. This becomes immutable after
        confirmation.
      </p>
      <form action={submit} className="mt-4 space-y-4">
        <div className="max-w-56">
          <label htmlFor={backupId} className={label}>
            Provider backup maximum (days)
          </label>
          <input
            id={backupId}
            name="provider_backup_max_days"
            type="number"
            inputMode="numeric"
            min={1}
            max={30}
            required
            className={`${field} mt-1`}
          />
        </div>
        <label className="flex max-w-170 items-start gap-3 text-[15px] leading-[1.5]">
          <input
            name="season_cutoff_confirmed"
            type="checkbox"
            required
            className="mt-1"
          />
          <span>
            I confirm {season} is this workspace&apos;s season cutoff.
          </span>
        </label>
        <label className="flex max-w-170 items-start gap-3 text-[15px] leading-[1.5]">
          <input
            name="provider_backup_expiry_confirmed"
            type="checkbox"
            required
            className="mt-1"
          />
          <span>
            I verified this maximum against the actual backup policy for every
            provider that stores Shoulder data.
          </span>
        </label>
        <label className="flex max-w-170 items-start gap-3 text-[15px] leading-[1.5]">
          <input
            name="collateral_deletion_confirmed"
            type="checkbox"
            required
            className="mt-1"
          />
          <span>
            I understand that deleting one player from shared footage deletes
            the team video and every player’s clips from it.
          </span>
        </label>
        <label className="flex max-w-170 items-start gap-3 text-[15px] leading-[1.5]">
          <input
            name="notice_confirmed"
            type="checkbox"
            required
            className="mt-1"
          />
          <span>
            I have the required player and guardian deletion notice ready.
          </span>
        </label>
        <label className="flex max-w-170 items-start gap-3 text-[15px] leading-[1.5]">
          <input
            name="operator_confirmed"
            type="checkbox"
            required
            className="mt-1"
          />
          <span>
            I am the responsible operator who will verify active and backup
            deletion.
          </span>
        </label>
        <button type="submit" disabled={pending} className={primary}>
          {pending ? "Confirming…" : "Confirm retention setup"}
        </button>
        {state.message ? (
          <p
            role={state.ok ? "status" : "alert"}
            className="text-[15px] font-medium"
          >
            {state.message}
          </p>
        ) : (
          <p className={metadata}>
            Nothing is confirmed until you submit this form.
          </p>
        )}
      </form>
    </section>
  );
}
