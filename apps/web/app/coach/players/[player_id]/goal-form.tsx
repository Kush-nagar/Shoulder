"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import {
  componentTitle,
  dialog,
  field,
  focus,
  label,
  metadata,
  panel,
  primary,
  secondary,
  tertiary,
} from "../../ui";
import { goalAction } from "./actions";

export type ActiveGoal = {
  id: string;
  title: string;
  description: string | null;
  setOn: string;
};

const choices = [
  ["achieved", "Achieved", "They are doing this now."],
  ["paused", "Paused", "Set aside for now; you can make it active again."],
  ["retired", "Retired", "No longer what they are working on."],
] as const;

/**
 * One active goal at a time; the server refuses a second one.
 *
 * Setting a goal replaces the form with the panel, and closing one does the
 * reverse. A component that unmounts on success takes its own confirmation with
 * it and leaves a screen reader silent, so both actions are owned here, by the
 * one component that survives either swap.
 */
export function GoalSection({
  playerId,
  name,
  active,
}: {
  playerId: string;
  name: string;
  active: ActiveGoal | null;
}) {
  // One hook for both writes: the newest outcome always wins, which two hooks
  // could not guarantee.
  const [state, submit, pending] = useActionState(goalAction, { message: "" });
  const form = useRef<HTMLFormElement>(null);
  const box = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const detailId = useId();
  const headingId = useId();
  const closeId = useId();
  const groupId = useId();

  useEffect(() => {
    if (!state.ok) return;
    form.current?.reset();
    box.current?.close();
  }, [state]);

  // Announced from a slot that outlives both the panel and the form.
  const announcement = state.message ? (
    <p
      role={state.ok ? "status" : "alert"}
      className="mt-3 text-[15px] font-medium"
    >
      {state.message}
    </p>
  ) : null;

  const closeDialog = active ? (
    <dialog ref={box} aria-labelledby={closeId} className={dialog}>
      <form action={submit} className="p-5">
        <input type="hidden" name="intent" value="close" />
        <h2 id={closeId} className={componentTitle}>
          Close “{active.title}”?
        </h2>
        <p className="mt-3 text-[15px] leading-[1.5]">
          The goal moves to closed goals and stays readable. Set a new goal
          afterwards.
        </p>
        <input type="hidden" name="player_id" value={playerId} />
        <input type="hidden" name="goal_id" value={active.id} />
        <fieldset className="mt-4" aria-describedby={groupId}>
          <legend className={label}>What happened to this goal?</legend>
          <p id={groupId} className={`${metadata} mb-2`}>
            Choose one.
          </p>
          {choices.map(([value, choice, help], index) => (
            <label
              key={value}
              className="flex items-start gap-3 py-1.5 text-[15px]"
            >
              <input
                type="radio"
                name="status"
                value={value}
                defaultChecked={index === 0}
                className="mt-1 size-4 accent-ink"
              />
              <span>
                <span className="font-medium">{choice}</span>
                <span className={`${metadata} block`}>{help}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="mt-5 flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={() => box.current?.close()}
            className={secondary}
          >
            Keep it active
          </button>
          <button type="submit" disabled={pending} className={primary}>
            {pending ? "Saving…" : "Close goal"}
          </button>
        </div>
        {state.message && !state.ok ? (
          <p role="alert" className="mt-3 text-[15px] font-medium">
            {state.message}
          </p>
        ) : null}
      </form>
    </dialog>
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
          <div className="mt-4 border-t border-line pt-4">
            <button
              type="button"
              onClick={() => box.current?.showModal()}
              className={tertiary}
            >
              Close this goal
            </button>
          </div>
        </div>
        {closeDialog}
        {announcement}
      </div>
    );
  }

  return (
    <div className="mt-3 max-w-170">
      <form ref={form} action={submit} aria-labelledby={headingId}>
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
          className={`mt-1 w-full rounded-lg border border-line bg-surface p-3 text-[15px] leading-[1.5] text-ink hover:border-muted ${focus}`}
        />
        <div className="mt-4">
          <button type="submit" disabled={pending} className={primary}>
            {pending ? "Saving…" : "Set a goal"}
          </button>
        </div>
      </form>
      {announcement}
    </div>
  );
}
