"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import {
  componentTitle,
  field,
  focus,
  label,
  metadata,
  primary,
} from "../../ui";
import { createGoal } from "./actions";

/** One active goal at a time. The server refuses a second one. */
export function GoalForm({
  playerId,
  name,
}: {
  playerId: string;
  name: string;
}) {
  const [state, submit, pending] = useActionState(createGoal, { message: "" });
  const form = useRef<HTMLFormElement>(null);
  const titleId = useId();
  const detailId = useId();
  const headingId = useId();

  useEffect(() => {
    if (state.ok) form.current?.reset();
  }, [state]);

  return (
    <form
      ref={form}
      action={submit}
      aria-labelledby={headingId}
      className="max-w-170"
    >
      <h3 id={headingId} className={componentTitle}>
        Set a goal
      </h3>
      <p className={`${metadata} mt-1`}>
        One sentence about what {name} is working on. Only you write this.
      </p>
      <input type="hidden" name="player_id" value={playerId} />
      <label htmlFor={titleId} className={`${label} mt-4`}>
        Goal (required)
      </label>
      <input
        id={titleId}
        name="title"
        type="text"
        required
        maxLength={100}
        autoComplete="off"
        className={`${field} mt-1`}
      />
      <label htmlFor={detailId} className={`${label} mt-4`}>
        Detail for yourself
      </label>
      <textarea
        id={detailId}
        name="description"
        rows={3}
        maxLength={1000}
        className={`mt-1 w-full rounded-lg border border-line bg-white p-3 text-[15px] leading-[1.5] text-ink hover:border-muted ${focus}`}
      />
      <div className="mt-4">
        <button type="submit" disabled={pending} className={primary}>
          {pending ? "Saving…" : "Set a goal"}
        </button>
      </div>
      {state.message ? (
        <p
          role={state.ok ? "status" : "alert"}
          className="mt-3 text-[15px] font-medium"
        >
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
