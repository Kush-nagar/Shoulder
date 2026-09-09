"use client";

import type { ReactNode } from "react";
import { useActionState, useEffect, useId, useRef } from "react";
import {
  componentTitle,
  field,
  focus,
  label,
  metadata,
  panel,
  primary,
} from "../../ui";
import { createGoal } from "./actions";

export type ActiveGoal = {
  title: string;
  description: string | null;
  setOn: string;
};

/**
 * One active goal at a time; the server refuses a second one.
 *
 * The panel and the form live in one mounted component on purpose. Setting a
 * goal replaces the form with the panel, and a component that unmounts takes
 * its own confirmation with it — leaving a screen reader with silence. Owning
 * both states keeps the live region alive across that swap.
 */
export function GoalSection({
  playerId,
  name,
  active,
  children,
}: {
  playerId: string;
  name: string;
  active: ActiveGoal | null;
  children?: ReactNode;
}) {
  const [state, submit, pending] = useActionState(createGoal, { message: "" });
  const form = useRef<HTMLFormElement>(null);
  const titleId = useId();
  const detailId = useId();
  const headingId = useId();

  useEffect(() => {
    if (state.ok) form.current?.reset();
  }, [state]);

  const message = state.message ? (
    <p
      role={state.ok ? "status" : "alert"}
      className="mt-3 text-[15px] font-medium"
    >
      {state.message}
    </p>
  ) : null;

  if (active) {
    return (
      <div className="mt-3 max-w-170">
        <div className={`${panel} p-5`}>
          <p className="text-[17px] leading-[1.35] font-semibold">
            {active.title}
          </p>
          {active.description ? (
            <p className="mt-3 text-[15px] leading-[1.5]">
              {active.description}
            </p>
          ) : null}
          <p className={`${metadata} mt-4`}>Set {active.setOn}</p>
          {children ? (
            <div className="mt-4 border-t border-line pt-4">{children}</div>
          ) : null}
        </div>
        {message}
      </div>
    );
  }

  return (
    <form
      ref={form}
      action={submit}
      aria-labelledby={headingId}
      className="mt-3 max-w-170"
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
      {message}
    </form>
  );
}
