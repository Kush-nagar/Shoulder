"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import {
  componentTitle,
  dialog,
  label,
  metadata,
  primary,
  secondary,
  tertiary,
} from "../../ui";
import { closeGoal } from "./actions";

const choices = [
  ["achieved", "Achieved", "They are doing this now."],
  ["paused", "Paused", "Set aside for now; you can make it active again."],
  ["retired", "Retired", "No longer what they are working on."],
] as const;

/** Closing an active goal is the replacement step, so it is confirmed. */
export function CloseGoal({
  playerId,
  goalId,
  title,
}: {
  playerId: string;
  goalId: string;
  title: string;
}) {
  const [state, submit, pending] = useActionState(closeGoal, { message: "" });
  const box = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const groupId = useId();

  useEffect(() => {
    if (state.ok) box.current?.close();
  }, [state]);

  return (
    <>
      <button
        type="button"
        onClick={() => box.current?.showModal()}
        className={tertiary}
      >
        Close this goal
      </button>
      <dialog ref={box} aria-labelledby={titleId} className={dialog}>
        <form action={submit} className="p-5">
          <h2 id={titleId} className={componentTitle}>
            Close “{title}”?
          </h2>
          <p className="mt-3 text-[15px] leading-[1.5]">
            The goal moves to closed goals and stays readable. Set a new goal
            afterwards.
          </p>
          <input type="hidden" name="player_id" value={playerId} />
          <input type="hidden" name="goal_id" value={goalId} />
          <fieldset className="mt-4" aria-describedby={groupId}>
            <legend className={label}>What happened to this goal?</legend>
            <p id={groupId} className={`${metadata} mb-2`}>
              Choose one.
            </p>
            {choices.map(([value, name, help], index) => (
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
                  <span className="font-medium">{name}</span>
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
    </>
  );
}
